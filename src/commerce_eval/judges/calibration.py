"""Small human-labelled calibration suite for optional semantic judges."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from .eval_judge import EvalJudge
from .models import JudgeCalibrationCaseV1, JudgeCalibrationReportV1


async def calibrate_judge(
    judge: EvalJudge,
    cases: Iterable[JudgeCalibrationCaseV1],
    *,
    repetitions: int = 3,
    min_valid_response_rate: float = 1.0,
    min_human_alignment_rate: float = 0.8,
    min_repeat_stability_rate: float = 0.9,
) -> JudgeCalibrationReportV1:
    if repetitions < 1:
        raise ValueError("judge_calibration_repetitions_invalid")
    rows = list(cases)
    total = len(rows) * repetitions
    valid = 0
    aligned = 0
    stable_scores: list[float] = []
    for case in rows:
        decisions: list[str] = []
        for _ in range(repetitions):
            try:
                verdict = await judge.evaluate(case.task, case.payload)
            except Exception:
                continue
            valid += 1
            decisions.append(verdict.decision)
            aligned += int(verdict.decision == case.expected_decision)
        if decisions:
            stable_scores.append(Counter(decisions).most_common(1)[0][1] / repetitions)
        else:
            stable_scores.append(0.0)
    valid_rate = valid / total if total else 0.0
    alignment_rate = aligned / valid if valid else 0.0
    stability_rate = sum(stable_scores) / len(stable_scores) if stable_scores else 0.0
    failures = []
    if valid_rate < min_valid_response_rate:
        failures.append("valid_response_rate_below_threshold")
    if alignment_rate < min_human_alignment_rate:
        failures.append("human_alignment_rate_below_threshold")
    if stability_rate < min_repeat_stability_rate:
        failures.append("repeat_stability_rate_below_threshold")
    return JudgeCalibrationReportV1(
        case_count=len(rows),
        repetitions=repetitions,
        valid_response_rate=valid_rate,
        human_alignment_rate=alignment_rate,
        repeat_stability_rate=stability_rate,
        eligible_for_release_gate=not failures,
        thresholds={
            "valid_response_rate": min_valid_response_rate,
            "human_alignment_rate": min_human_alignment_rate,
            "repeat_stability_rate": min_repeat_stability_rate,
        },
        failure_codes=failures,
    )


__all__ = ["calibrate_judge"]
