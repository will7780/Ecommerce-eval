"""Evaluator and target plugin registries."""

from __future__ import annotations

from importlib import metadata
from typing import Dict, Iterable

from commerce_eval.contracts import MetricEvaluator


class EvaluatorRegistry:
    def __init__(self, evaluators: Iterable[MetricEvaluator] = ()) -> None:
        self._evaluators: Dict[str, MetricEvaluator] = {}
        for evaluator in evaluators:
            self.register(evaluator)

    def register(self, evaluator: MetricEvaluator) -> None:
        if evaluator.metric_id in self._evaluators:
            raise ValueError(f"evaluator_already_registered:{evaluator.metric_id}")
        self._evaluators[evaluator.metric_id] = evaluator

    def get(self, metric_id: str) -> MetricEvaluator:
        try:
            return self._evaluators[metric_id]
        except KeyError as exc:
            raise KeyError(f"evaluator_not_found:{metric_id}") from exc

    def list(self) -> list[MetricEvaluator]:
        return [self._evaluators[key] for key in sorted(self._evaluators)]

    def load_entry_points(self) -> None:
        points = metadata.entry_points()
        selected = points.select(group="commerce_eval.metric_packs") if hasattr(points, "select") else points.get("commerce_eval.metric_packs", [])
        for point in selected:
            provider = point.load()
            for evaluator in provider():
                self.register(evaluator)

