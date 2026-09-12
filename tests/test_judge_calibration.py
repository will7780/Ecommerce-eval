from __future__ import annotations

import pytest

from commerce_eval.judges import EvalJudge, JudgeCalibrationCaseV1, calibrate_judge


class FixedProvider:
    async def evaluate(self, task, payload):
        decisions = {
            "parameter_intent": "aligned",
            "turn_relevance": "relevant",
            "conversation_completeness": "complete",
        }
        return {"decision": decisions[task], "score": 1.0, "issue_codes": []}


@pytest.mark.asyncio
async def test_structured_judge_calibration_can_become_a_release_gate() -> None:
    judge = EvalJudge(FixedProvider())
    report = await calibrate_judge(
        judge,
        [
            JudgeCalibrationCaseV1(
                case_id="label-1",
                task="parameter_intent",
                payload={"request": "Use the declared threshold."},
                expected_decision="aligned",
            )
        ],
        repetitions=3,
    )
    assert report.eligible_for_release_gate is True
    assert report.repeat_stability_rate == 1.0


@pytest.mark.asyncio
async def test_judge_rejects_hidden_reasoning_fields() -> None:
    class UnsafeProvider:
        async def evaluate(self, task, payload):
            return {
                "decision": "aligned",
                "score": 1.0,
                "issue_codes": [],
                "chain_of_thought": "must not be retained",
            }

    with pytest.raises(ValueError):
        await EvalJudge(UnsafeProvider()).parameter_intent({"request": "x"})
