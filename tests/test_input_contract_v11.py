from __future__ import annotations

import json

import pytest

from commerce_eval.contracts import EvalCaseV1, ModelInputSnapshotV1, TraceEnvelopeV1
from commerce_eval.core import TraceNormalizer
from commerce_eval.core.redaction import contains_secret, redact_recursive


def test_legacy_case_serialization_does_not_change_checksum_shape():
    case = EvalCaseV1(case_id="legacy", name="Legacy")
    assert "scenario_data" not in case.model_dump()
    assert "artifact_requirements" not in case.model_dump()
    current = case.model_copy(update={"contract_version": "1.1"})
    assert "scenario_data" in current.model_dump()


def test_input_snapshots_keep_roles_rounds_and_redaction():
    snapshot = ModelInputSnapshotV1(snapshot_id="s1", model_call_id="m1", round=1, captured=True,
        source="request_capture", messages=[{"role":"system","content":"Actual system"},
        {"role":"developer","content":"Actual developer"}, {"role":"user","content":"User update"},
        {"role":"tool","content":"token=example-sensitive","tool_call_id":"c1"}],
        tools=[{"type":"function","function":{"name":"catalog.read","parameters":{"type":"object","properties":{"limit":{"type":"integer"}}}}}])
    trace = TraceEnvelopeV1(contract_version="1.1", trace_id="captured", project_id="p", target_id="t", target_version="1",
        events=[{"event_id":"s1","sequence":0,"kind":"model.input","attributes":snapshot.model_dump()}])
    normalized = TraceNormalizer.normalize(trace)
    attrs = normalized.events[0].attributes
    assert [m["role"] for m in attrs["messages"]] == ["system","developer","user","tool"]
    assert attrs["tools"][0]["function"]["parameters"]["properties"]["limit"]["type"] == "integer"
    assert "example-sensitive" not in normalized.model_dump_json()
    assert attrs["redacted"] is True
    assert attrs["model_call_id"] == "m1"


def test_history_without_system_does_not_gain_a_snapshot():
    trace = TraceEnvelopeV1(trace_id="history", project_id="p", target_id="t", target_version="1", input={"message":"hello"})
    assert TraceNormalizer.normalize(trace).events == []
    with pytest.raises(ValueError, match="snapshot_omission_reason_required"):
        ModelInputSnapshotV1(snapshot_id="missing", model_call_id="unknown", round=0, source="legacy")


def test_long_event_list_is_not_silently_cut_at_256():
    trace = TraceEnvelopeV1(trace_id="long", project_id="p", target_id="t", target_version="1",
        events=[{"event_id":f"event-{i}","sequence":i,"kind":"observation","attributes":{"index":i}} for i in range(300)])
    assert len(TraceNormalizer.normalize(trace).events) == 300


def test_structured_sensitive_field_does_not_raise_or_leak():
    raw = {"credentials":{"nested":["example-sensitive"]}}
    assert contains_secret(raw)
    assert not contains_secret(redact_recursive(raw))
    assert "example-sensitive" not in json.dumps(redact_recursive(raw))
