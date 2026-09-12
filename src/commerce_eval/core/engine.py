"""Evaluation engine over canonical contracts only."""

from __future__ import annotations

from typing import Iterable, Mapping

from commerce_eval.contracts import (
    BusinessEvidenceBundleV1,
    EvaluationContext,
    EvaluationResultV1,
    MetricGateV1,
    MetricEvaluator,
    MetricResultV1,
    MetricStatus,
    ToolContractV1,
    TraceEnvelopeV1,
)

from .gates import evaluate_gates
from .normalizer import TraceNormalizer


class EvaluationEngine:
    def __init__(self, evaluators: Iterable[MetricEvaluator]) -> None:
        self._evaluators = list(evaluators)

    def evaluate(
        self,
        case,
        trace: TraceEnvelopeV1 | Mapping,
        *,
        tool_contracts: Mapping[str, ToolContractV1] | None = None,
        business_evidence: BusinessEvidenceBundleV1 | None = None,
    ) -> EvaluationResultV1:
        normalized = TraceNormalizer.normalize(trace)
        results: dict[str, MetricResultV1] = {}
        for evaluator in self._evaluators:
            context = EvaluationContext(
                case=case,
                trace=normalized,
                tool_contracts=tool_contracts or {},
                prior_results=results,
                business_evidence=business_evidence,
            )
            try:
                result = evaluator.evaluate(context)
            except Exception as exc:
                result = MetricResultV1(
                    metric_id=evaluator.metric_id,
                    metric_version=evaluator.metric_version,
                    group=evaluator.group,
                    status=MetricStatus.ERROR,
                    reason_code="evaluator_error",
                    details={"error_type": type(exc).__name__},
                )
            results[result.metric_id] = result
        gates = list(case.gates)
        if case.business_requirements:
            from commerce_eval.business.verifiers import evaluate_business_requirements

            # Evidence is supplied by the evaluator harness, never Trace metadata.
            results["business_acceptance_pass"] = evaluate_business_requirements(case, business_evidence)
            gates = [gate for gate in gates if gate.metric_id != "business_acceptance_pass"]
            gates.append(MetricGateV1(metric_id="business_acceptance_pass", operator="equals", expected=True))
        declared = {gate.metric_id for gate in gates}
        budget_gates = (
            ("total_tokens_budget_pass", case.budgets.max_total_tokens),
            ("agent_llm_calls_budget_pass", case.budgets.max_agent_llm_calls),
            ("active_runtime_budget_pass", case.budgets.max_active_runtime_ms),
            ("estimated_cost_budget_pass", case.budgets.max_estimated_cost),
        )
        for metric_id, maximum in budget_gates:
            if maximum is not None and metric_id not in declared:
                gates.append(MetricGateV1(metric_id=metric_id, operator="equals", expected=True))
        gate_rows, overall_pass, failures = evaluate_gates(gates, results)
        return EvaluationResultV1(
            trace_id=normalized.trace_id,
            case_id=case.case_id,
            metric_results=list(results.values()),
            gate_results=gate_rows,
            overall_pass=overall_pass,
            gate_failures=failures,
        )

