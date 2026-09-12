"""Canonical normalization before evaluation, storage, export, or UI output."""

from __future__ import annotations

import hashlib
import json
from datetime import timezone
from typing import Any, Iterable, Mapping

from commerce_eval.contracts import EvalCaseV1, ToolContractV1, TraceEnvelopeV1

from .redaction import redact_declared_fields, redact_recursive


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_checksum(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class TraceNormalizer:
    @staticmethod
    def normalize(
        payload: TraceEnvelopeV1 | Mapping[str, Any], *, sensitive_fields: Iterable[str] = ()
    ) -> TraceEnvelopeV1:
        raw = payload.model_dump(mode="json") if isinstance(payload, TraceEnvelopeV1) else dict(payload)
        declared = tuple(sensitive_fields)
        if declared:
            for field in ("input", "output", "metadata", "tags"):
                raw[field] = redact_declared_fields(raw.get(field, {}), declared)
            raw["events"] = [
                {**dict(event), "attributes": redact_declared_fields(dict(event).get("attributes", {}), declared)}
                if isinstance(event, Mapping) else event
                for event in raw.get("events", [])
            ]
        if len(raw.get("events", [])) > 10000:
            raise ValueError("trace_event_limit_exceeded")
        cleaned = redact_recursive(raw, max_depth=24, max_items=10000)
        for event in cleaned.get("events", []):
            if isinstance(event, dict) and event.get("kind") == "model.input":
                attributes = event.get("attributes") or {}
                snapshot = attributes.get("snapshot", attributes)
                if isinstance(snapshot, dict):
                    encoded = canonical_json(snapshot)
                    if "[TRUNCATED]" in encoded or "[OMITTED]" in encoded:
                        snapshot["truncated"] = True
                        snapshot.setdefault("omission_reason", "redaction_or_capture_limit")
                    if "[REDACTED]" in encoded:
                        snapshot["redacted"] = True
        events = list(cleaned.get("events") or [])
        events.sort(key=lambda item: (int(item.get("sequence", 0)), str(item.get("event_id", ""))))
        for sequence, event in enumerate(events):
            event["sequence"] = sequence
            event.setdefault("event_id", f"event_{sequence:04d}")
            event.setdefault("kind", "unknown")
            event.setdefault("status", "ok")
            event.setdefault("attributes", {})
            event.setdefault("evidence_refs", [])
        cleaned["events"] = events
        normalized = TraceEnvelopeV1.model_validate(cleaned)
        if normalized.started_at.tzinfo is None:
            normalized.started_at = normalized.started_at.replace(tzinfo=timezone.utc)
        if normalized.ended_at and normalized.ended_at.tzinfo is None:
            normalized.ended_at = normalized.ended_at.replace(tzinfo=timezone.utc)
        return normalized


class ContractNormalizer:
    @staticmethod
    def tool(payload: ToolContractV1 | Mapping[str, Any]) -> ToolContractV1:
        raw = payload.model_dump(mode="json") if isinstance(payload, ToolContractV1) else dict(payload)
        return ToolContractV1.model_validate(redact_recursive(raw))

    @staticmethod
    def case(payload: EvalCaseV1 | Mapping[str, Any]) -> EvalCaseV1:
        raw = payload.model_dump(mode="json") if isinstance(payload, EvalCaseV1) else dict(payload)
        return EvalCaseV1.model_validate(redact_recursive(raw, max_depth=24, max_items=10000))

