"""Explicit, bounded dual-surface smoke. No reference actor or automatic paid calls."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import math
import re
import time
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from commerce_eval.contracts import ExperimentSpecV1, ResourceUsageV1, TraceEnvelopeV1
from commerce_eval.core import content_checksum
from commerce_eval.core.redaction import contains_secret, redact_recursive
from commerce_eval.experiments import ExperimentRunner
from commerce_eval.providers import NativeCompatibleClient, ProviderConfigService, ProviderError, parse_usage
from commerce_eval.storage import Database, Repository
from commerce_eval.targets.business_candidate import BusinessCandidateTarget

from .bootstrap import SURFACES, VERSION, seed_business_bank
from .candidates import ModelRequestBudget

DEFAULT_CASES = ("I01", "C03", "T01", "P01", "A03", "M02", "R03", "S02")
MAX_MODEL_CALLS = 128
DEFAULT_MODEL_TIMEOUT_SECONDS = 120.0
DEFAULT_CASE_TIMEOUT_MS = 300000
DEFAULT_MAX_COMPLETION_TOKENS = 4096
_UNCOMPLETED = {"model_request_budget_exhausted", "provider_call_budget_exhausted",
               "candidate_round_limit", "candidate_timeout", "target_timeout", "provider_timeout",
               "target_cancelled", "smoke_cancelled", "smoke_run_not_completed"}
_PROVIDER_PREFLIGHT_ERRORS = {
    "paid_call_not_authorized", "provider_disabled", "provider_endpoint_not_confirmed",
    "provider_credential_missing", "provider_address_forbidden", "provider_https_required",
    "provider_url_invalid", "credential_reference_invalid", "central_env_invalid",
    "central_env_unavailable", "central_env_too_large", "central_env_link_forbidden",
    "provider_messages_invalid", "provider_tools_invalid", "provider_request_too_large",
    "provider_call_budget_exhausted", "provider_version_not_found",
}
_ENVIRONMENT_ERRORS = {
    "paid_call_not_authorized", "paid_calls_disabled", "provider_disabled",
    "provider_endpoint_not_confirmed", "provider_credential_missing", "provider_not_configured",
    "model_client_missing", "provider_address_forbidden", "provider_https_required",
    "provider_url_invalid", "credential_reference_invalid", "central_env_invalid",
    "central_env_unavailable", "central_env_too_large", "central_env_link_forbidden",
    "provider_version_not_found", "provider_timeout", "provider_disconnected",
    "provider_authentication_denied", "provider_permission_denied", "provider_rate_limited",
    "provider_backend_error", "provider_redirect_refused", "provider_request_rejected",
    "provider_invalid_response", "provider_response_too_large",
}


class SmokeError(Exception):
    """Only fixed error codes are printed by the CLI."""


def _validate_selection(project_id, provider_id, provider_version, model, max_calls, timeout_ms,
                        model_timeout_seconds, max_completion_tokens):
    if not all(isinstance(value, str) and value.strip() and not contains_secret(value)
               and not any(ord(char) < 32 for char in value) for value in (project_id, provider_id, model)):
        raise SmokeError("smoke_configuration_invalid")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", project_id):
        raise SmokeError("smoke_project_invalid")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,119}", provider_id) or len(model) > 160:
        raise SmokeError("smoke_model_configuration_invalid")
    if isinstance(provider_version, bool) or not str(provider_version).isdigit() or int(provider_version) < 1:
        raise SmokeError("smoke_provider_version_invalid")
    if type(max_calls) is not int or not 1 <= max_calls <= MAX_MODEL_CALLS:
        raise SmokeError("smoke_call_budget_invalid")
    if type(timeout_ms) is not int or not 100 <= timeout_ms <= 300000:
        raise SmokeError("smoke_timeout_invalid")
    if (type(model_timeout_seconds) not in (int, float) or not 0 < model_timeout_seconds <= 300
            or not math.isfinite(model_timeout_seconds)):
        raise SmokeError("smoke_model_timeout_invalid")
    if type(max_completion_tokens) is not int or not 1 <= max_completion_tokens <= 32768:
        raise SmokeError("smoke_completion_budget_invalid")


class _ObservedCompletion:
    def __init__(self, complete, *, clock):
        self.complete = complete
        self.clock = clock
        self.calls = 0
        self.preflight_rejections = 0
        self.usage = []
        self.latency_ms = 0.0

    async def __call__(self, messages, tools):
        self.calls += 1
        began = self.clock()
        result = None
        try:
            result = self.complete(messages=messages, tools=tools)
            if inspect.isawaitable(result):
                result = await result
            return result
        except ProviderError as exc:
            if isinstance(exc.code, str) and exc.code in _PROVIDER_PREFLIGHT_ERRORS:
                self.preflight_rejections += 1
            raise
        finally:
            self.latency_ms += max(0.0, (self.clock() - began) * 1000)
            usage = result.get("usage") if isinstance(result, dict) else None
            # Store accounting only, never messages, answers, arguments or errors.
            normalized = parse_usage(usage)
            if isinstance(usage, dict):
                for name in ("cache_hit_tokens", "cache_miss_tokens"):
                    value = usage.get(name)
                    if type(value) is int and value >= 0:
                        normalized[name] = value
            self.usage.append(normalized)


def _sum_known(values):
    if not values or any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        return None
    return sum(values)


def _resources(records):
    result = {}
    for name in ResourceUsageV1.model_fields:
        values = [record.get(name) for record in records]
        if name in {"currency", "price_card_version", "cost_status"}:
            result[name] = values[0] if values and all(value == values[0] for value in values) else None
        else:
            result[name] = _sum_known(values)
    # No smoke price card is supplied. Never convert unknown costs into zero.
    result.update(estimated_cost=None, currency=None, price_card_version=None, cost_status="price_card_unavailable")
    return result


def _error_codes(detail):
    trace = detail["trace"]
    codes = {str(trace.get("output", {}).get("error_type") or ""),
             str(trace.get("metadata", {}).get("protocol_error") or "")}
    for container in (trace.get("output", {}), trace.get("metadata", {})):
        cause = container.get("provider_error_type")
        if isinstance(cause, str) and cause in _ENVIRONMENT_ERRORS | _PROVIDER_PREFLIGHT_ERRORS:
            codes.add(cause)
    for event in trace.get("events", []):
        if event.get("kind") == "error":
            attrs = event.get("attributes", {})
            codes.update(str(attrs.get(key) or "") for key in ("error_type", "reason_code", "reason"))
            cause = attrs.get("provider_error_type")
            if isinstance(cause, str) and cause in _ENVIRONMENT_ERRORS | _PROVIDER_PREFLIGHT_ERRORS:
                codes.add(cause)
    return codes - {""}


def _classify(detail):
    trace = detail["trace"]
    codes = _error_codes(detail)
    if trace["status"] == "failed" and codes & _ENVIRONMENT_ERRORS:
        return "uncompleted"
    if codes & _UNCOMPLETED or trace["status"] in {"queued", "running", "awaiting_input", "awaiting_confirmation", "cancelled", "interrupted"}:
        return "uncompleted"
    if trace["status"] == "failed":
        return "error"
    gates = detail.get("gates", [])
    gated = {item.get("metric_id") for item in gates}
    metrics = {item.get("metric_id"): item for item in detail.get("metrics", [])}
    if any(metrics.get(name, {}).get("status") == "error" for name in gated):
        return "error"
    if detail.get("overall_pass") is True:
        return "pass"
    if detail.get("overall_pass") is False:
        return "fail"
    return "error"


def _failure_category(detail, verdict):
    if verdict == "uncompleted":
        return "environment_unavailable" if _error_codes(detail) & _ENVIRONMENT_ERRORS else "execution_incomplete"
    if verdict == "error":
        return "execution_error" if detail["trace"]["status"] == "failed" else "evaluation_error"
    return "business_failure" if verdict == "fail" else None


def _call_accounting(observed, budget, native_calls, *, native_client):
    # Native call_count increments before DNS/HTTP validation, not at HTTP send.
    no_http = native_client and observed.calls == observed.preflight_rejections
    return {"limit": budget.max_calls, "candidate_attempts": budget.calls,
            "callback_invocations": observed.calls, "provider_budget_attempts": native_calls,
            "provider_preflight_rejections": observed.preflight_rejections if native_client else None,
            "http_requests_sent": 0 if no_http else None,
            "http_count_status": "preflight_only_no_send" if no_http else "not_instrumented",
            "billable_requests": None,
            "remaining": max(0, budget.max_calls - budget.calls), "budget_exhausted": budget.calls >= budget.max_calls,
            "count_semantics": {
                "provider_budget_attempts": "client_budget_consumptions_including_preflight_rejections_not_http_sends",
                "provider_preflight_rejections": "known_native_client_rejections_before_http_send",
                "http_requests_sent": "zero_only_when_all_native_invocations_are_preflight_rejections_otherwise_unknown",
                "billable_requests": "not_observed",
            }}


def _preserve_missing_runs(repository, spec, *, reason):
    """A runner failure is a platform record, not an invented model trajectory."""
    cases = repository.get_dataset(spec.project_id, spec.dataset_id, spec.dataset_version)["cases"]
    for case in cases:
        if repository.run_exists(spec.experiment_id, case["case_id"], 1):
            continue
        now = datetime.now(timezone.utc)
        trace = TraceEnvelopeV1(
            contract_version="1.2", trace_id="smoke-uncompleted-" + uuid4().hex,
            project_id=spec.project_id, target_id=spec.target_id, target_version=spec.target_version,
            experiment_id=spec.experiment_id, case_id=case["case_id"], repetition=1,
            dataset_version=spec.dataset_version, tool_contract_set_id=spec.tool_contract_set_id,
            tool_contract_version=spec.tool_contract_version, evaluator_set_version=spec.evaluator_set_version,
            started_at=now, ended_at=now, status="cancelled" if reason == "smoke_cancelled" else "failed",
            input={"message": case.get("input", {}).get("message", "")},
            output={"error_type": reason, "task_completed": False},
            metadata={"source": "smoke_runner", "model_trace_unavailable": True,
                      "provider_id": spec.provider_id, "provider_version": spec.provider_version, "model": spec.model},
            tags={"execution": "simulated", "actor": "runner_failure_record"},
            events=[{"event_id": "runner-failure", "sequence": 0, "kind": "error", "status": "error",
                     "attributes": {"source": "smoke_runner", "error_type": reason}}],
        )
        repository.save_trace(trace)


def _experiment_summary(repository, spec):
    experiment = repository.get_experiment(spec.experiment_id)
    rows = repository.list_traces(project_id=spec.project_id, experiment_id=spec.experiment_id, limit=500)
    cases = repository.get_dataset(spec.project_id, spec.dataset_id, spec.dataset_version)["cases"]
    scenarios = {case["case_id"]: case.get("scenario_id") for case in cases}
    counts = dict.fromkeys(("pass", "fail", "error", "uncompleted"), 0)
    runs, resources = [], []
    for row in rows:
        detail = repository.get_trace(row["trace_id"])
        verdict = _classify(detail)
        counts[verdict] += 1
        resources.append(detail["trace"]["resource_usage"])
        runs.append({"trace_id": row["trace_id"], "case_id": row["case_id"],
                     "scenario_id": scenarios.get(row["case_id"]), "run_status": row["status"],
                     "verdict": verdict, "overall_pass": detail["overall_pass"],
                     "failure_category": _failure_category(detail, verdict),
                     "evaluation_id": detail.get("evaluation_id"),
                     "error_codes": sorted(_error_codes(detail))})
    counts["uncompleted"] += max(0, experiment["total_runs"] - len(rows))
    return {"experiment_id": spec.experiment_id, "surface": spec.tags["surface"],
            "status": experiment["status"], "expected_runs": experiment["total_runs"],
            "recorded_runs": len(rows), "counts": counts,
            "environment_unavailable_runs": sum(run["failure_category"] == "environment_unavailable" for run in runs),
            "resource_usage": _resources(resources),
            "runs": sorted(runs, key=lambda row: row["scenario_id"] or row["case_id"])}, resources


async def run_business_smoke(repository: Repository, *, project_id: str, provider_id: str,
                             provider_version: int | str, model: str, allow_paid: bool = False,
                             service=None, client=None, complete: Callable | None = None,
                             template_ids=None, max_calls: int = MAX_MODEL_CALLS,
                             timeout_ms: int = DEFAULT_CASE_TIMEOUT_MS,
                             model_timeout_seconds: float = DEFAULT_MODEL_TIMEOUT_SECONDS,
                             max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
                             clock=time.monotonic) -> dict:
    """Same model callback and total budget for both real candidate tool surfaces.

    Injected services/clients/callbacks are test seams, not reference answers. CLI
    runs always build one NativeCompatibleClient and require explicit paid consent.
    model_timeout_seconds bounds each native request, while timeout_ms bounds the
    whole case across calls and interactions. Injected callbacks own their provider
    limits; the target/runner still enforce the remaining whole-case deadline.
    """
    if allow_paid is not True:
        raise SmokeError("paid_call_not_authorized")
    _validate_selection(project_id, provider_id, provider_version, model, max_calls, timeout_ms,
                        model_timeout_seconds, max_completion_tokens)
    if client is not None and complete is not None:
        raise SmokeError("smoke_client_or_callback_required")
    provider_version = int(provider_version)
    model_timeout_seconds = float(model_timeout_seconds)
    mode = "injected_callback" if complete is not None else "injected_client" if client is not None else "real_model"
    if complete is None:
        if client is None:
            service = service if service is not None else ProviderConfigService(repository.database)
            transport = getattr(service, "transport", None)
            if transport is not None:
                mode = "injected_transport"
            client = NativeCompatibleClient(service, provider_id=provider_id, version=provider_version,
                model=model, allow_paid=True, max_calls=max_calls, transport=transport,
                dns_resolver=getattr(service, "dns_resolver", None), timeout_seconds=model_timeout_seconds,
                max_completion_tokens=max_completion_tokens)
        for name, expected in (("provider_id", provider_id), ("version", provider_version), ("model", model),
                               ("timeout_seconds", model_timeout_seconds), ("max_calls", max_calls),
                               ("max_completion_tokens", max_completion_tokens)):
            if hasattr(client, name) and getattr(client, name) != expected:
                raise SmokeError("smoke_client_configuration_mismatch")
        complete = client.complete
    if not callable(complete):
        raise SmokeError("smoke_model_callback_required")
    try:
        repository.get_project(project_id)
    except KeyError:
        repository.create_project(project_id, "Business acceptance smoke", "Synthetic dual-surface model evaluation")
    seeded = seed_business_bank(repository, project_id, template_ids=list(DEFAULT_CASES) if template_ids is None else template_ids)
    smoke_id = "smoke-" + uuid4().hex
    limits = {"model_timeout_seconds": model_timeout_seconds, "whole_case_timeout_ms": timeout_ms,
              "max_completion_tokens": max_completion_tokens, "total_model_request_limit": max_calls}
    model_config_version = "model-" + content_checksum({"provider_id": provider_id,
        "provider_version": provider_version, "model": model, **limits})[:48]
    specs = []
    for index, raw in enumerate(seeded["candidate_experiment_specs"]):
        surface = SURFACES[index]
        spec = ExperimentSpecV1.model_validate({**raw, "experiment_id": f"{smoke_id}-{surface}",
            "name": f"{surface} model smoke", "repetitions": 1, "concurrency": 1, "timeout_ms": timeout_ms,
            "provider_id": provider_id, "provider_version": str(provider_version), "model": model,
            "allow_paid": True, "model_config_version": model_config_version,
            "tags": {**raw.get("tags", {}), "smoke_id": smoke_id, "surface": surface,
                     "model_source": mode, "execution": "simulated",
                     **{name: str(value) for name, value in limits.items()}}})
        specs.append(spec)
    # Both immutable specs exist before the first candidate/model can fail.
    with repository.transaction() as transaction:
        for spec in specs:
            transaction.create_experiment(spec)
    budget = ModelRequestBudget(max_calls)
    observed = _ObservedCompletion(complete, clock=clock)
    initial_native_calls = getattr(client, "call_count", None)

    def target_factory(definition):
        runtime_definition = definition.model_copy(update={"config": {**definition.config,
            "model_source": mode, "provider_id": provider_id, "model": model}})
        return BusinessCandidateTarget(runtime_definition, complete=observed, request_budget=budget)

    cancelled = False
    for spec in specs:
        if cancelled:
            repository.update_experiment(spec.experiment_id, status="cancelled", error_type="smoke_cancelled")
            _preserve_missing_runs(repository, spec, reason="smoke_cancelled")
            continue
        try:
            # A fresh runner per experiment, but exactly one callback/client/budget.
            await ExperimentRunner(repository, target_factory=target_factory).run(spec)
        except asyncio.CancelledError:
            cancelled = True
            repository.update_experiment(spec.experiment_id, status="cancelled", error_type="smoke_cancelled")
            _preserve_missing_runs(repository, spec, reason="smoke_cancelled")
        except Exception:
            repository.update_experiment(spec.experiment_id, status="failed", error_type="smoke_runner_failed")
            _preserve_missing_runs(repository, spec, reason="smoke_runner_failed")
        else:
            _preserve_missing_runs(repository, spec, reason="smoke_run_not_completed")
    experiments, resources = [], []
    for spec in specs:
        summary, usage = _experiment_summary(repository, spec)
        experiments.append(summary)
        resources.extend(usage)
    counts = {name: sum(experiment["counts"][name] for experiment in experiments)
              for name in ("pass", "fail", "error", "uncompleted")}
    final_native_calls = getattr(client, "call_count", None)
    native_calls = final_native_calls - initial_native_calls if type(initial_native_calls) is int and type(final_native_calls) is int else None
    environment_runs = sum(experiment["environment_unavailable_runs"] for experiment in experiments)
    result = {"smoke_id": smoke_id, "version": VERSION, "project_id": project_id,
        "provider_id": provider_id, "provider_version": str(provider_version), "model": model,
        "model_config_version": model_config_version, "limits": limits,
        "model_source": mode, "execution": "simulated", "live_side_effect": False,
        "cancelled": cancelled, "case_count": seeded["case_count"], "total_runs": seeded["case_count"] * 2,
        "counts": counts, "overall_pass": all(counts[key] == 0 for key in ("fail", "error", "uncompleted")),
        "environment_unavailable_runs": environment_runs,
        "calls": _call_accounting(observed, budget, native_calls, native_client=isinstance(client, NativeCompatibleClient)),
        "resource_usage": _resources(resources),
        "model_usage": {**{name: _sum_known([usage[name] for usage in observed.usage]) for name in parse_usage(None)},
                        "callback_latency_ms": observed.latency_ms, "estimated_cost": None},
        "experiments": experiments}
    return redact_recursive(result, max_depth=24, max_items=10000, max_chars=10000)


def main(argv=None, *, run_fn=None) -> int:
    parser = argparse.ArgumentParser(description="Explicit paid, synthetic dual-surface business smoke")
    parser.add_argument("--database", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--provider-version", type=int, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-timeout-seconds", type=float, default=DEFAULT_MODEL_TIMEOUT_SECONDS,
                        help="Per-model-call timeout in seconds (0 < value <= 300; default: 120)")
    parser.add_argument("--timeout-ms", type=int, default=DEFAULT_CASE_TIMEOUT_MS,
                        help="Whole-case timeout across calls and interactions in milliseconds (default: 300000)")
    parser.add_argument("--allow-paid", action="store_true", help="Authorize up to 128 total model requests; provider charges may apply")
    args = parser.parse_args(argv)
    if not args.allow_paid:
        print(json.dumps({"error_type": "paid_call_not_authorized", "executed": False}))
        return 2
    database = None
    try:
        _validate_selection(args.project, args.provider, args.provider_version, args.model, MAX_MODEL_CALLS,
                            args.timeout_ms, args.model_timeout_seconds, DEFAULT_MAX_COMPLETION_TOKENS)
        database = Database(args.database)
        # CLI attachment must not mark the UI server's active experiments interrupted.
        from commerce_eval.storage.upgrades import upgrade_onboarding

        with database.engine.begin() as connection:
            upgrade_onboarding(connection)
        result = asyncio.run((run_fn or run_business_smoke)(Repository(database), project_id=args.project,
            provider_id=args.provider, provider_version=args.provider_version, model=args.model, allow_paid=True,
            model_timeout_seconds=args.model_timeout_seconds, timeout_ms=args.timeout_ms))
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0 if result["overall_pass"] else 1
    except (SmokeError, ProviderError) as exc:
        print(json.dumps({"error_type": str(exc), "executed": False}))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"error_type": "smoke_interrupted"}))
        return 130
    except Exception:
        print(json.dumps({"error_type": "smoke_setup_failed", "executed": False}))
        return 2
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
