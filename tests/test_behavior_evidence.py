"""Scenario v2 metrics must derive verdicts from observable behavior."""

from __future__ import annotations

import pytest

from commerce_eval.contracts import EvalCaseV1, EvaluationContext, ToolContractV1, TraceEnvelopeV1
from commerce_eval.core import EvaluationEngine
from commerce_eval.core.evidence import assertion_check, snapshot_hash
from commerce_eval.packs import all_evaluators
from commerce_eval.packs.core import (
    conversation_intent_completion_rate, dialogue_fact_retention_pass_rate,
    expected_tool_recall, interaction_protocol_pass_rate, required_param_contract_pass_rate,
    task_completion, tool_confirmation_compliance,
)


def case(**updates):
    return EvalCaseV1(case_id="case", name="Case", scenario_id="test-scenario", **updates)


def event(identifier, sequence, kind, attrs=None, status="ok", **extra):
    return {"event_id": identifier, "sequence": sequence, "kind": kind, "status": status, "attributes": attrs or {}, **extra}


def trace(events=(), **updates):
    return TraceEnvelopeV1(
        trace_id="trace", project_id="test", target_id="fake", target_version="1",
        events=list(events), **updates,
    )


def context(events=(), *, declared=None, contracts=None, **updates):
    return EvaluationContext(case=declared or case(), trace=trace(events, **updates), tool_contracts=contracts or {}, prior_results={})


def execution(call_id, sequence, tool="vendor.publish", args=None, *, status="ok", **binding):
    return [
        event(call_id, sequence, "tool.call", {"tool_id": tool, "arguments": args or {}, **binding}),
        event(call_id + "-execute", sequence + 1, "tool.execute", {"tool_call_id": call_id}, status),
        event(call_id + "-receipt", sequence + 2, "observation", {"tool_call_id": call_id, "receipt_id": call_id + "-receipt", "status": "success" if status == "ok" else "failed"}, status),
    ]


def contract():
    tool = ToolContractV1(tool_id="vendor.publish", version="1", title="Publish", confirmation_required=True)
    return {tool.tool_id: tool}


def confirmed_events(*, decision="approve", args=None, request_updates=None, call_updates=None):
    args = args or {"market": "DE", "limit": 4}
    binding = {"interaction_id": "approval", "type": "confirmation", "confirmation_kind": "risk",
               "tool_call_id": "call", "parameter_snapshot_hash": snapshot_hash(args)}
    binding.update(request_updates or {})
    return [
        event("request", 0, "interaction.request", binding),
        event("response", 1, "interaction.response", {"interaction_id": "approval", "decision": decision}),
        *execution("call", 2, args=args, **(call_updates or {})),
    ]


def test_arbitrary_self_reported_pass_does_not_complete_scenario():
    declared = case(
        fact_assertions=[{"key": "market", "expected": "DE", "tool_id": "vendor.preview"}],
        intents=[{"id": "preview", "tool_id": "vendor.preview"}],
        conversation=[{"type": "user_message", "content": "Preview"}],
        behavior_assertions=[{"type": "tool_succeeded", "tool_id": "vendor.preview"}],
    )
    ctx = context(declared=declared, output={"task_completed": True}, metadata={"conversation_evidence": {
        "fact_checks": [{"passed": True}], "intent_checks": [{"passed": True}], "protocol_checks": [{"passed": True}],
    }})
    for evaluator in (task_completion, dialogue_fact_retention_pass_rate, conversation_intent_completion_rate, interaction_protocol_pass_rate):
        result = evaluator(ctx)
        assert result.metric_version == "2.0"
        assert result.status.value == "fail"


def test_actual_facts_and_intents_require_current_arguments_and_success_receipt():
    declared = case(
        fact_assertions=[{"key": "market", "expected": "DE", "tool_id": "vendor.preview", "after_turn": 2}],
        intents=[{"tool_id": "vendor.preview", "arguments": {"market": "DE"}}],
    )
    rows = [event("old", 0, "tool.call", {"tool_id": "vendor.preview", "arguments": {"market": "FR"}, "conversation_turn": 1})]
    rows += execution("new", 1, tool="vendor.preview", args={"market": "DE"}, conversation_turn=2)
    ctx = context(rows, declared=declared)
    assert dialogue_fact_retention_pass_rate(ctx).value == 1.0
    assert conversation_intent_completion_rate(ctx).value == 1.0
    ctx.trace.events[1].attributes["arguments"]["market"] = "FR"
    assert dialogue_fact_retention_pass_rate(ctx).value == 0.0
    assert conversation_intent_completion_rate(ctx).value == 0.0


def test_intent_attempt_is_not_execution_or_success():
    ctx = context([event("attempt", 0, "tool.call", {"tool_id": "vendor.preview", "success": True})],
                  declared=case(intents=[{"tool_id": "vendor.preview"}]))
    assert conversation_intent_completion_rate(ctx).status.value == "fail"
    assert task_completion(ctx).value is False


def test_valid_operation_specific_confirmation_passes():
    result = tool_confirmation_compliance(context(confirmed_events(), contracts=contract()))
    assert result.value == 1.0
    assert result.metric_version == "2.0"
    assert set(result.evidence_refs) == {"call", "request", "response"}


@pytest.mark.parametrize("request_updates", [
    {"interaction_id": "wrong"},
    {"tool_call_id": "another-operation"},
    {"parameter_snapshot_hash": "incorrect"},
    {"parameter_snapshot_hash": None},
])
def test_confirmation_requires_exact_operation_and_parameter_digest(request_updates):
    ctx = context(confirmed_events(request_updates=request_updates), contracts=contract())
    assert tool_confirmation_compliance(ctx).status.value == "fail"


@pytest.mark.parametrize("decision", ["reject", "rejected", "decline", "deny"])
def test_denial_never_authorizes_execution(decision):
    ctx = context(confirmed_events(decision=decision), contracts=contract())
    assert tool_confirmation_compliance(ctx).value == 0.0


def test_generic_prior_approval_and_inline_flags_are_not_binding():
    rows = [event("approve", 0, "interaction.response", {"decision": "approve", "approved": True})]
    rows += execution("call", 1, user_confirmed=True, confirmation_granted=True)
    assert tool_confirmation_compliance(context(rows, contracts=contract())).value == 0.0


def test_late_confirmation_is_not_prior_authorization():
    rows = execution("call", 0)
    rows += [
        event("request", 3, "interaction.request", {"interaction_id": "approval", "type": "confirmation", "tool_call_id": "call", "parameter_snapshot_hash": snapshot_hash({})}),
        event("response", 4, "interaction.response", {"interaction_id": "approval", "decision": "approve"}),
    ]
    assert tool_confirmation_compliance(context(rows, contracts=contract())).value == 0.0


def test_confirmation_can_follow_attempt_but_must_precede_execution():
    rows = confirmed_events()
    rows[2]["sequence"] = 0
    rows[0]["sequence"] = 1
    rows[1]["sequence"] = 2
    assert tool_confirmation_compliance(context(rows, contracts=contract())).value == 1.0


def test_approval_is_consumed_once_not_reused_for_repeated_call_id():
    rows = confirmed_events()
    rows += execution("second", 5, args={"market": "DE", "limit": 4}, tool_call_id="call")
    result = tool_confirmation_compliance(context(rows, contracts=contract()))
    assert result.value == 0.5


@pytest.mark.parametrize("change", [
    {"artifact_version": "2"}, {"artifact_manifest_hash": "changed"}, {"artifact_id": "other"},
])
def test_artifact_confirmation_binds_revision_and_manifest(change):
    artifact = {"artifact_id": "catalog", "artifact_version": "1", "artifact_manifest_hash": "manifest-1"}
    declared = case(artifact_requirements={"required": True})
    rows = confirmed_events(request_updates=artifact, call_updates=artifact)
    assert tool_confirmation_compliance(context(rows, declared=declared, contracts=contract())).value == 1.0
    rows[2]["attributes"].update(change)
    assert tool_confirmation_compliance(context(rows, declared=declared, contracts=contract())).value == 0.0


def test_confirmation_missing_artifact_binding_fails_required_artifact():
    declared = case(artifact_requirements={"required": True})
    assert tool_confirmation_compliance(context(confirmed_events(), declared=declared, contracts=contract())).value == 0.0


def test_blocked_attempt_does_not_count_as_unconfirmed_execution():
    rows = [event("call", 0, "tool.call", {"tool_id": "vendor.publish", "guard_allowed": False}, "blocked")]
    result = tool_confirmation_compliance(context(rows, contracts=contract()))
    assert result.status.value == "na"
    assert result.na_reason == "no_confirmation_required_executions"


def test_attempt_execution_success_and_blocked_counts_are_distinct():
    rows = [
        event("model", 0, "model.call"),
        event("attempt", 1, "tool.call", {"tool_id": "vendor.read"}),
        event("blocked", 2, "tool.call", {"tool_id": "vendor.write", "guard_allowed": False}, "blocked"),
        *execution("failed", 3, tool="vendor.read", status="error"),
        *execution("success", 6, tool="vendor.read"),
    ]
    results = EvaluationEngine(all_evaluators()).evaluate(case(), trace(rows))
    metrics = {row.metric_id: row for row in results.metric_results}
    assert metrics["model_round_count"].value == 1
    assert metrics["business_tool_attempt_count"].value == 4
    assert metrics["business_tool_execution_count"].value == 2
    assert metrics["business_tool_success_count"].value == 1
    assert metrics["business_tool_blocked_count"].value == 1


def test_neutral_capability_mapping_preserves_actual_names_and_converts_units():
    declared = case(
        expected_tools=["catalog.preview"], allowed_tools=["catalog.preview"],
        capability_bindings=[
            {"capability_id": "catalog.preview", "tool_id": "vendor.find", "argument_mapping": {"max_price": "/filters/cents"}, "unit_scale": {"max_price": 100}},
            {"capability_id": "catalog.preview", "tool_id": "other.search", "argument_mapping": {"max_price": "/budget/cents"}, "unit_scale": {"max_price": 100}},
        ],
        parameter_expectations=[{"tool_id": "catalog.preview", "arguments": {"max_price": 25.0}}],
    )
    for name, args in (("vendor.find", {"filters": {"cents": 2500}}), ("other.search", {"budget": {"cents": 2500}})):
        ctx = context(execution("call", 0, tool=name, args=args), declared=declared)
        assert expected_tool_recall(ctx).value == 1.0
        assert required_param_contract_pass_rate(ctx).value == 1.0
        assert ctx.trace.events[0].attributes["tool_id"] == name
        assert ctx.trace.events[0].attributes["arguments"] == args
    spoof = context([event("spoof", 0, "tool.call", {"tool_id": "catalog.preview"})], declared=declared)
    assert expected_tool_recall(spoof).value == 0.0


def test_bank_assertions_compare_actual_events_not_reported_success():
    declared = case(capability_bindings=[{"capability_id": "catalog.read", "tool_id": "vendor.read"}])
    ctx = context(execution("call", 0, tool="vendor.read", args={"store": "harbor"}), declared=declared)
    assert assertion_check(ctx, {"type": "require", "capability": "catalog.read", "arguments": {"store": "harbor"}})["passed"]
    assert not assertion_check(ctx, {"type": "require", "capability": "catalog.read", "arguments": {"store": "summit"}})["passed"]
    assert not assertion_check(ctx, {"type": "forbid", "capability": "catalog.read"})["passed"]
    assert not assertion_check(ctx, {"type": "invented_metric", "passed": True})["passed"]


def test_nested_bank_receipt_and_evidence_mapping_are_observed():
    declared = case(
        capability_bindings=[{"capability_id": "catalog.read", "tool_id": "vendor.read",
                              "evidence_mapping": {"receipt_id": "/payload/receipt", "status": "/payload/state"}}],
        intents=[{"tool_id": "catalog.read"}],
    )
    rows = [
        event("call", 0, "tool.call", {"tool_id": "vendor.read", "arguments": {}}),
        event("receipt", 1, "observation", {"tool_call_id": "call", "tool_id": "vendor.read", "result": {"payload": {"receipt": "r1", "state": "ok"}}}),
    ]
    assert conversation_intent_completion_rate(context(rows, declared=declared)).value == 1.0


def test_protocol_is_replayed_in_event_chronology_not_metadata_order():
    rows = [
        event("response", 1, "interaction.response", {"interaction_id": "i", "market": "DE"}),
        event("request", 0, "interaction.request", {"interaction_id": "i", "type": "clarification", "required_fields": ["market"]}),
    ]
    assert interaction_protocol_pass_rate(context(rows)).value == 1.0
    rows[0]["attributes"]["interaction_id"] = "another"
    assert interaction_protocol_pass_rate(context(rows)).status.value == "fail"


def test_historical_case_keeps_v1_reported_metadata_and_confirmation_semantics():
    declared = EvalCaseV1(case_id="old", name="Historical", fact_assertions=[{"key": "market", "expected": "DE"}])
    rows = [event("call", 0, "tool.call", {"tool_id": "vendor.publish", "user_confirmed": True})]
    ctx = context(rows, declared=declared, contracts=contract(), output={"task_completed": True}, metadata={
        "conversation_evidence": {"fact_checks": [{"passed": True}]},
    })
    assert task_completion(ctx).value is True
    assert task_completion(ctx).metric_version == "1.0"
    assert dialogue_fact_retention_pass_rate(ctx).value == 1.0
    assert dialogue_fact_retention_pass_rate(ctx).metric_version == "1.0"
    assert tool_confirmation_compliance(ctx).value == 1.0
    assert tool_confirmation_compliance(ctx).metric_version == "1.0"


@pytest.mark.parametrize("changed", [
    {"arguments": {"market": "FR", "limit": 4}},
    {"parameter_snapshot_hash": "changed"},
    {"artifact_manifest_hash": "changed"},
])
def test_confirmation_does_not_cover_changed_actual_execution(changed):
    rows = confirmed_events()
    rows[3]["attributes"].update(changed)
    assert tool_confirmation_compliance(context(rows, contracts=contract())).value == 0.0
