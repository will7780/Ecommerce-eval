"""Small evidence helpers shared by deterministic metric packs."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from commerce_eval.contracts import TraceEnvelopeV1, TraceEventV1


TOOL_KINDS = {"tool.call", "tool_call", "tool.request"}
MODEL_KINDS = {"model.call", "model_call"}
INTERACTION_REQUEST_KINDS = {"interaction.request", "interaction_request"}


def events(trace: TraceEnvelopeV1, kinds: Iterable[str]) -> list[TraceEventV1]:
    accepted = set(kinds)
    return [event for event in trace.events if event.kind in accepted]


def tool_events(trace: TraceEnvelopeV1) -> list[TraceEventV1]:
    return events(trace, TOOL_KINDS)


def tool_id(event: TraceEventV1) -> str:
    return str(event.attributes.get("tool_id") or event.name or "")


def arguments(event: TraceEventV1) -> dict[str, Any]:
    raw = event.attributes.get("arguments")
    return dict(raw) if isinstance(raw, Mapping) else {}


def argument_signature(event: TraceEventV1) -> str:
    return json.dumps(arguments(event), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def evidence_refs(rows: Iterable[TraceEventV1]) -> list[str]:
    return [row.event_id for row in rows]


def is_subsequence(required: list[str], actual: list[str]) -> bool:
    if not required:
        return True
    cursor = 0
    for item in actual:
        if item == required[cursor]:
            cursor += 1
            if cursor == len(required):
                return True
    return False


def scenario_case(case) -> bool:
    return bool(getattr(case, "scenario_id", None))


def ordered_events(trace: TraceEnvelopeV1) -> list[TraceEventV1]:
    return sorted(trace.events, key=lambda row: row.sequence)


def snapshot_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return dict(value) if isinstance(value, Mapping) else {}


def capability_tools(case, identifier: str) -> set[str]:
    bindings = [_mapping(raw) for raw in getattr(case, "capability_bindings", [])]
    capabilities = {
        binding.get("capability_id", binding.get("capability")) for binding in bindings
        if identifier in {binding.get("capability_id"), binding.get("capability"), binding.get("tool_id"), binding.get("actual_tool_id")}
        or identifier in binding.get("alternative_tools", [])
    }
    if not capabilities:
        return {identifier}
    actual = set()
    for binding in bindings:
        if binding.get("capability_id", binding.get("capability")) in capabilities:
            actual.add(str(binding.get("tool_id") or binding.get("actual_tool_id") or ""))
            actual.update(str(item) for item in binding.get("alternative_tools", []) if isinstance(item, str))
    return actual - {""}


def matches_tool(case, event: TraceEventV1, identifier: str) -> bool:
    return tool_id(event) in capability_tools(case, identifier)


def canonical_arguments(case, event: TraceEventV1) -> dict[str, Any]:
    actual = arguments(event)
    result = dict(actual)
    for raw in getattr(case, "capability_bindings", []):
        binding = _mapping(raw)
        if tool_id(event) != (binding.get("tool_id") or binding.get("actual_tool_id")):
            continue
        if "argument_mapping" in binding:
            mapping = binding["argument_mapping"]
            result = {key: value for key, value in actual.items() if key not in {str(path).strip("/").split("/")[0] for path in mapping.values()}}
            for neutral, path in mapping.items():
                value = get_path(actual, str(path))
                scale = binding.get("unit_scale", {}).get(neutral, 1)
                if value is not None:
                    result[neutral] = value / scale if isinstance(value, (float, int)) and not isinstance(value, bool) and scale != 1 else value
            if not mapping:
                result = dict(actual)
                for key, scale in binding.get("unit_scale", {}).items():
                    if key in result and isinstance(result[key], (float, int)) and not isinstance(result[key], bool):
                        result[key] /= scale
            continue
        fields = binding.get("field_mapping", binding.get("parameter_mapping", binding.get("field_mappings", {})))
        units = binding.get("unit_mapping", binding.get("unit_mappings", {}))
        if isinstance(fields, Mapping):
            for neutral, mapped in fields.items():
                spec = _mapping(mapped)
                field = mapped if isinstance(mapped, str) else spec.get("field", spec.get("target_field"))
                value = get_path(actual, str(field)) if field else None
                unit = _mapping(units.get(neutral)) if isinstance(units, Mapping) else {}
                scale = spec.get("scale", unit.get("scale", 1))
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    value = value * scale + unit.get("offset", 0)
                result[neutral] = value
    return result


def get_path(value: Any, path: str) -> Any:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")] if path.startswith("/") else path.split(".")
    for part in parts:
        if isinstance(value, Mapping):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def subset_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and all(key in actual and subset_matches(actual[key], value) for key, value in expected.items())
    return actual == expected


def linked_events(trace: TraceEnvelopeV1, call: TraceEventV1) -> list[TraceEventV1]:
    ids = {call.event_id, call.attributes.get("tool_call_id"), call.attributes.get("call_id")} - {None, ""}
    return [
        row for row in ordered_events(trace)
        if row.sequence > call.sequence and (
            row.parent_event_id in ids or row.attributes.get("tool_call_id") in ids
            or row.attributes.get("call_id") in ids or bool(ids.intersection(row.evidence_refs))
        )
    ]


def receipt_data(row, case=None):
    result = row.attributes.get("result")
    data = dict(result) if isinstance(result, Mapping) else dict(row.attributes)
    if case is not None:
        for raw in getattr(case, "capability_bindings", []):
            binding = _mapping(raw)
            if tool_id(row) == binding.get("tool_id"):
                for neutral, path in binding.get("evidence_mapping", {}).items():
                    data[neutral] = get_path(result, path)
    return data


def operation_state(trace: TraceEnvelopeV1, call: TraceEventV1, case=None) -> dict[str, bool]:
    linked = linked_events(trace, call)
    execution_kinds = {"tool.execute", "tool.execution", "tool.result", "execution.receipt"}
    blocked_errors = {
        "scope_denied", "write_not_authorized", "interaction_pending", "invalid_arguments",
        "unsupported_capability", "call_budget_exceeded", "dependency_missing", "preflight_unavailable",
        "artifact_missing", "approved_revision_required", "artifact_invalid", "risk_approval_required",
        "publication_already_completed", "execution_binding_mismatch", "full_check_required", "review_sample_required",
    }
    observations = [row for row in linked if row.kind in {"observation", "tool.observation", "tool.result", "execution.receipt"}]
    receipts = [(row, receipt_data(row, case)) for row in observations]
    receipts = [(row, data) for row, data in receipts if data.get("receipt_id") or data.get("execution_id") or row.kind in {"tool.result", "execution.receipt"}]
    execution = [row for row in linked if row.kind in execution_kinds and row.status.value not in {"blocked", "skipped", "pending"}]
    completed_receipts = [
        (row, data) for row, data in receipts
        if row.status.value not in {"blocked", "skipped", "pending"} and data.get("status") not in {"pending", "blocked"}
        and data.get("error_type") not in blocked_errors
    ]
    executed = bool(execution or completed_receipts)
    success = bool(completed_receipts) and completed_receipts[-1][0].status.value == "ok" and completed_receipts[-1][1].get(
        "observation_status", completed_receipts[-1][1].get("status", "success")
    ) in {"success", "completed", "dry_run", "ok"}
    blocked = call.status.value == "blocked" or call.attributes.get("guard_allowed") is False or any(
        row.status.value == "blocked" or (row.kind in {"guard", "guard.check"} and row.attributes.get("allowed") is False)
        for row in linked
    ) or any(data.get("status") == "blocked" or data.get("error_type") in blocked_errors for _, data in receipts)
    return {"attempted": True, "executed": executed, "succeeded": success, "blocked": blocked and not executed}


def protocol_checks(trace: TraceEnvelopeV1) -> list[dict[str, Any]]:
    pending = None
    used = set()
    checks = []
    for row in ordered_events(trace):
        attrs = row.attributes
        if row.kind in INTERACTION_REQUEST_KINDS:
            identifier = attrs.get("interaction_id")
            valid = pending is None and bool(identifier) and identifier not in used and attrs.get("type") in {"clarification", "confirmation"}
            checks.append({"passed": valid, "refs": [row.event_id], "reason": "request"})
            if valid:
                pending = row
                used.add(identifier)
        elif row.kind in {"interaction.response", "interaction_response"}:
            valid = pending is not None and attrs.get("interaction_id") == pending.attributes.get("interaction_id")
            if valid and attrs.get("type") not in (None, pending.attributes.get("type"), "artifact_review" if pending.attributes.get("confirmation_kind") == "artifact" else None):
                valid = False
            if valid and pending.attributes.get("type") == "confirmation":
                decision = attrs.get("decision", attrs.get("answer"))
                valid = isinstance(decision, str) and decision.lower() in {
                    "approve", "approved", "yes", "continue", "reject", "rejected", "decline", "declined", "deny", "denied", "no", "cancel", "cancelled", "change", "changes",
                }
            if valid and pending.attributes.get("type") == "clarification":
                fields = pending.attributes.get("required_fields") or pending.attributes.get("missing_fields") or pending.attributes.get("fields") or []
                supplied = attrs.get("fields", attrs.get("values", attrs))
                scalar = attrs.get("answer", attrs.get("value"))
                if isinstance(scalar, Mapping):
                    supplied = {**supplied, **scalar}
                elif len(fields) == 1 and scalar not in (None, ""):
                    supplied = {**supplied, fields[0]: scalar}
                valid = isinstance(supplied, Mapping) and all(field in supplied for field in fields) and "decision" not in attrs
            checks.append({"passed": valid, "refs": [row.event_id], "reason": "response"})
            if valid:
                pending = None
        elif row.kind in {"user.message", "tool.execute", "tool.execution", "execution.receipt"} and pending is not None:
            checks.append({"passed": False, "refs": [pending.event_id, row.event_id], "reason": "action_while_pending"})
        elif row.kind == "error" and attrs.get("error_type") == "interaction_protocol_error":
            checks.append({"passed": False, "refs": [row.event_id], "reason": attrs.get("reason_code", "protocol_error")})
    if pending is not None:
        checks.append({"passed": False, "refs": [pending.event_id], "reason": "unresolved_pending"})
    return checks


def confirmation_checks(context) -> list[dict[str, Any]]:
    rows = ordered_events(context.trace)
    calls = tool_events(context.trace)
    required = [
        call for call in calls if context.tool_contracts.get(tool_id(call))
        and context.tool_contracts[tool_id(call)].confirmation_required
        and operation_state(context.trace, call, context.case)["executed"]
    ]
    consumed = set()
    checks = []
    for call in sorted(required, key=lambda item: item.sequence):
        attrs = call.attributes
        call_ids = {call.event_id, attrs.get("tool_call_id"), attrs.get("call_id")} - {None, ""}
        execution_rows = [row for row in linked_events(context.trace, call) if row.kind in {"tool.execute", "tool.execution", "execution.receipt", "tool.result"}]
        execution_sequence = min((row.sequence for row in execution_rows), default=call.sequence)
        digest = snapshot_hash(arguments(call))
        approved = False
        refs = [call.event_id]
        consuming = [
            row for row in linked_events(context.trace, call)
            if row.kind in {"tool.execute", "tool.execution", "execution.receipt", "tool.result", "artifact.consume"}
        ]
        changed_arguments = any(
            (isinstance(row.attributes.get("arguments"), Mapping)
             and snapshot_hash(row.attributes["arguments"]) != digest)
            or row.attributes.get("parameter_snapshot_hash") not in (None, digest, "sha256:" + digest)
            for row in consuming
        )
        artifact_fields = ("artifact_id", "artifact_version", "artifact_manifest_hash")
        changed_artifact = any(
            row.attributes.get(key) is not None and row.attributes[key] != attrs.get(key)
            for row in consuming for key in artifact_fields
        )
        if changed_arguments or changed_artifact:
            checks.append({"passed": False, "refs": [call.event_id, *evidence_refs(consuming)], "reason": "execution_binding_changed"})
            continue
        for request in rows:
            data = request.attributes
            interaction_id = data.get("interaction_id")
            if request.kind not in INTERACTION_REQUEST_KINDS or data.get("type") != "confirmation":
                continue
            if not interaction_id or interaction_id in consumed or data.get("tool_call_id") not in call_ids:
                continue
            if request.sequence >= execution_sequence:
                continue
            if str(data.get("parameter_snapshot_hash") or "").removeprefix("sha256:") != digest:
                continue
            artifact_fields = ("artifact_id", "artifact_version", "artifact_manifest_hash")
            artifact_required = bool(getattr(context.case, "artifact_requirements", {})) or any(attrs.get(key) for key in artifact_fields)
            if artifact_required and any(not attrs.get(key) or data.get(key) != attrs.get(key) for key in artifact_fields):
                continue
            responses = [
                row for row in rows if row.kind in {"interaction.response", "interaction_response"}
                and request.sequence < row.sequence < execution_sequence
                and row.attributes.get("interaction_id") == interaction_id
            ]
            if len(responses) != 1:
                continue
            response = responses[0]
            decision = response.attributes.get("decision", response.attributes.get("answer"))
            if not isinstance(decision, str) or decision.lower() not in {"approve", "approved", "yes", "continue"}:
                continue
            if any(response.attributes.get(key) not in (None, data.get(key)) for key in (*artifact_fields, "parameter_snapshot_hash", "tool_call_id")):
                continue
            approved = True
            consumed.add(interaction_id)
            refs.extend([request.event_id, response.event_id])
            break
        checks.append({"passed": approved, "refs": refs, "reason": "operation_bound_confirmation"})
    return checks


def assertion_check(context, assertion: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate declarative behavior against event values, never a reported pass."""
    check = dict(assertion)
    kind = str(check.get("type") or check.get("kind") or "fact")
    aliases = {"require": "tool_called", "forbid": "tool_not_called", "order": "sequence"}
    kind = aliases.get(kind, kind)
    if kind == "sequence" and "capabilities" in check:
        check["tools"] = check["capabilities"]
    if "any_of" in check:
        choices = [assertion_check(context, item) for item in check["any_of"]]
        return {"passed": any(item["passed"] for item in choices), "refs": [ref for item in choices for ref in item["refs"]], "reason": kind}
    rows = tool_events(context.trace)
    identifier = check.get("tool_id") or check.get("capability_id") or check.get("capability")
    if identifier:
        rows = [row for row in rows if matches_tool(context.case, row, str(identifier))]
    turn = check.get("turn", check.get("after_turn"))
    if turn is not None:
        rows = [row for row in rows if int(row.attributes.get("conversation_turn", row.attributes.get("turn", 0))) >= int(turn)]
    all_rows = list(rows)
    required_args = check.get("arguments", check.get("parameters"))
    if isinstance(required_args, Mapping):
        rows = [row for row in rows if subset_matches(canonical_arguments(context.case, row), required_args)]
    state = check.get("state", "succeeded" if kind in {"intent", "intent_completed", "tool_succeeded"} else "attempted")
    if kind in {"tool_executed", "no_execution"}:
        state = "executed"
    elif kind == "tool_blocked":
        state = "blocked"
    if state not in {"attempted", "executed", "succeeded", "blocked"}:
        return {"passed": False, "refs": [], "reason": "unsupported_operation_state"}
    state_rows = [row for row in rows if operation_state(context.trace, row, context.case)[state]]
    refs = evidence_refs(state_rows)
    if kind in {"tool_called", "tool_attempted", "tool_executed", "tool_succeeded", "tool_blocked", "intent", "intent_completed"}:
        passed = bool(state_rows)
    elif kind in {"tool_not_called", "forbidden_tool", "no_execution"}:
        passed = not state_rows
    elif kind == "all_arguments":
        passed = bool(all_rows) and len(rows) == len(all_rows)
        refs = evidence_refs(all_rows)
    elif kind in {"max_count", "min_count", "total_calls"}:
        count = len(tool_events(context.trace)) if kind == "total_calls" else len(rows)
        passed = count >= check["count"] if kind == "min_count" else count <= check.get("count", check.get("maximum", 0))
    elif kind == "no_successful_row_retry":
        completed = set()
        passed = True
        refs = evidence_refs(rows)
        for row in sorted(rows, key=lambda item: item.sequence):
            requested = canonical_arguments(context.case, row).get("row_ids", [])
            if completed.intersection(requested):
                passed = False
            for observation in linked_events(context.trace, row):
                if observation.kind in {"observation", "tool.observation", "tool.result"}:
                    completed.update(receipt_data(observation, context.case).get("successful_row_ids", []))
    elif kind in {"tool_count", "event_count"}:
        if kind == "event_count":
            state_rows = events(context.trace, [check.get("event_kind", "")])
            refs = evidence_refs(state_rows)
        count = len(state_rows)
        passed = count == check["count"] if "count" in check else check.get("min", 0) <= count <= check.get("max", float("inf"))
    elif kind in {"fact", "fact_retained", "argument_equals", "parameter", "intent_alignment"}:
        field = check.get("field", check.get("key"))
        expected = check.get("expected", check.get("value", check.get("equals")))
        if field:
            matched = [row for row in rows if get_path(canonical_arguments(context.case, row), str(field)) == expected]
            passed = bool(matched)
            if check.get("all", True):
                passed = passed and len(matched) == len(rows)
            refs = evidence_refs(rows)
        elif isinstance(required_args, Mapping):
            passed = bool(rows)
            refs = evidence_refs(rows)
        else:
            passed = False
    elif kind in {"protocol", "interaction_protocol"}:
        checks = protocol_checks(context.trace)
        passed = bool(checks) and all(item["passed"] for item in checks)
        refs = [ref for item in checks for ref in item["refs"]]
    elif kind in {"confirmation", "operation_confirmation"}:
        checks = confirmation_checks(context)
        passed = bool(checks) and all(item["passed"] for item in checks)
        refs = [ref for item in checks for ref in item["refs"]]
    elif kind in {"event", "event_required", "event_absent"}:
        matched = [
            row for row in ordered_events(context.trace)
            if row.kind == check.get("event_kind") and subset_matches(row.attributes, check.get("attributes", {}))
        ]
        passed = not matched if kind == "event_absent" else bool(matched)
        refs = evidence_refs(matched)
    elif kind == "sequence":
        chain = check.get("tools", check.get("sequence", []))
        cursor = 0
        for row in tool_events(context.trace):
            if cursor < len(chain) and matches_tool(context.case, row, chain[cursor]):
                cursor += 1
        passed = bool(chain) and cursor == len(chain)
    else:
        return {"passed": False, "refs": [], "reason": "unsupported_behavior_assertion", "type": kind}
    return {"passed": passed, "refs": refs, "reason": kind}

