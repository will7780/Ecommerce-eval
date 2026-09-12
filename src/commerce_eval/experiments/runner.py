"""Dataset experiment execution over AgentTarget, independent of agent framework."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional
from uuid import uuid4

from commerce_eval.contracts import (
    EvalCaseV1,
    ConversationEventV1,
    GateResultV1,
    TraceEventV1,
    ExperimentSpecV1,
    ResourceUsageV1,
    RunStatus,
    TargetResumeRequestV1,
    TargetRunRequestV1,
    TargetRunResponseV1,
    TraceEnvelopeV1,
)
from commerce_eval.core import EvaluationEngine, TraceNormalizer
from commerce_eval.packs import available_evaluators
from commerce_eval.storage import Repository
from commerce_eval.storage.business_evidence import save_collected_business_evidence
from commerce_eval.targets import build_target, failed_target_response, validate_active_target

from commerce_eval.targets.base import candidate_case
from commerce_eval.scenarios.interaction_bindings import canonical_fields, canonical_values, response_for_pending

from .events import ExperimentEventBus


def _sum_resource_usages(rows: list[ResourceUsageV1]) -> ResourceUsageV1:
    if not rows:
        return ResourceUsageV1()
    payloads = [row.model_dump() for row in rows]
    output: dict[str, Any] = {}
    for field in ResourceUsageV1.model_fields:
        values = [payload.get(field) for payload in payloads]
        if all(value is None for value in values):
            output[field] = None
        elif any(value is None for value in values):
            output[field] = None
        elif field in {"currency", "price_card_version", "cost_status"}:
            output[field] = values[0] if len(set(values)) == 1 else None
        else:
            output[field] = sum(values)
    return ResourceUsageV1.model_validate(output)


def _remap_refs(value: Any, ids: Mapping[str, str], key: str = "") -> Any:
    reference_keys = {"event_id", "parent_event_id", "model_call_id", "model_call_event_id", "call_event_id", "tool_call_id", "observation_id", "observation_event_id"}
    if key in {"arguments", "parameter_snapshot", "messages", "content", "rows"}:
        return value
    if isinstance(value, dict):
        return {name: _remap_refs(item, ids, name) for name, item in value.items()}
    if isinstance(value, list):
        return [_remap_refs(item, ids, key) for item in value]
    if isinstance(value, str) and (key in reference_keys or key.endswith(("_refs", "_event_ids"))):
        return ids.get(value, value)
    return value


def _same_event(left, right) -> bool:
    return left.model_dump(exclude={"sequence"}) == right.model_dump(exclude={"sequence"})


def merge_turn_traces(
    traces: list[TraceEnvelopeV1], turn_inputs: Optional[list[Mapping[str, Any]]] = None
) -> TraceEnvelopeV1:
    if not traces:
        raise ValueError("conversation_trace_empty")
    merged = []
    usages = []
    previous_rows = []
    previous_ids: dict[str, str] = {}
    previous_trace = None
    used_ids = set()
    for turn, trace in enumerate(traces, start=1):
        rows = sorted(trace.events, key=lambda item: item.sequence)
        cumulative = trace.metadata.get("event_scope") == "cumulative" or (
            previous_trace is not None and trace.metadata.get("event_scope") != "delta"
            and (trace.trace_id == previous_trace.trace_id or (trace.started_at == previous_trace.started_at and len(rows) > len(previous_rows)))
            and bool(previous_rows) and len(rows) >= len(previous_rows)
            and all(_same_event(a, b) for a, b in zip(previous_rows, rows))
        )
        overlap = 0
        if cumulative:
            while overlap < min(len(previous_rows), len(rows)) and _same_event(previous_rows[overlap], rows[overlap]):
                overlap += 1
            if previous_rows and overlap != len(previous_rows):
                raise ValueError("cumulative_trace_history_changed")
        ids = {row.event_id: previous_ids[row.event_id] for row in rows[:overlap]}
        for index, row in enumerate(rows[overlap:], start=overlap):
            # Keep globally unique operation IDs intact for receipt/approval bindings.
            identifier = row.event_id if row.kind in {"tool.call", "tool_call", "tool.request"} and row.event_id not in used_ids else f"turn-{turn}-{index}"
            ids[row.event_id] = identifier
            used_ids.add(identifier)
        boundary = turn_inputs[turn - 1] if turn_inputs else None
        if boundary:
            merged.append({
                "event_id": f"runner-turn-{turn}", "sequence": len(merged),
                "kind": boundary["kind"], "attributes": {
                    **boundary["attributes"], "conversation_turn": turn, "source": "runner",
                },
            })
        for row in rows[overlap:]:
            if boundary and row.kind == boundary["kind"]:
                if row.kind == "user.message" or row.attributes.get("interaction_id") == boundary["attributes"].get("interaction_id"):
                    ids[row.event_id] = f"runner-turn-{turn}"
        pending_recorded = False
        for row in rows[overlap:]:
            if ids[row.event_id] == f"runner-turn-{turn}":
                continue
            payload = _remap_refs(row.model_dump(mode="json"), {**previous_ids, **ids})
            payload["event_id"] = ids[row.event_id]
            payload["sequence"] = len(merged)
            payload["attributes"] = {**payload["attributes"], "conversation_turn": turn}
            if row.kind in {"tool.call", "tool_call", "tool.request"}:
                payload["attributes"].setdefault("tool_call_id", ids[row.event_id])
            if row.kind in {"interaction.request", "interaction_request"}:
                pending = trace.metadata.get("runner_pending_interaction") or {}
                if pending and row.attributes.get("interaction_id") in {None, pending["interaction_id"]}:
                    payload["attributes"].update({key: value for key, value in pending.items() if value not in (None, [])})
                    pending_recorded = True
            merged.append(payload)
        pending = trace.metadata.get("runner_pending_interaction")
        if pending and not pending_recorded:
            merged.append({
                "event_id": f"runner-pending-{turn}", "sequence": len(merged),
                "kind": "interaction.request", "status": "pending",
                "attributes": {**pending, "source": "runner", "conversation_turn": turn},
            })
        if (cumulative or trace.metadata.get("usage_scope") == "cumulative") and trace.metadata.get("usage_scope") != "delta" and previous_trace is not None:
            # Cumulative accounting replaces the current segment, it is not added.
            if usages:
                usages[-1] = trace.resource_usage
        else:
            usages.append(trace.resource_usage)
        previous_rows, previous_ids, previous_trace = rows, {**previous_ids, **ids}, trace
    payload = traces[-1].model_dump(mode="json")
    payload.update({
        "started_at": traces[0].started_at, "input": traces[0].input,
        "events": merged, "resource_usage": _sum_resource_usages(usages),
        "tags": {**traces[0].tags, **traces[-1].tags},
        "metadata": {**traces[0].metadata, **traces[-1].metadata, "conversation_turn_count": len(traces)},
    })
    return TraceEnvelopeV1.model_validate(payload)


def _response_trace(response: TargetRunResponseV1) -> TraceEnvelopeV1:
    return response.trace.model_copy(update={"metadata": {
        **response.trace.metadata,
        "runner_pending_interaction": response.pending_interaction.model_dump() if response.pending_interaction else None,
    }})


def _pending_error(response: TargetRunResponseV1) -> Optional[str]:
    pending = response.pending_interaction
    waiting = {RunStatus.AWAITING_INPUT, RunStatus.AWAITING_CONFIRMATION}
    if response.status != response.trace.status:
        return "response_trace_status_mismatch"
    if pending is None:
        return "missing_pending_interaction" if response.status in waiting else None
    required_status = RunStatus.AWAITING_INPUT if pending.type == "clarification" else RunStatus.AWAITING_CONFIRMATION
    if response.status != required_status:
        return "pending_status_mismatch"
    if not pending.interaction_id:
        return "pending_id_missing"
    return None


def _case_script(case: EvalCaseV1):
    if case.conversation:
        return [(event, {}) for event in case.conversation]
    script = getattr(case, "scenario_data", {}).get("interaction_script", []) if getattr(case, "scenario_id", None) else []
    if not isinstance(script, list):
        raise ValueError("scenario_interaction_script_invalid")
    result = []
    for index, item in enumerate(script):
        if not isinstance(item, Mapping):
            raise ValueError("scenario_interaction_script_invalid")
        kind = item.get("type")
        if kind == "user_message":
            event = ConversationEventV1(type="user_message", content=item.get("content"))
        elif kind in {"clarification", "confirmation", "artifact_review", "interaction_response"}:
            event = ConversationEventV1(
                type="interaction_response", interaction_id=str(item.get("interaction_id") or f"script-{index}"),
                response=item.get("response", {}),
            )
        else:
            raise ValueError("scenario_interaction_script_type_invalid")
        result.append((event, dict(item)))
    return result


def _script_response_error(event, pending, trace: TraceEnvelopeV1, script=None, field_aliases=None) -> Optional[str]:
    data = event.response
    for key in ("tool_call_id", "parameter_snapshot_hash", "artifact_id", "artifact_version", "artifact_manifest_hash"):
        if key in data and data[key] != getattr(pending, key, None):
            return "confirmation_binding_mismatch"
    script = script or {}
    declared_type = script.get("type")
    if declared_type == "artifact_review":
        if pending.type != "confirmation" or pending.confirmation_kind != "artifact":
            return "interaction_type_mismatch"
    elif declared_type in {"confirmation", "clarification"} and declared_type != pending.type:
        return "interaction_type_mismatch"
    if script.get("confirmation_kind") and script["confirmation_kind"] != pending.confirmation_kind:
        return "confirmation_kind_mismatch"
    expected_type = data.get("interaction_type") or data.get("type")
    if expected_type and expected_type != pending.type:
        return "interaction_type_mismatch"
    if data.get("confirmation_kind") and data["confirmation_kind"] != pending.confirmation_kind:
        return "confirmation_kind_mismatch"
    decision = data.get("decision")
    if pending.type == "confirmation":
        decision = decision if decision is not None else data.get("answer")
        if not isinstance(decision, str) or decision.lower() not in {"approve", "approved", "yes", "continue", "reject", "rejected", "decline", "declined", "deny", "denied", "no", "cancel", "cancelled", "change", "changes", "revise"}:
            return "explicit_confirmation_decision_required"
        if decision.lower() == "revise" and pending.confirmation_kind != "artifact":
            return "interaction_type_mismatch"
        if pending.choices and decision not in pending.choices:
            return "confirmation_choice_mismatch"
    elif decision is not None or isinstance(data.get("approved"), bool):
        return "interaction_type_mismatch"
    fields = list(getattr(pending, "required_fields", []) or [])
    for row in reversed(sorted(trace.events, key=lambda item: item.sequence)):
        if row.kind in {"interaction.request", "interaction_request"} and row.attributes.get("interaction_id") in {None, pending.interaction_id}:
            fields = fields or row.attributes.get("required_fields") or row.attributes.get("missing_fields") or row.attributes.get("fields") or []
            break
    aliases = (field_aliases or {}) if pending.type == "clarification" else {}
    try:
        fields = canonical_fields(fields, aliases)
        declared_fields = canonical_fields(script.get("fields", fields), aliases)
    except ValueError:
        return "interaction_fields_mismatch"
    if "fields" in script and set(declared_fields) != set(fields):
        return "interaction_fields_mismatch"
    supplied = data.get("fields", data.get("values", data))
    if not isinstance(supplied, Mapping):
        return "interaction_fields_mismatch"
    if pending.type == "clarification":
        try:
            supplied = canonical_values(supplied, aliases)
        except ValueError:
            return "interaction_fields_mismatch"
        scalar = data.get("answer", data.get("value"))
        if isinstance(scalar, Mapping):
            supplied = {**supplied, **scalar}
        elif scalar not in (None, "") and len(fields) == 1:
            supplied = {**supplied, fields[0]: scalar}
        if any(field not in supplied for field in fields):
            return "interaction_fields_mismatch"
        if not fields and not data:
            return "interaction_response_empty"
        if pending.choices and scalar not in pending.choices:
            return "clarification_choice_mismatch"
    return None


def _interaction_policy(case):
    policy = case.scenario_data.get("behavior_criteria", {}).get("interaction_policy", {})
    if not policy:
        return {}, []
    if policy.get("version") != "1.1":
        raise ValueError("interaction_policy_version_unavailable")
    aliases = policy.get("field_aliases", {})
    canonical_fields([], aliases)
    optional = policy.get("optional_responses", [])
    if not isinstance(optional, list) or len(optional) > 16:
        raise ValueError("interaction_optional_script_invalid")
    for item in optional:
        if (not isinstance(item, dict) or type(item.get("at_step")) is not int or item["at_step"] < 0
            or type(item.get("max_uses")) is not int or not 1 <= item["max_uses"] <= 4
            or item.get("type") not in {"artifact_review", "confirmation"}
            or not isinstance(item.get("response"), dict)):
            raise ValueError("interaction_optional_script_invalid")
    return aliases, optional


def _protocol_failure(response, traces, turn_inputs, reason: str):
    try:
        trace = merge_turn_traces(traces, turn_inputs)
    except ValueError as exc:
        if str(exc) != "cumulative_trace_history_changed" or len(traces) < 2:
            raise
        trace = merge_turn_traces(traces[:-1], turn_inputs[:-1])
        reason = "cumulative_trace_history_changed"
    now = datetime.now(timezone.utc)
    trace = trace.model_copy(update={
        "status": RunStatus.FAILED, "ended_at": max(now, trace.started_at),
        "output": {**trace.output, "task_completed": False, "error_type": "interaction_protocol_error"},
        "metadata": {**trace.metadata, "protocol_error": reason},
        "events": [*trace.events, TraceEventV1(
            event_id=f"protocol-error-{uuid4().hex}", sequence=len(trace.events),
            kind="error", status="error",
            attributes={"error_type": "interaction_protocol_error", "reason_code": reason, "source": "runner"},
        )],
    })
    return response.model_copy(update={
        "status": RunStatus.FAILED, "trace": trace, "pending_interaction": None,
        "error_type": "interaction_protocol_error",
    })


class ExperimentRunner:
    def __init__(
        self,
        repository: Repository,
        *,
        event_bus: Optional[ExperimentEventBus] = None,
        target_factory: Callable[..., Any] = build_target,
    ) -> None:
        self.repository = repository
        self.event_bus = event_bus or ExperimentEventBus()
        self.target_factory = target_factory

    def prepare_target(self, spec, definition):
        if definition.adapter_type not in {"business_interface", "file_editor"}:
            if spec.provider_id is not None:
                raise ValueError("external_target_model_is_not_platform_managed")
            return self.target_factory(definition)
        if self.target_factory is not build_target:
            return self.target_factory(definition)
        if not spec.allow_paid or not all((spec.provider_id, spec.provider_version, spec.model)):
            raise ValueError("explicit_provider_and_paid_consent_required")
        from commerce_eval.providers import NativeCompatibleClient, ProviderConfigService
        from commerce_eval.targets.business_candidate import BusinessCandidateTarget

        service = ProviderConfigService(self.repository.database)
        from commerce_eval.business.candidates import ModelRequestBudget
        try:
            limits = {
                "timeout_seconds": float(spec.tags.get("model_timeout_seconds", definition.config.get("model_timeout_seconds", 30))),
                "max_completion_tokens": int(spec.tags.get("max_completion_tokens", definition.config.get("max_completion_tokens", 4096))),
                "max_calls": int(spec.tags.get("total_model_request_limit", definition.config.get("max_model_calls", 128))),
            }
            budget = ModelRequestBudget(limits["max_calls"])
        except (TypeError, ValueError):
            raise ValueError("model_limits_invalid") from None
        client = NativeCompatibleClient(
            service, provider_id=spec.provider_id, version=int(spec.provider_version),
            model=spec.model, allow_paid=True, **limits,
        )
        return BusinessCandidateTarget(definition, complete=client.complete, request_budget=budget)

    async def run(self, spec: ExperimentSpecV1) -> dict[str, Any]:
        definition = self.repository.get_target(spec.project_id, spec.target_id, spec.target_version)
        if spec.execution_mode.value not in {"dry_run", "sandbox"}:
            raise ValueError("experiment_execution_mode_not_allowed")
        validate_active_target(definition)
        target = self.prepare_target(spec, definition)
        dataset = self.repository.get_dataset(spec.project_id, spec.dataset_id, spec.dataset_version)
        if definition.adapter_type == "reference_fixture":
            # Reference scripts remain in the explicitly trusted evaluator harness.
            target.bind_fixture_cases(dataset["cases"])
        elif definition.adapter_type == "reference_policy":
            target.bind_environment_cases(dataset["cases"])
        elif definition.adapter_type in {"business_interface", "file_editor"}:
            target.bind_environment_cases(dataset["cases"])
        tool_contracts = (
            self.repository.get_tool_contracts(spec.project_id, spec.tool_contract_set_id, spec.tool_contract_version)
            if spec.tool_contract_version
            else {}
        )
        evaluator_manifest = self.repository.get_evaluator_set(
            spec.project_id,
            spec.evaluator_set_id,
            spec.evaluator_set_version,
        )
        evaluator_ids = set(evaluator_manifest.get("metric_ids") or [])
        available = {item.metric_id: item for item in available_evaluators()}
        missing = sorted(evaluator_ids - set(available))
        if missing:
            raise ValueError(f"evaluator_not_available:{missing[0]}")
        evaluators = [available[metric_id] for metric_id in sorted(evaluator_ids)]
        engine = EvaluationEngine(evaluators)
        all_jobs = [
            (EvalCaseV1.model_validate(case), repetition)
            for case in dataset["cases"]
            for repetition in range(1, spec.repetitions + 1)
        ]
        jobs = [
            (case, repetition)
            for case, repetition in all_jobs
            if not self.repository.run_exists(spec.experiment_id, case.case_id, repetition)
        ]
        completed = len(all_jobs) - len(jobs)
        self.repository.update_experiment(spec.experiment_id, status="running", completed_runs=completed)
        await self.event_bus.publish(spec.experiment_id, "experiment.started", {"total_runs": len(all_jobs), "completed_runs": completed})
        semaphore = asyncio.Semaphore(spec.concurrency)
        completion_lock = asyncio.Lock()

        async def execute(case: EvalCaseV1, repetition: int) -> None:
            nonlocal completed
            async with semaphore:
                if self.repository.experiment_is_cancelled(spec.experiment_id):
                    return
                await self.event_bus.publish(spec.experiment_id, "run.started", {"case_id": case.case_id, "repetition": repetition})
                session_id = f"eval-{spec.experiment_id}-{case.case_id}-{repetition}"
                request_id = f"run-{uuid4().hex}"
                response = None
                collected_trace = None
                business_evidence = None
                try:
                    response = await asyncio.wait_for(
                        self._execute_case(target, spec, case, repetition, session_id=session_id, request_id=request_id, reference_fixture=definition.adapter_type == "reference_fixture"),
                        timeout=spec.timeout_ms / 1000.0,
                    )
                except asyncio.TimeoutError:
                    response = failed_target_response(request_id=request_id, project_id=spec.project_id, target=definition, error_type="target_timeout")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    response = failed_target_response(
                        request_id=request_id, project_id=spec.project_id, target=definition, error_type=f"target_error:{type(exc).__name__}"
                    )
                finally:
                    try:
                        from commerce_eval.targets.business_candidate import BusinessCandidateTarget

                        # Only the registered harness path may mint stored business evidence.
                        if isinstance(target, BusinessCandidateTarget):
                            cause = "target_cancelled" if response is None else response.error_type
                            if cause in {"target_timeout", "target_cancelled"}:
                                response = target.interrupted_response(request_id, session_id, cause) or response
                            if response is None:
                                response = failed_target_response(request_id=request_id, project_id=spec.project_id,
                                    target=definition, error_type="target_cancelled")
                            collected_trace = self._pin_trace(response.trace, spec, case, repetition)
                            try:
                                collected = target.export_business_evidence(session_id)
                            except Exception:
                                collected = None
                                collected_trace = collected_trace.model_copy(update={"metadata": {
                                    **collected_trace.metadata, "business_evidence_error": "collector_unavailable",
                                }})
                            with self.repository.transaction() as bound:
                                collected_trace = bound.save_trace(collected_trace, tool_contracts=tool_contracts)
                                if collected is not None:
                                    business_evidence = save_collected_business_evidence(
                                        bound, collected_trace.trace_id, collected, session_id=session_id,
                                        project_id=spec.project_id, collector_id="builtin-business-environment-v1",
                                    )
                    finally:
                        try:
                            await asyncio.wait_for(target.reset(session_id), timeout=min(5.0, spec.timeout_ms / 1000.0))
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            await self.event_bus.publish(spec.experiment_id, "run.reset_failed", {"case_id": case.case_id, "error_type": type(exc).__name__})
                if self.repository.experiment_is_cancelled(spec.experiment_id):
                    return
                trace = collected_trace or self._pin_trace(response.trace, spec, case, repetition)
                if definition.adapter_type == "reference_fixture":
                    trace = trace.model_copy(update={
                        "metadata": {**trace.metadata, "reference_fixture": True, "reference_actor": False,
                                     "execution_purpose": "conformance_fixture", "candidate_evaluation": False,
                                     "candidate_execution": False, "actor": "reference_fixture"},
                        "tags": {**trace.tags, "actor": "reference_fixture", "execution": "simulated"},
                    })
                elif definition.adapter_type == "reference_policy":
                    trace = trace.model_copy(update={
                        "metadata": {**trace.metadata, "actor": "reference_policy", "reference_fixture": False,
                                     "reference_actor": False, "candidate_evaluation": True, "candidate_execution": True,
                                     "simulation": True, "production_agent": False, "llm_calls": 0,
                                     "execution_purpose": "deterministic_policy_baseline"},
                        "tags": {**trace.tags, "actor": "reference_policy", "execution": "simulated", "model": "none"},
                        "resource_usage": trace.resource_usage.model_copy(update={
                            "agent_llm_calls": 0, "judge_llm_calls": 0, "agent_total_tokens": 0,
                            "cost_status": "no_model_calls",
                        }),
                    })
                trace = self.repository.save_trace(trace, tool_contracts=tool_contracts)
                evaluation = None if definition.adapter_type == "reference_fixture" else engine.evaluate(
                    case, trace, tool_contracts=tool_contracts, business_evidence=business_evidence,
                )
                if evaluation is not None and trace.status in {RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}:
                    reason = str(trace.metadata.get("protocol_error") or "target_run_failed")
                    evaluation.overall_pass = False
                    evaluation.gate_failures.append(f"execution_protocol:{reason}")
                    evaluation.gate_results.append(GateResultV1(
                        metric_id="execution_protocol", passed=False, operator="equals",
                        expected=True, actual=False, reason_code=reason,
                    ))
                if evaluation is not None:
                    self.repository.save_evaluation(evaluation)
                async with completion_lock:
                    completed += 1
                    self.repository.update_experiment(spec.experiment_id, status="running", completed_runs=completed)
                await self.event_bus.publish(
                    spec.experiment_id,
                    "run.completed",
                    {"trace_id": trace.trace_id, "case_id": case.case_id, "repetition": repetition, "overall_pass": evaluation.overall_pass if evaluation is not None else None, "candidate_evaluation": evaluation is not None, "completed_runs": completed},
                )

        execution_tasks = [asyncio.create_task(execute(case, repetition)) for case, repetition in jobs]
        try:
            await asyncio.gather(*execution_tasks)
            if not self.repository.experiment_is_cancelled(spec.experiment_id):
                self.repository.update_experiment(spec.experiment_id, status="completed", completed_runs=completed)
                await self.event_bus.publish(spec.experiment_id, "experiment.completed", {"completed_runs": completed})
        except asyncio.CancelledError:
            # gather can report a queued task's cancellation before active resets finish.
            await asyncio.gather(*execution_tasks, return_exceptions=True)
            self.repository.update_experiment(spec.experiment_id, status="cancelled", completed_runs=completed, error_type="experiment_cancelled")
            await self.event_bus.publish(spec.experiment_id, "experiment.cancelled", {"completed_runs": completed})
            raise
        except Exception as exc:
            self.repository.update_experiment(spec.experiment_id, status="failed", completed_runs=completed, error_type=type(exc).__name__)
            await self.event_bus.publish(spec.experiment_id, "experiment.failed", {"error_type": type(exc).__name__})
            raise
        return self.repository.get_experiment(spec.experiment_id)

    async def _execute_case(
        self, target, spec: ExperimentSpecV1, case: EvalCaseV1, repetition: int, *, session_id: str, request_id: str, reference_fixture: bool = False
    ) -> TargetRunResponseV1:
        deadline = asyncio.get_running_loop().time() + spec.timeout_ms / 1000
        initial_case = candidate_case(case, 0)
        response = await target.start(TargetRunRequestV1(
            request_id=request_id, session_id=session_id, case=initial_case,
            execution_mode=spec.execution_mode, timeout_ms=spec.timeout_ms,
        ))
        traces = [_response_trace(response)]
        turn_inputs = [{"kind": "user.message", "attributes": {"input": initial_case.input, "content": initial_case.input.get("message", "")}}]
        script = [] if reference_fixture else _case_script(case)
        remaining = script[1:] if case.conversation and case.conversation[0].type == "user_message" else script
        reason = _pending_error(response)
        if reason:
            return _protocol_failure(response, traces, turn_inputs, reason)
        resumed_ids = set()
        aliases, optional = _interaction_policy(case) if not reference_fixture else ({}, [])
        optional_uses = [0] * len(optional)
        cursor = 0
        while cursor < len(remaining) or response.pending_interaction is not None:
            if response.status in {RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}:
                return _protocol_failure(response, traces, turn_inputs, "script_after_failed_run")
            required = remaining[cursor] if cursor < len(remaining) else None
            selected_optional = None
            pending = response.pending_interaction
            required_error = None
            if pending is not None:
                if required is None:
                    required_error = "script_exhausted_while_pending"
                elif required[0].type != "interaction_response":
                    required_error = "start_while_pending"
                else:
                    required_error = _script_response_error(required[0], pending, response.trace, required[1], aliases)
                if required_error:
                    matches = []
                    for index, item in enumerate(optional):
                        if item["at_step"] != cursor or optional_uses[index] >= item["max_uses"]:
                            continue
                        candidate = ConversationEventV1(type="interaction_response", interaction_id="optional",
                                                        response=item["response"])
                        if _script_response_error(candidate, pending, response.trace, item, aliases) is None:
                            matches.append((index, candidate, item))
                    if len(matches) > 1:
                        return _protocol_failure(response, traces, turn_inputs, "interaction_script_ambiguous")
                    if not matches:
                        policy = case.scenario_data.get("behavior_criteria", {}).get("interaction_policy")
                        reason = "unsupported_scripted_interaction" if policy else required_error
                        return _protocol_failure(response, traces, turn_inputs, reason)
                    selected_optional, event, scripted_expectation = matches[0]
                else:
                    event, scripted_expectation = required
            elif required is not None:
                event, scripted_expectation = required
            else:
                break
            remaining_ms = int((deadline - asyncio.get_running_loop().time()) * 1000)
            if remaining_ms < 100:
                raise asyncio.TimeoutError
            if event.type == "interaction_response":
                pending = response.pending_interaction
                if pending is None:
                    return _protocol_failure(response, traces, turn_inputs, "response_without_pending")
                reason = _script_response_error(event, pending, response.trace, scripted_expectation, aliases)
                if reason:
                    return _protocol_failure(response, traces, turn_inputs, reason)
                resume_data = dict(event.response)
                if aliases and pending.type == "clarification":
                    try:
                        resume_data = response_for_pending(resume_data, list(pending.required_fields), aliases)
                    except ValueError:
                        return _protocol_failure(response, traces, turn_inputs, "interaction_fields_mismatch")
                resumed_ids.add(pending.interaction_id)
                boundary = {"kind": "interaction.response", "attributes": {
                    **resume_data, "interaction_id": pending.interaction_id,
                    "type": pending.type, "confirmation_kind": pending.confirmation_kind,
                }}
                response = await target.resume(TargetResumeRequestV1(
                    request_id=f"resume-{uuid4().hex}", external_run_id=response.external_run_id,
                    session_id=session_id, interaction_id=pending.interaction_id,
                    response=resume_data, timeout_ms=remaining_ms,
                ))
            else:
                if response.pending_interaction is not None:
                    return _protocol_failure(response, traces, turn_inputs, "start_while_pending")
                next_case = candidate_case(case)
                next_case.input["message"] = event.content or ""
                boundary = {"kind": "user.message", "attributes": {"input": next_case.input, "content": event.content or ""}}
                response = await target.start(TargetRunRequestV1(
                    request_id=f"run-{uuid4().hex}", session_id=session_id, case=next_case,
                    execution_mode=spec.execution_mode, timeout_ms=remaining_ms,
                ))
            if selected_optional is None:
                cursor += 1
            else:
                optional_uses[selected_optional] += 1
            traces.append(_response_trace(response))
            turn_inputs.append(boundary)
            reason = _pending_error(response)
            if response.pending_interaction and response.pending_interaction.interaction_id in resumed_ids:
                reason = "interaction_id_reused"
            if reason:
                return _protocol_failure(response, traces, turn_inputs, reason)
        if response.pending_interaction is not None:
            return _protocol_failure(response, traces, turn_inputs, "script_exhausted_while_pending")
        try:
            trace = merge_turn_traces(traces, turn_inputs)
        except ValueError as exc:
            if str(exc) != "cumulative_trace_history_changed":
                raise
            return _protocol_failure(response, traces, turn_inputs, str(exc))
        return response.model_copy(update={"trace": trace})

    @staticmethod
    def _pin_trace(trace: TraceEnvelopeV1, spec: ExperimentSpecV1, case: EvalCaseV1, repetition: int) -> TraceEnvelopeV1:
        payload = trace.model_dump(mode="json")
        payload.update(
            {
                "project_id": spec.project_id,
                "experiment_id": spec.experiment_id,
                "case_id": case.case_id,
                "repetition": repetition,
                "dataset_version": spec.dataset_version,
                "tool_contract_version": spec.tool_contract_version,
                "tool_contract_set_id": spec.tool_contract_set_id,
                "evaluator_set_version": spec.evaluator_set_version,
                "target_id": spec.target_id,
                "target_version": spec.target_version,
            }
        )
        if spec.model_config_version:
            payload["metadata"] = {**payload.get("metadata", {}), "model_config_version": spec.model_config_version}
        if spec.provider_id:
            payload["metadata"] = {**payload.get("metadata", {}), "provider_id": spec.provider_id,
                                   "provider_version": spec.provider_version, "model": spec.model}
        return TraceNormalizer.normalize(payload)


class ExperimentManager:
    def __init__(self, runner: ExperimentRunner) -> None:
        self.runner = runner
        self.tasks: dict[str, asyncio.Task] = {}

    def start(self, spec: ExperimentSpecV1) -> asyncio.Task:
        running = self.tasks.get(spec.experiment_id)
        if running and not running.done():
            raise ValueError("experiment_already_running")
        task = asyncio.create_task(self.runner.run(spec))
        self.tasks[spec.experiment_id] = task
        return task

    def is_running(self, experiment_id: str) -> bool:
        task = self.tasks.get(experiment_id)
        return bool(task and not task.done())

    def cancel(self, experiment_id: str) -> bool:
        task = self.tasks.get(experiment_id)
        if not task or task.done():
            return False
        task.cancel()
        return True

