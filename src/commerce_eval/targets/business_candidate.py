"""Native-model candidate target with evaluator-side evidence kept off the wire."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import inspect
import json
import math
import time
from types import SimpleNamespace
from typing import Any

from commerce_eval.business.candidates import BusinessCandidateSurface, ModelRequestBudget
from commerce_eval.business.environment import BusinessScenarioEnvironment, _safe
from commerce_eval.contracts.models import (
    EvalCaseV1, PendingInteractionV1, ResourceUsageV1, TargetRunResponseV1, TraceEnvelopeV1, TraceEventV1,
)
from commerce_eval.core.redaction import redact_recursive
from commerce_eval.providers.errors import ProviderError
from commerce_eval.scenarios.compiler import project_candidate_input
from .base import validate_active_target


_TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens", "cache_hit_tokens", "cache_miss_tokens")
_SAFE_PROVIDER_CODES = frozenset({
    "provider_address_forbidden", "provider_https_required", "provider_url_invalid",
    "provider_disconnected", "provider_timeout", "provider_authentication_denied",
    "provider_permission_denied", "provider_redirect_refused", "provider_rate_limited",
    "provider_backend_error", "provider_request_rejected", "provider_invalid_response",
    "provider_response_too_large", "provider_request_too_large", "provider_messages_invalid",
    "provider_tools_invalid", "provider_credential_missing", "provider_call_budget_exhausted",
    "provider_disabled", "provider_endpoint_not_confirmed", "provider_version_required",
    "provider_version_not_found", "provider_model_invalid", "provider_model_required",
    "provider_call_budget_invalid", "provider_request_budget_invalid", "paid_call_not_authorized",
    "credential_reference_invalid", "central_env_link_forbidden", "central_env_invalid",
    "central_env_too_large", "central_env_unavailable",
})


def _model_failure_diagnostics(error, elapsed_ms):
    details = {"latency_ms": elapsed_ms}
    if isinstance(error, ProviderError):
        code = error.code
        details["provider_error_type"] = code if type(code) is str and code in _SAFE_PROVIDER_CODES else "provider_error"
        details["failure_category"] = "provider_failure"
        latency = error.latency_ms
        if type(latency) in (int, float) and math.isfinite(latency) and latency >= 0:
            details["latency_ms"] = float(latency)
    return details


@dataclass
class _CandidateSession:
    environment: Any
    case: EvalCaseV1
    external_run_id: str
    started_at: datetime
    wall_start: float
    messages: list[dict] = field(default_factory=list)
    events: list[TraceEventV1] = field(default_factory=list)
    pending: PendingInteractionV1 | None = None
    pending_call_id: str | None = None
    rounds: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    active_ms: float = 0
    llm_ms: float = 0
    tool_ms: float = 0
    usage_rows: list[dict] = field(default_factory=list)
    returned_event_count: int = 0
    returned_calls: int = 0
    returned_tools: int = 0
    output: dict = field(default_factory=dict)
    busy: bool = False
    pending_wait_start: float | None = None
    wait_ms: float = 0


class BusinessCandidateTarget:
    def __init__(self, definition, *, complete=None, model_client=None, environment_factory=None,
                 request_budget=None, clock=time.monotonic):
        validate_active_target(definition)
        self.definition = definition
        surface = definition.adapter_type if definition.adapter_type in {"business_interface", "file_editor"} else definition.config.get("surface", "business_interface")
        self.surface = BusinessCandidateSurface(surface)
        self.complete = complete or (model_client.complete if model_client is not None else None)
        self.environment_factory = environment_factory or BusinessScenarioEnvironment
        self.request_budget = request_budget or ModelRequestBudget()
        self.clock = clock
        self.max_rounds = min(24, max(1, int(definition.config.get("max_rounds", 24))))
        self._cases: dict[str, EvalCaseV1] = {}
        self._sessions: dict[str, _CandidateSession] = {}

    def bind_environment_cases(self, cases):
        result = {}
        for raw in cases:
            case = EvalCaseV1.model_validate(raw).model_copy(deep=True)
            if case.case_id in result or not isinstance(case.scenario_data.get("environment"), dict):
                raise ValueError("business_case_binding_invalid")
            result[case.case_id] = case
        self._cases = result

    async def capabilities(self):
        return {"protocol_version": "1.2", "supported_protocol_versions": ["1.2"],
                "operations": ["start", "resume", "reset"], "safe_for_eval": True,
                "surface": self.surface.name, "actor": self.definition.config.get("model_source", "real_model"),
                "simulation": True, "business_evidence": True}

    def _event(self, state, kind, attrs, *, status="ok"):
        event = TraceEventV1(contract_version="1.2", event_id=f"candidate-event-{len(state.events)}",
                             sequence=len(state.events), kind=kind, status=status, attributes=_safe(attrs))
        state.events.append(event)
        return event

    async def start(self, request):
        old = self._sessions.get(request.session_id)
        if old and (old.pending or old.busy):
            return self._error(request, old, "start_while_pending")
        case = self._cases.get(request.case.case_id)
        if case is None or case.version != request.case.version:
            return self._error(request, old, "business_case_not_bound")
        # Only this trusted harness receives the full case. The candidate sees its public projection.
        public = project_candidate_input(request.case)
        now = self.clock()
        if old and old.case.case_id == case.case_id:
            state = old
            state.external_run_id = request.request_id
            state.rounds = 0
        else:
            previous = old.environment.collect_business_evidence(request.session_id) if old else None
            if old:
                old.environment.close()
            environment = self.environment_factory(case)
            state = _CandidateSession(environment, case, request.request_id, datetime.now(timezone.utc), now)
            environment.bind_clock(lambda: state.started_at + timedelta(seconds=self.clock()-state.wall_start))
            self._sessions[request.session_id] = state
            system = self.surface.system_message()
            if case.scenario_data["environment"].get("report_contract_version") == "1.1":
                from commerce_eval.business.reporting import report_system_instruction
                system += " " + report_system_instruction()
            state.messages.append({"role": "system", "content": system})
            if previous and previous.company_id != str(case.scenario_data["environment"].get("company_id", "harbor")):
                environment.record_prior_context(request.session_id, previous)
        state.busy = True
        try:
            workspace = state.environment.open_session(request.session_id)
            state.environment.record_user_message(request.session_id, public.message)
            state.messages.append({"role": "user", "content": json.dumps(_safe({"message": public.message,
                "assets": public.assets, "workspace": workspace}), ensure_ascii=True)})
            self._event(state, "user.message", {"message": public.message})
            return await self._advance(request, state, now)
        finally:
            state.busy = False

    async def resume(self, request):
        state = self._sessions.get(request.session_id)
        if not state or state.pending is None:
            return self._error(request, state, "response_without_pending")
        if state.busy:
            return self._error(request, state, "interaction_in_progress")
        if state.external_run_id != request.external_run_id or state.pending.interaction_id != request.interaction_id:
            return self._error(request, state, "pending_interaction_mismatch")
        state.busy = True
        start = self.clock()
        try:
            try:
                result = state.environment.respond(request.session_id, request.interaction_id, deepcopy(request.response))
            except ValueError:
                return self._error(request, state, "interaction_response_invalid")
            if state.pending_wait_start is not None:
                wait_start = state.pending_wait_start
                state.wait_ms += max(0, (start - wait_start) * 1000)
                state.environment.record_wait_interval(request.session_id,
                    state.started_at + timedelta(seconds=wait_start-state.wall_start),
                    state.started_at + timedelta(seconds=start-state.wall_start))
                state.pending_wait_start = None
            self._event(state, "interaction.response", {"interaction_id": request.interaction_id,
                        "type": state.pending.type, "confirmation_kind": state.pending.confirmation_kind,
                        "response": request.response, "result": result})
            state.messages.append({"role": "tool", "tool_call_id": state.pending_call_id,
                                   "content": json.dumps(_safe(result), ensure_ascii=True)})
            state.pending = None
            state.pending_call_id = None
            return await self._advance(request, state, start)
        finally:
            state.busy = False

    def _control_call(self, call):
        if call["name"] in {"ask_user", "confirm_publication", "business_review_artifact"}:
            return True
        return call["name"] == "backend_request" and call["arguments"].get("path") == "/artifact/review"

    async def _advance(self, request, state, segment_start):
        deadline = segment_start + request.timeout_ms / 1000
        if self.complete is None:
            return self._error(request, state, "model_client_missing")
        while state.rounds < self.max_rounds:
            remaining = deadline - self.clock()
            if remaining <= 0:
                return self._terminal_error(request, state, "candidate_timeout", segment_start)
            try:
                self.request_budget.acquire()
            except ValueError:
                return self._terminal_error(request, state, "model_request_budget_exhausted", segment_start)
            state.rounds += 1
            state.llm_calls += 1
            model_call_id = f"model-call-{state.llm_calls}"
            messages = _safe(deepcopy(state.messages))
            self._event(state, "model.input", {"model_call_id": model_call_id, "round_index": state.rounds - 1,
                "messages": messages, "tools": deepcopy(self.surface.schemas), "source": "actual_request",
                "captured": True, "truncated": False, "redacted": messages != state.messages})
            began = self.clock()
            try:
                result = self.complete(messages=messages, tools=deepcopy(self.surface.schemas))
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(result, timeout=remaining)
                if not isinstance(result, dict):
                    raise ValueError("model_response_invalid")
            except asyncio.CancelledError:
                latency = max(0, (self.clock() - began) * 1000)
                state.llm_ms += latency
                state.usage_rows.append({key: None for key in _TOKEN_FIELDS})
                state.environment.record_model_usage(request.session_id, state.usage_rows[-1], latency)
                state.environment.record_model_failure(request.session_id, model_call_id,
                    error_type="model_call_cancelled", latency_ms=latency)
                self._event(state, "model.call", {"model_call_id": model_call_id,
                    "error_type": "model_call_cancelled", "usage": state.usage_rows[-1], "latency_ms": latency}, status="error")
                raise
            except Exception as exc:
                diagnostics = _model_failure_diagnostics(exc, max(0, (self.clock()-began)*1000))
                latency = diagnostics["latency_ms"]
                state.llm_ms += latency
                state.usage_rows.append({key: None for key in _TOKEN_FIELDS})
                state.environment.record_model_usage(request.session_id, state.usage_rows[-1], latency)
                state.environment.record_model_failure(request.session_id, model_call_id,
                    error_type="model_request_failed", latency_ms=latency,
                    provider_error_type=diagnostics.get("provider_error_type"))
                self._event(state, "model.call", {"model_call_id": model_call_id,
                    "error_type": "model_request_failed", "usage": state.usage_rows[-1], **diagnostics}, status="error")
                return self._terminal_error(request, state, "model_request_failed", segment_start, diagnostics=diagnostics)
            elapsed = max(0, (self.clock() - began) * 1000)
            latency = result.get("latency_ms")
            state.llm_ms += float(latency) if isinstance(latency, (float, int)) and latency >= 0 else elapsed
            usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
            state.usage_rows.append({key: usage.get(key) if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool)
                                    and usage[key] >= 0 else None for key in _TOKEN_FIELDS})
            state.environment.record_model_usage(request.session_id, state.usage_rows[-1], elapsed)
            raw_calls = result.get("tool_calls") or []
            if not isinstance(raw_calls, list) or len(raw_calls) > 32:
                return self._terminal_error(request, state, "model_tool_calls_invalid", segment_start)
            calls = []
            for raw in raw_calls:
                if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not isinstance(raw.get("arguments"), dict):
                    return self._terminal_error(request, state, "model_tool_calls_invalid", segment_start)
                calls.append({"id": str(raw.get("id") or f"call-{state.llm_calls}-{len(calls)}"),
                              "name": raw["name"], "arguments": deepcopy(raw["arguments"])})
            if len({call["id"] for call in calls}) != len(calls):
                return self._terminal_error(request, state, "model_tool_call_ids_duplicate", segment_start)
            content = result.get("content") if isinstance(result.get("content"), str) else ""
            self._event(state, "model.call", {"model_call_id": model_call_id, "usage": usage, "latency_ms": elapsed,
                                              "tool_calls": calls, "content": content})
            if not calls:
                state.active_ms += max(0, (self.clock() - segment_start) * 1000)
                state.output = {"summary": _safe(content), "execution": "simulated", "live_side_effect": False}
                state.environment.finish(request.session_id, content, self._usage(state))
                self._event(state, "final_answer", {"text": content})
                return self._response(request, state, "completed")
            state.messages.append({"role": "assistant", "content": _safe(content) or None,
                "tool_calls": [{"id": call["id"], "type": "function", "function": {"name": call["name"],
                                "arguments": json.dumps(_safe(call["arguments"]), ensure_ascii=True)}} for call in calls]})
            mixed = len(calls) > 1 and any(self._control_call(call) for call in calls)
            for call in calls:
                state.tool_calls += 1
                state.environment.record_decision(request.session_id, action=call["name"], related_event_ids=[model_call_id])
                self._event(state, "tool.call", {"tool_id": call["name"], "tool_call_id": call["id"], "arguments": call["arguments"]})
                began = self.clock()
                receipt = {"status": "blocked", "error_type": "interaction_tool_must_be_single"} if mixed else self.surface.execute(
                    state.environment, request.session_id, call)
                state.tool_ms += max(0, (self.clock() - began) * 1000)
                self._event(state, "observation", {"tool_call_id": call["id"], "tool_id": call["name"], "result": receipt},
                            status="pending" if receipt.get("status") == "pending" else "ok" if receipt.get("status") == "ok" else "error")
                if receipt.get("status") == "pending":
                    pending = receipt["pending_interaction"]
                    state.pending = PendingInteractionV1(interaction_id=pending["interaction_id"], type=pending["type"],
                        prompt=pending["prompt"], confirmation_kind=pending.get("confirmation_kind"), required_fields=pending["fields"],
                        tool_call_id=call["id"], artifact_id=pending.get("artifact_id"), artifact_version=pending.get("version"),
                        artifact_manifest_hash=pending.get("manifest_hash"))
                    state.pending_call_id = call["id"]
                    state.pending_wait_start = self.clock()
                    self._event(state, "interaction.request", pending, status="pending")
                    state.active_ms += max(0, (self.clock() - segment_start) * 1000)
                    return self._response(request, state, "awaiting_input" if state.pending.type == "clarification" else "awaiting_confirmation")
                state.messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(_safe(receipt), ensure_ascii=True)})
        return self._terminal_error(request, state, "candidate_round_limit", segment_start)

    def _usage(self, state):
        from decimal import Decimal
        now = self.clock()
        wall = round(max(0, (now - state.wall_start) * 1000), 6)
        wait = state.wait_ms + (max(0, (now-state.pending_wait_start)*1000) if state.pending_wait_start is not None else 0)
        wait = round(min(wall, wait), 6)
        active = float(Decimal(str(wall))-Decimal(str(wait)))
        values = {"agent_llm_calls": state.llm_calls, "judge_llm_calls": 0, "tool_calls": state.tool_calls,
                  "agent_llm_latency_ms": state.llm_ms, "judge_llm_latency_ms": 0,
                  "tool_latency_ms": state.tool_ms, "active_runtime_ms": active,
                  "wall_runtime_ms": wall, "user_wait_ms": wait,
                  "estimated_cost": None, "cost_status": "price_card_missing",
                  "judge_prompt_tokens": 0, "judge_completion_tokens": 0, "judge_total_tokens": 0}
        for key in _TOKEN_FIELDS:
            present = [row[key] for row in state.usage_rows]
            amount = sum(present) if present and len(present) == state.llm_calls and all(item is not None for item in present) else None
            values[key] = values["agent_" + key] = amount
        return ResourceUsageV1.model_validate(values)

    def _response(self, request, state, status, error_type=None):
        usage = self._usage(state) if state else ResourceUsageV1()
        now = state.started_at + timedelta(milliseconds=usage.wall_runtime_ms) if state else datetime.now(timezone.utc)
        events = deepcopy(state.events[state.returned_event_count:]) if state else []
        for index, event in enumerate(events):
            event.sequence = index
        if state:
            state.returned_event_count = len(state.events)
        actor = str(self.definition.config.get("model_source", "real_model"))
        trace = TraceEnvelopeV1(contract_version="1.2", trace_id=request.request_id,
            project_id=str(self.definition.config.get("project_id", "business-sandbox")),
            target_id=self.definition.target_id, target_version=self.definition.version,
            case_id=state.case.case_id if state else None, started_at=state.started_at if state else now,
            ended_at=now, status=status, input={"message": request.case.input.get("message", "")} if hasattr(request, "case") else {},
            output=deepcopy(state.output) if state else {"error_type": error_type}, events=events,
            resource_usage=usage,
            metadata={"actor": actor, "surface": self.surface.name, "simulation": True,
                      "candidate_execution": True, "candidate_evaluation": True, "event_scope": "delta",
                      "usage_scope": "cumulative", "reference_fixture": False,
                      "provider_id": self.definition.config.get("provider_id"), "model": self.definition.config.get("model")},
            tags={"actor": actor, "surface": self.surface.name, "execution": "simulated"})
        return TargetRunResponseV1(contract_version="1.2", external_run_id=state.external_run_id if state else request.request_id,
            status=status, trace=trace, pending_interaction=state.pending if state and status.startswith("awaiting_") else None,
            error_type=error_type)

    def _error(self, request, state, code, *, diagnostics=None):
        if state:
            self._event(state, "error", {"error_type": code, **(diagnostics or {})}, status="error")
        return self._response(request, state, "failed", code)

    def _terminal_error(self, request, state, code, segment_start, *, diagnostics=None):
        diagnostics = diagnostics or {}
        state.active_ms += max(0, (self.clock() - segment_start) * 1000)
        summary = "Candidate could not complete because its model provider failed." if diagnostics.get("provider_error_type") else "Candidate did not finish this run."
        state.output = {"error_type": code, "summary": summary, "task_completed": False, **diagnostics}
        state.environment.finish(request.session_id, json.dumps({"outcome": "incomplete", "simulated": True,
                                 "error_type": code, **diagnostics}), self._usage(state))
        return self._error(request, state, code, diagnostics=diagnostics)

    def export_business_evidence(self, session_id):
        state = self._sessions.get(session_id)
        if state is None:
            raise ValueError("business_session_not_found")
        bundle = state.environment.collect_business_evidence(session_id)
        usage = self._usage(state)
        ended = state.started_at + timedelta(milliseconds=usage.wall_runtime_ms)
        final_state = deepcopy(bundle.final_state)
        final_state["journal"].update(started_at=state.started_at.isoformat(), ended_at=ended.isoformat())
        return bundle.model_copy(update={"project_id": str(self.definition.config.get("project_id", "business-sandbox")),
                                         "resource_usage": usage, "started_at": state.started_at, "ended_at": ended,
                                         "final_state": final_state})

    def interrupted_response(self, request_id, session_id, error_type):
        """Keep completed work and the interrupted call when the outer case deadline fires."""
        state = self._sessions.get(session_id)
        if state is None:
            return None
        state.output = {"error_type": error_type, "task_completed": False,
                        "summary": "Candidate did not finish this run."}
        self._event(state, "error", {"error_type": error_type}, status="error")
        state.environment.finish(session_id, json.dumps({"outcome": "incomplete", "simulated": True,
            "error_type": error_type}), self._usage(state))
        state.returned_event_count = 0
        request = SimpleNamespace(request_id=request_id, case=state.case)
        return self._response(request, state, "cancelled" if error_type == "target_cancelled" else "failed", error_type)

    async def reset(self, session_id):
        state = self._sessions.pop(session_id, None)
        if state:
            state.environment.close()
