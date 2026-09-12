"""Case-declared release gates; no opaque weighted score."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from commerce_eval.contracts import GateResultV1, MetricGateV1, MetricResultV1, MetricStatus


def _compare(actual: Any, gate: MetricGateV1) -> tuple[bool, str]:
    if gate.operator == "equals":
        return actual == gate.expected, "equals"
    if actual is None or isinstance(actual, bool) or isinstance(gate.expected, bool):
        return False, "numeric_value_required"
    try:
        left = float(actual)
        right = float(gate.expected)
    except (TypeError, ValueError):
        return False, "numeric_value_required"
    if gate.operator == "min":
        return left >= right, "minimum"
    return left <= right, "maximum"


def evaluate_gates(
    gates: Iterable[MetricGateV1],
    results: Mapping[str, MetricResultV1],
) -> tuple[list[GateResultV1], bool, list[str]]:
    rows: list[GateResultV1] = []
    failures: list[str] = []
    for gate in gates:
        metric = results.get(gate.metric_id)
        if metric is None:
            passed, reason, actual = False, "metric_missing", None
        elif metric.status == MetricStatus.NA:
            passed, reason, actual = gate.allow_na, "na_allowed" if gate.allow_na else "na_not_allowed", None
        elif metric.status == MetricStatus.ERROR:
            passed, reason, actual = False, "metric_error", metric.value
        else:
            passed, reason = _compare(metric.value, gate)
            actual = metric.value
        rows.append(
            GateResultV1(
                metric_id=gate.metric_id,
                passed=passed,
                operator=gate.operator,
                expected=gate.expected,
                actual=actual,
                reason_code=reason,
            )
        )
        if not passed:
            failures.append(f"{gate.metric_id}:{reason}")
    return rows, not failures, failures

