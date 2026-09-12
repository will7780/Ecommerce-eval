"""Provider-neutral structured semantic judge."""

from __future__ import annotations

from typing import Any, Mapping

from commerce_eval.contracts import JudgeProvider
from commerce_eval.core.redaction import redact_recursive

from .models import JudgeTask, JudgeVerdictV1


_ALLOWED_DECISIONS = {
    "parameter_intent": {"aligned", "misaligned", "uncertain"},
    "turn_relevance": {"relevant", "irrelevant", "uncertain"},
    "conversation_completeness": {"complete", "incomplete", "uncertain"},
}


class EvalJudge:
    def __init__(self, provider: JudgeProvider) -> None:
        self.provider = provider

    async def evaluate(
        self,
        task: JudgeTask,
        payload: Mapping[str, Any],
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> JudgeVerdictV1:
        safe_payload = redact_recursive(dict(payload))
        raw = await self.provider.evaluate(task, safe_payload)
        if not isinstance(raw, Mapping):
            raise ValueError("judge_response_not_object")
        verdict = JudgeVerdictV1.model_validate(
            {
                **dict(raw),
                "task": task,
                "evidence_refs": list(raw.get("evidence_refs") or evidence_refs),
            }
        )
        if verdict.decision not in _ALLOWED_DECISIONS[task]:
            raise ValueError("judge_decision_invalid")
        return verdict

    async def parameter_intent(self, payload: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()) -> JudgeVerdictV1:
        return await self.evaluate("parameter_intent", payload, evidence_refs=evidence_refs)

    async def turn_relevance(self, payload: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()) -> JudgeVerdictV1:
        return await self.evaluate("turn_relevance", payload, evidence_refs=evidence_refs)

    async def conversation_completeness(self, payload: Mapping[str, Any], *, evidence_refs: tuple[str, ...] = ()) -> JudgeVerdictV1:
        return await self.evaluate("conversation_completeness", payload, evidence_refs=evidence_refs)


__all__ = ["EvalJudge"]
