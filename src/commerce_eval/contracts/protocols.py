"""Extension protocols kept independent from storage and web frameworks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .models import (
    BusinessEvidenceBundleV1,
    EvalCaseV1,
    MetricResultV1,
    TargetResumeRequestV1,
    TargetRunRequestV1,
    TargetRunResponseV1,
    ToolContractV1,
    TraceEnvelopeV1,
)


@dataclass(frozen=True)
class EvaluationContext:
    case: EvalCaseV1
    trace: TraceEnvelopeV1
    tool_contracts: Mapping[str, ToolContractV1]
    prior_results: Mapping[str, MetricResultV1]
    business_evidence: BusinessEvidenceBundleV1 | None = None


class MetricEvaluator(Protocol):
    metric_id: str
    metric_version: str
    group: str
    required_evidence: Sequence[str]

    def evaluate(self, context: EvaluationContext) -> MetricResultV1:
        ...


class AgentTarget(Protocol):
    async def capabilities(self) -> Mapping[str, Any]:
        ...

    async def start(self, request: TargetRunRequestV1) -> TargetRunResponseV1:
        ...

    async def resume(self, request: TargetResumeRequestV1) -> TargetRunResponseV1:
        ...

    async def reset(self, session_id: str) -> None:
        ...


class JudgeProvider(Protocol):
    async def evaluate(self, task: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        ...
