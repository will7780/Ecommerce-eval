from __future__ import annotations

from datetime import datetime, timezone

from commerce_eval.contracts import EvalCaseV1, TraceEnvelopeV1
from commerce_eval.core import EvaluationEngine
from commerce_eval.packs import all_evaluators


def test_engineering_and_governance_evidence_are_framework_neutral() -> None:
    trace = TraceEnvelopeV1(
        trace_id="evidence-trace",
        project_id="neutral-project",
        target_id="neutral-target",
        target_version="1",
        started_at=datetime.now(timezone.utc),
        output={"task_completed": False, "summary": "The tool failed; next step is retry.", "failure_acknowledged": True},
        metadata={"runtime_path": "custom-runtime", "provider_equivalence_score": 0.75},
        events=[
            {"event_id": "tool", "sequence": 0, "kind": "tool.call", "status": "blocked", "attributes": {"tool_id": "catalog.generate_listing", "guard_allowed": False}},
            {"event_id": "obs", "sequence": 1, "kind": "observation", "status": "error", "attributes": {"error_type": "input_missing"}},
            {"event_id": "verify", "sequence": 2, "kind": "answer.verify", "attributes": {"passed": True}, "evidence_refs": ["obs"]},
            {"event_id": "compact", "sequence": 3, "kind": "context.compaction", "attributes": {"chars_before": 1000, "chars_after": 400}},
            {"event_id": "review", "sequence": 4, "kind": "memory.review", "attributes": {"triggered": True}},
            {"event_id": "candidate", "sequence": 5, "kind": "memory.candidate", "attributes": {"created": True}},
            {"event_id": "citation", "sequence": 6, "kind": "citation.verify", "attributes": {"method": "lexical", "unsupported_claim_count": 1, "invalid_remote_citation_count": 0, "grounded": False}},
            {"event_id": "fallback", "sequence": 7, "kind": "provider.fallback", "attributes": {"success": True}},
            {"event_id": "circuit", "sequence": 8, "kind": "provider.circuit", "attributes": {"state": "open"}},
        ],
    )
    case = EvalCaseV1(case_id="evidence-case", name="Evidence", expected_tools=["catalog.generate_listing"])
    result = EvaluationEngine(all_evaluators()).evaluate(case, trace)
    metrics = {item.metric_id: item for item in result.metric_results}
    assert metrics["guard_block_rate"].value == 1.0
    assert metrics["failure_acknowledgement_rate"].value == 1.0
    assert metrics["answer_verification_pass_rate"].value == 1.0
    assert metrics["evidence_step_coverage"].value == 1.0
    assert metrics["context_compression_ratio"].value == 0.6
    assert metrics["runtime_path"].value == "custom-runtime"
    assert metrics["memory_candidate_created"].value is True
    assert metrics["memory_review_triggered"].value is True
    assert metrics["unsupported_claim_count"].value == 1
    assert metrics["fallback_used"].value is True
    assert metrics["circuit_open_count"].value == 1
    assert metrics["provider_equivalence_score"].value == 0.75
