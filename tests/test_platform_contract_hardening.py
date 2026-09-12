from __future__ import annotations

import pytest
from pydantic import ValidationError

from commerce_eval.contracts import EvalCaseV1, ToolContractV1, TraceEnvelopeV1
from commerce_eval.core import EvaluationEngine, contains_secret, redact_recursive
from commerce_eval.packs import all_evaluators


def _metrics(case: EvalCaseV1, trace: TraceEnvelopeV1, tools=None):
    result = EvaluationEngine(all_evaluators()).evaluate(case, trace, tool_contracts=tools or {})
    return result, {row.metric_id: row for row in result.metric_results}


def _trace(*events, output=None) -> TraceEnvelopeV1:
    return TraceEnvelopeV1(
        trace_id="contract-hardening",
        project_id="project",
        target_id="target",
        target_version="1",
        output=output or {"task_completed": True},
        events=list(events),
    )


def _tool(event_id: str, sequence: int, tool_id: str, arguments: dict, **attributes):
    return {
        "event_id": event_id,
        "sequence": sequence,
        "kind": "tool.call",
        "name": tool_id,
        "attributes": {"tool_id": tool_id, "arguments": arguments, **attributes},
    }


def test_schema_metric_uses_contract_instead_of_agent_self_report() -> None:
    contract = ToolContractV1(
        tool_id="pricing.audit_margin",
        version="1",
        title="Audit",
        input_schema={
            "type": "object",
            "properties": {"threshold_percent": {"type": "number", "minimum": -100, "maximum": 100}},
            "required": ["threshold_percent"],
            "additionalProperties": False,
        },
    )
    trace = _trace(_tool("t1", 0, contract.tool_id, {"threshold_percent": 150}, schema_pass=True))
    _result, metrics = _metrics(EvalCaseV1(case_id="schema", name="Schema"), trace, {contract.tool_id: contract})
    metric = metrics["tool_argument_schema_pass_rate"]
    assert metric.value == 0.0
    assert metric.status.value == "fail"
    assert metric.details["reported_schema_disagreements"] == ["t1"]
    assert metric.details["invalid"][0]["validators"] == ["maximum"]


def test_missing_tool_contract_fails_schema_metric() -> None:
    trace = _trace(_tool("t1", 0, "catalog.generate_listing", {"market": "DE"}, schema_pass=True))
    _result, metrics = _metrics(EvalCaseV1(case_id="missing", name="Missing"), trace)
    metric = metrics["tool_argument_schema_pass_rate"]
    assert metric.value == 0.0
    assert metric.details["missing_contracts"] == ["catalog.generate_listing"]


def test_partial_order_and_output_assertions_are_independent_gates() -> None:
    case = EvalCaseV1(
        case_id="ordering",
        name="Ordering",
        partial_order=[["catalog.generate_listing", "catalog.upload_listing"], ["catalog.generate_listing", "pricing.audit_margin"]],
        outcome_assertions={"receipt": {"simulated": True}},
        gates=[
            {"metric_id": "partial_order_pass", "operator": "equals", "expected": 1.0},
            {"metric_id": "outcome_assertion_pass_rate", "operator": "equals", "expected": 1.0},
        ],
    )
    trace = _trace(
        _tool("audit", 0, "pricing.audit_margin", {}),
        _tool("generate", 1, "catalog.generate_listing", {}),
        _tool("upload", 2, "catalog.upload_listing", {}),
        output={"task_completed": True, "receipt": {"simulated": False}},
    )
    result, metrics = _metrics(case, trace)
    assert metrics["partial_order_pass"].value == 0.5
    assert metrics["outcome_assertion_pass_rate"].value == 0.0
    assert result.overall_pass is False
    assert len(result.gate_failures) == 2


def test_confirmation_required_tool_must_have_prior_approval() -> None:
    contract = ToolContractV1(
        tool_id="catalog.upload_listing",
        version="1",
        title="Upload",
        confirmation_required=True,
    )
    case = EvalCaseV1(case_id="confirm", name="Confirm")
    without_approval = _trace(_tool("upload", 0, contract.tool_id, {}))
    _result, metrics = _metrics(case, without_approval, {contract.tool_id: contract})
    assert metrics["tool_confirmation_compliance"].value == 0.0

    with_approval = _trace(
        {
            "event_id": "approved",
            "sequence": 0,
            "kind": "interaction.response",
            "attributes": {"decision": "approve"},
        },
        _tool("upload", 1, contract.tool_id, {}),
    )
    _result, metrics = _metrics(case, with_approval, {contract.tool_id: contract})
    assert metrics["tool_confirmation_compliance"].value == 1.0


def test_duplicate_tool_call_requires_same_evidence_epoch() -> None:
    case = EvalCaseV1(case_id="duplicate", name="Duplicate")
    same_epoch = _trace(
        _tool("first", 0, "catalog.generate_listing", {"market": "DE"}),
        _tool("second", 1, "catalog.generate_listing", {"market": "DE"}),
    )
    _result, metrics = _metrics(case, same_epoch)
    assert metrics["duplicate_tool_call_rate"].value == 0.5

    new_evidence = _trace(
        _tool("first", 0, "catalog.generate_listing", {"market": "DE"}),
        {"event_id": "obs", "sequence": 1, "kind": "observation", "attributes": {"status": "retryable"}},
        _tool("second", 2, "catalog.generate_listing", {"market": "DE"}),
    )
    _result, metrics = _metrics(case, new_evidence)
    assert metrics["duplicate_tool_call_rate"].value == 0.0


def test_redacted_placeholders_are_safe_but_original_secret_is_detected() -> None:
    secret_like_value = "sk-" + ("1" * 16)
    cleaned = redact_recursive({"api_key": secret_like_value, "nested": {"token": "secret"}})
    assert contains_secret(cleaned) is False
    assert contains_secret({"api_key": secret_like_value}) is True


def test_partial_order_rejects_single_item_constraints() -> None:
    with pytest.raises(ValidationError, match="partial_order_constraint_invalid"):
        EvalCaseV1(case_id="bad-order", name="Bad", partial_order=[["catalog.generate_listing"]])
