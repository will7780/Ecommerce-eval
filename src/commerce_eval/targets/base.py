"""Target construction and shared failure mapping."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from importlib import import_module
import json
from typing import Any
from uuid import uuid4

from commerce_eval.contracts import (
    EvalCaseV1,
    RunStatus,
    TargetDefinitionV1,
    TargetRunResponseV1,
    TraceEnvelopeV1,
    TraceEventV1,
)


_PRIVATE_INPUT_KEYS = {
    "business_requirements", "required_evidence", "verifier_id", "verifier_version",
    "conversation", "conversations", "interaction_script", "script", "future_messages",
    "expected_tools", "allowed_tools", "forbidden_tools", "required_sequence", "partial_order",
    "parameter_expectations", "outcome_assertions", "fact_assertions", "behavior_assertions",
    "artifact_requirements", "gates", "intents", "reference_min_steps", "reference", "references",
    "expected", "expected_answer", "correct_answer", "answer_key", "ground_truth", "scenario_data",
    "simulator", "simulator_script", "environment", "private", "hidden",
    "answer", "answers", "labels", "defect_labels", "evaluation", "capability_bindings", "context",
    "dialogue", "future_turns", "future_replies", "future_dialogue", "scripts", "behavior_criteria",
}


def _normalized_key(value: str) -> str:
    return "".join(char for char in str(value).lower() if char.isalnum())


def _public_value(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        if isinstance(parsed, (dict, list)):
            return json.dumps(_public_value(parsed), ensure_ascii=True)
    if isinstance(value, dict):
        return {
            key: _public_value(item) for key, item in value.items()
            if _normalized_key(key) not in {_normalized_key(item) for item in _PRIVATE_INPUT_KEYS}
            and not _normalized_key(key).startswith(("expected", "hidden", "evaluator", "reference", "future", "script"))
        }
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    return deepcopy(value)


def candidate_case(case: EvalCaseV1, turn: int = 0) -> EvalCaseV1:
    """Build a fresh legacy-compatible case; never copy evaluator-owned fields."""
    if not isinstance(turn, int) or isinstance(turn, bool) or turn < 0:
        raise ValueError("candidate_turn_invalid")
    public = _public_value(case.input)
    if case.conversation and turn < len(case.conversation) and case.conversation[turn].type == "user_message":
        public["message"] = case.conversation[turn].content or ""
    for key in ("assets", "public_assets", "allowed_assets"):
        if key in public:
            public[key] = [
                item for item in public[key] if isinstance(item, dict) and item.get("permitted") is True
            ] if isinstance(public[key], list) else []
    projected_case = EvalCaseV1(case_id=case.case_id, version=case.version, name="Candidate task", input=public)
    # The projector is delivered independently; consume only its public view.
    try:
        module = import_module("commerce_eval.scenarios.compiler")
    except ModuleNotFoundError as exc:
        if exc.name not in {"commerce_eval.scenarios", "commerce_eval.scenarios.compiler"}:
            raise
    else:
        projector = getattr(module, "project_candidate_input", None)
        if projector is not None:
            projected = projector(projected_case, turn)
            data = projected.model_dump(mode="json") if hasattr(projected, "model_dump") else projected
            if isinstance(data, dict):
                if isinstance(data.get("input"), dict):
                    public = _public_value(data["input"])
                elif isinstance(data.get("message"), str):
                    public["message"] = data["message"]
                for key in ("assets", "public_assets", "allowed_assets", "tools"):
                    if key in data:
                        public[key] = _public_value(data[key])
                        if key in {"assets", "public_assets", "allowed_assets"} and isinstance(public[key], list):
                            public[key] = [{**item, "permitted": True} for item in public[key] if isinstance(item, dict)]
    return EvalCaseV1(case_id=case.case_id, version=case.version, name="Candidate task", input=public)


def candidate_request_payload(request) -> dict[str, Any]:
    """Defense in depth for direct adapter callers as well as the Runner."""
    payload = request.model_dump(mode="json")
    safe = candidate_case(request.case)
    payload["case"] = safe.model_dump(mode="json", include={"contract_version", "case_id", "version", "name", "input"})
    payload.pop("candidate_input", None)
    return payload


def target_protocol_version(definition: TargetDefinitionV1) -> str:
    version = str(definition.config.get("protocol_version") or "1.0")
    if version not in {"1.0", "1.1", "1.2"}:
        raise ValueError("target_protocol_version_unsupported")
    return version


def failed_target_response(
    *,
    request_id: str,
    project_id: str,
    target: TargetDefinitionV1,
    error_type: str,
) -> TargetRunResponseV1:
    now = datetime.now(timezone.utc)
    trace = TraceEnvelopeV1(
        trace_id=f"trace_{uuid4().hex}",
        project_id=project_id,
        target_id=target.target_id,
        target_version=target.version,
        started_at=now,
        ended_at=now,
        status=RunStatus.FAILED,
        output={"task_completed": False, "error_type": error_type},
        metadata={"request_id": request_id},
        events=[
            TraceEventV1(
                event_id="target-error",
                sequence=0,
                kind="error",
                name="Target invocation failed",
                status="error",
                attributes={"error_type": error_type},
            )
        ],
    )
    return TargetRunResponseV1(
        external_run_id=request_id,
        status=RunStatus.FAILED,
        trace=trace,
        error_type=error_type,
    )


def validate_active_target(definition: TargetDefinitionV1) -> None:
    if not definition.safe_for_eval:
        raise ValueError("target_not_safe_for_eval")
    forbidden = {"live", "local_write", "external_write"}
    mode = str(definition.config.get("execution_mode") or "dry_run")
    if mode in forbidden:
        raise ValueError("live_target_not_allowed")


def build_target(definition: TargetDefinitionV1, *, client: Any = None):
    validate_active_target(definition)
    if definition.adapter_type == "reference_policy":
        from .reference_policy import ReferencePolicyTarget

        return ReferencePolicyTarget(definition)
    if definition.adapter_type == "reference_fixture":
        from commerce_eval.demo_runtime import ReferenceFixtureTarget

        return ReferenceFixtureTarget(definition)
    if definition.adapter_type == "python":
        from .python_target import PythonAgentTarget

        return PythonAgentTarget(definition)
    if definition.adapter_type == "http":
        from .http_target import HTTPAgentTarget

        return HTTPAgentTarget(definition, client=client)
    from .registry import TargetRegistry

    registry = TargetRegistry()
    registry.load_entry_points()
    return registry.build(definition, client=client)

