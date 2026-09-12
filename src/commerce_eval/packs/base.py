"""Reusable evaluator primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from commerce_eval.contracts import EvaluationContext, MetricResultV1


@dataclass(frozen=True)
class FunctionalMetricEvaluator:
    metric_id: str
    group: str
    function: Callable[[EvaluationContext], MetricResultV1]
    metric_version: str = "1.0"
    required_evidence: Sequence[str] = ()

    def evaluate(self, context: EvaluationContext) -> MetricResultV1:
        result = self.function(context)
        if result.metric_id != self.metric_id:
            raise ValueError("evaluator_metric_id_mismatch")
        return result

