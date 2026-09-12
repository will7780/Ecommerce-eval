"""Third-party AgentTarget discovery through the public entry-point group."""

from __future__ import annotations

from importlib import metadata
from typing import Any, Callable

from commerce_eval.contracts import TargetDefinitionV1


class TargetRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., Any]] = {}

    def register(self, adapter_type: str, factory: Callable[..., Any]) -> None:
        key = str(adapter_type).strip()
        if not key:
            raise ValueError("target_adapter_type_required")
        if key in self._factories:
            raise ValueError(f"target_adapter_already_registered:{key}")
        self._factories[key] = factory

    def load_entry_points(self) -> None:
        points = metadata.entry_points()
        selected = points.select(group="commerce_eval.targets") if hasattr(points, "select") else points.get("commerce_eval.targets", [])
        for point in selected:
            self.register(point.name, point.load())

    def build(self, definition: TargetDefinitionV1, **kwargs: Any):
        try:
            factory = self._factories[definition.adapter_type]
        except KeyError as exc:
            raise ValueError("target_adapter_unsupported") from exc
        return factory(definition, **kwargs)


__all__ = ["TargetRegistry"]
