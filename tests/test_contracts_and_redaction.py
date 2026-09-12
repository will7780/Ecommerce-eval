from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from commerce_eval.contracts import EvalCaseV1, ToolContractV1, TraceEnvelopeV1
from commerce_eval.core import ContractNormalizer, TraceNormalizer, redact_recursive


ROOT = Path(__file__).resolve().parents[1]


def test_tool_contract_round_trip_and_schema_validation() -> None:
    payload = json.loads((ROOT / "examples" / "tool-contracts.json").read_text(encoding="utf-8"))
    contracts = [ContractNormalizer.tool(item) for item in payload["tools"]]
    assert len(contracts) == 4
    assert ToolContractV1.model_validate_json(contracts[0].model_dump_json()) == contracts[0]


def test_invalid_json_schema_is_rejected() -> None:
    with pytest.raises(Exception):
        ToolContractV1(
            tool_id="catalog.invalid",
            version="1",
            title="Invalid",
            input_schema={"type": "not-a-json-schema-type"},
        )


def test_dataset_jsonl_round_trip() -> None:
    rows = [
        EvalCaseV1.model_validate_json(line)
        for line in (ROOT / "examples" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row.case_id for row in rows] == ["listing-launch", "failure-replan", "clarify-market"]


def test_unknown_event_kind_remains_forward_compatible() -> None:
    trace = TraceEnvelopeV1(
        trace_id="unknown-kind",
        project_id="demo",
        target_id="target",
        target_version="1",
        events=[{"event_id": "e1", "sequence": 0, "kind": "vendor.future_event"}],
    )
    normalized = TraceNormalizer.normalize(trace)
    assert normalized.events[0].kind == "vendor.future_event"


def test_redaction_removes_secrets_paths_and_hidden_reasoning() -> None:
    cleaned = redact_recursive(
        {
            "api_key": "secret-value",
            "message": "token=visible-secret C:\\Users\\someone\\private\\data.json",
            "chain_of_thought": "private reasoning",
        }
    )
    serialized = json.dumps(cleaned)
    assert "secret-value" not in serialized
    assert "visible-secret" not in serialized
    assert "someone" not in serialized
    assert "private reasoning" not in serialized
    assert "[REDACTED]" in serialized
    assert "[OMITTED]" in serialized


def test_trace_normalizer_redacts_contract_declared_business_fields() -> None:
    trace = TraceEnvelopeV1(
        trace_id="declared-sensitive-field",
        project_id="demo",
        target_id="target",
        target_version="1",
        input={"merchant_reference": "merchant-private-42"},
        output={"nested": {"merchant_reference": "merchant-private-42"}},
        events=[
            {
                "event_id": "tool-1",
                "sequence": 0,
                "kind": "tool.call",
                "attributes": {
                    "tool_id": "catalog.lookup_listing",
                    "arguments": {"merchant_reference": "merchant-private-42"},
                },
            }
        ],
    )
    normalized = TraceNormalizer.normalize(trace, sensitive_fields={"merchant_reference"})
    serialized = normalized.model_dump_json()
    assert "merchant-private-42" not in serialized
    assert serialized.count("[REDACTED]") == 3


def test_contract_rejects_duplicate_sequences() -> None:
    with pytest.raises(ValidationError, match="trace_event_sequence_duplicate"):
        TraceEnvelopeV1(
            trace_id="duplicate-sequence",
            project_id="demo",
            target_id="target",
            target_version="1",
            events=[
                {"event_id": "a", "sequence": 0, "kind": "model.call"},
                {"event_id": "b", "sequence": 0, "kind": "tool.call"},
            ],
        )

