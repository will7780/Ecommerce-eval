from __future__ import annotations

from pathlib import Path

from commerce_eval.contracts import EvalCaseV1, TraceEnvelopeV1
from commerce_eval.core import EvaluationEngine
from commerce_eval.packs import all_evaluators


ROOT = Path(__file__).resolve().parents[1]


def _cases() -> dict[str, EvalCaseV1]:
    return {
        case.case_id: case
        for case in (
            EvalCaseV1.model_validate_json(line)
            for line in (ROOT / "examples" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def _traces() -> dict[str, TraceEnvelopeV1]:
    return {
        trace.trace_id: trace
        for trace in (
            TraceEnvelopeV1.model_validate_json(line)
            for line in (ROOT / "examples" / "traces.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def _metrics(result):
    return {row.metric_id: row for row in result.metric_results}


def test_success_trace_passes_declared_gates() -> None:
    result = EvaluationEngine(all_evaluators()).evaluate(
        _cases()["listing-launch"],
        _traces()["trace-listing-launch"],
    )
    metrics = _metrics(result)
    assert result.overall_pass is True
    assert metrics["expected_tool_recall"].value == 1.0
    assert metrics["required_sequence_pass"].value == 1.0
    assert metrics["step_efficiency_score"].value == 1.0
    assert metrics["estimated_cost"].value is None
    assert metrics["estimated_cost"].na_reason == "price_card_or_usage_unavailable"


def test_failure_requires_real_model_replan_and_changed_arguments() -> None:
    result = EvaluationEngine(all_evaluators()).evaluate(
        _cases()["failure-replan"],
        _traces()["trace-failure-replan"],
    )
    metrics = _metrics(result)
    assert metrics["failure_replan_pass_rate"].value == 1.0
    assert result.overall_pass is True


def test_duplicate_is_scoped_to_evidence_epoch() -> None:
    trace = _traces()["trace-failure-replan"].model_copy(deep=True)
    trace.events[3].attributes["evidence_epoch"] = 1
    trace.events[3].attributes["arguments"] = trace.events[1].attributes["arguments"]
    result = EvaluationEngine(all_evaluators()).evaluate(_cases()["failure-replan"], trace)
    assert _metrics(result)["duplicate_tool_call_rate"].value == 0.5


def test_non_conversation_metrics_are_na_not_zero() -> None:
    result = EvaluationEngine(all_evaluators()).evaluate(
        _cases()["listing-launch"],
        _traces()["trace-listing-launch"],
    )
    metric = _metrics(result)["dialogue_fact_retention_pass_rate"]
    assert metric.status.value == "na"
    assert metric.na_reason == "not_a_conversation_eval"


def test_gate_does_not_accept_na_unless_declared() -> None:
    payload = _cases()["listing-launch"].model_dump(mode="json")
    payload["gates"].append(
        {"metric_id": "failure_replan_pass_rate", "operator": "min", "expected": 1.0, "allow_na": False}
    )
    case = EvalCaseV1.model_validate(payload)
    result = EvaluationEngine(all_evaluators()).evaluate(case, _traces()["trace-listing-launch"])
    assert result.overall_pass is False
    assert "failure_replan_pass_rate:na_not_allowed" in result.gate_failures



def test_declared_resource_budget_is_an_automatic_gate() -> None:
    case = EvalCaseV1(
        case_id="budget-case",
        name="Budget",
        budgets={"max_total_tokens": 50},
    )
    trace = _traces()["trace-listing-launch"].model_copy(deep=True)
    trace.resource_usage.total_tokens = None
    trace.resource_usage.agent_llm_calls = 1
    trace.resource_usage.agent_total_tokens = 51
    result = EvaluationEngine(all_evaluators()).evaluate(case, trace)
    assert result.overall_pass is False
    assert "total_tokens_budget_pass:equals" in result.gate_failures
