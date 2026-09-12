"""Governance Pack diagnostics over normalized memory and retrieval events."""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from commerce_eval.contracts import EvaluationContext, MetricResultV1, MetricStatus
from commerce_eval.core.redaction import contains_secret

from .base import FunctionalMetricEvaluator


def _result(
    metric_id: str,
    value: Any,
    *,
    passed: bool = True,
    na_reason: Optional[str] = None,
    refs: Iterable[str] = (),
) -> MetricResultV1:
    return MetricResultV1(
        metric_id=metric_id,
        group="governance",
        status=MetricStatus.NA if na_reason else (MetricStatus.PASS if passed else MetricStatus.FAIL),
        value=None if na_reason else value,
        reason_code="not_applicable" if na_reason else "computed",
        evidence_refs=list(refs),
        na_reason=na_reason,
    )


def _memory_rows(context: EvaluationContext):
    return [event for event in context.trace.events if event.kind.startswith("memory.") or event.kind.startswith("memory_")]


def memory_candidate_created(context: EvaluationContext) -> MetricResultV1:
    rows = [row for row in _memory_rows(context) if row.kind in {"memory.candidate", "memory_candidate"}]
    value = any(row.attributes.get("created") is not False for row in rows)
    return _result("memory_candidate_created", value, refs=[row.event_id for row in rows])


def memory_review_triggered(context: EvaluationContext) -> MetricResultV1:
    rows = [row for row in _memory_rows(context) if row.kind in {"memory.review", "memory_review"}]
    value = any(row.attributes.get("triggered") is not False for row in rows)
    return _result("memory_review_triggered", value, refs=[row.event_id for row in rows])


def no_secret_leak_in_memory(context: EvaluationContext) -> MetricResultV1:
    rows = _memory_rows(context)
    serialized = json.dumps([row.attributes for row in rows], ensure_ascii=False)
    value = not contains_secret(serialized)
    return _result("no_secret_leak_in_memory", value, passed=value, refs=[row.event_id for row in rows])


def _citation_rows(context: EvaluationContext):
    return [event for event in context.trace.events if event.kind in {"citation.verify", "citation_verify"}]


def citation_groundedness_method(context: EvaluationContext) -> MetricResultV1:
    rows = _citation_rows(context)
    methods = [str(row.attributes.get("method")) for row in rows if row.attributes.get("method")]
    if not methods:
        return _result("citation_groundedness_method", None, na_reason="citation_verification_unavailable")
    return _result("citation_groundedness_method", methods[-1], refs=[row.event_id for row in rows])


def _citation_count(context: EvaluationContext, metric_id: str, attribute: str) -> MetricResultV1:
    rows = _citation_rows(context)
    if not rows:
        return _result(metric_id, None, na_reason="citation_verification_unavailable")
    value = sum(int(row.attributes.get(attribute) or 0) for row in rows)
    return _result(metric_id, value, passed=value == 0, refs=[row.event_id for row in rows])


def provider_equivalence_score(context: EvaluationContext) -> MetricResultV1:
    value = context.trace.metadata.get("provider_equivalence_score")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return _result("provider_equivalence_score", None, na_reason="provider_comparison_unavailable")
    score = max(0.0, min(1.0, float(value)))
    return _result("provider_equivalence_score", score, passed=score == 1.0)


def fallback_used(context: EvaluationContext) -> MetricResultV1:
    rows = [event for event in context.trace.events if event.kind == "provider.fallback"]
    return _result("fallback_used", bool(rows), refs=[row.event_id for row in rows])


def circuit_open_count(context: EvaluationContext) -> MetricResultV1:
    rows = [
        event
        for event in context.trace.events
        if event.kind in {"provider.circuit", "retrieval.provider"}
        and (event.attributes.get("state") == "open" or event.attributes.get("reason") == "circuit_open")
    ]
    return _result("circuit_open_count", len(rows), refs=[row.event_id for row in rows])


def governance_evidence_evaluators() -> list[FunctionalMetricEvaluator]:
    functions = (
        ("memory_candidate_created", memory_candidate_created),
        ("memory_review_triggered", memory_review_triggered),
        ("no_secret_leak_in_memory", no_secret_leak_in_memory),
        ("citation_groundedness_method", citation_groundedness_method),
        ("unsupported_claim_count", lambda context: _citation_count(context, "unsupported_claim_count", "unsupported_claim_count")),
        ("invalid_remote_citation_count", lambda context: _citation_count(context, "invalid_remote_citation_count", "invalid_remote_citation_count")),
        ("provider_equivalence_score", provider_equivalence_score),
        ("fallback_used", fallback_used),
        ("circuit_open_count", circuit_open_count),
    )
    return [FunctionalMetricEvaluator(metric_id, "governance", function) for metric_id, function in functions]


__all__ = ["governance_evidence_evaluators"]
