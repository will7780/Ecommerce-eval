"""Auditable semantic-judge records; hidden reasoning is never accepted."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


JudgeTask = Literal["parameter_intent", "turn_relevance", "conversation_completeness"]


class JudgeVerdictV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: JudgeTask
    decision: str = Field(min_length=1, max_length=40)
    score: float = Field(ge=0.0, le=1.0)
    issue_codes: List[str] = Field(default_factory=list, max_length=32)
    evidence_refs: List[str] = Field(default_factory=list, max_length=64)


class JudgeCalibrationCaseV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=160)
    task: JudgeTask
    payload: Dict[str, Any] = Field(default_factory=dict)
    expected_decision: str = Field(min_length=1, max_length=40)


class JudgeCalibrationReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=0)
    repetitions: int = Field(ge=1)
    valid_response_rate: float = Field(ge=0.0, le=1.0)
    human_alignment_rate: float = Field(ge=0.0, le=1.0)
    repeat_stability_rate: float = Field(ge=0.0, le=1.0)
    eligible_for_release_gate: bool
    thresholds: Dict[str, float]
    failure_codes: List[str] = Field(default_factory=list)


__all__ = [
    "JudgeCalibrationCaseV1",
    "JudgeCalibrationReportV1",
    "JudgeTask",
    "JudgeVerdictV1",
]
