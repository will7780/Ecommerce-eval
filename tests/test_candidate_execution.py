"""Offline tests for answer isolation, protocol transitions and trace merging."""

from __future__ import annotations

import json

import httpx
import pytest

from commerce_eval.contracts import (
    EvalCaseV1, ExperimentSpecV1, TargetDefinitionV1, TargetRunRequestV1,
    TargetRunResponseV1, TraceEnvelopeV1,
)
from commerce_eval.experiments.runner import ExperimentRunner, merge_turn_traces
from commerce_eval.targets import HTTPAgentTarget, PythonAgentTarget
from commerce_eval.targets.base import candidate_case, candidate_request_payload


def case_with_answers():
    return EvalCaseV1(
        case_id="public-case", version="7", name="HIDDEN_NAME",
        input={
            "message": "Current request", "market": "DE",
            "assets": [
                {"asset_id": "catalog", "permitted": True, "rows": [{"sku": "public-sku", "expectedAnswer": "HIDDEN_NESTED"}],
                 "content": json.dumps({"sku": "public-sku", "reference_answer": "HIDDEN_JSON"})},
                {"asset_id": "denied", "permitted": False, "content": "HIDDEN_ASSET"},
            ],
            "context": {"message": "HIDDEN_CONTEXT"},
            "futureTurns": ["HIDDEN_TURNS"], "answer_key": "HIDDEN_KEY",
        },
        scenario_id="HIDDEN_SCENE", scenario_data={"references": "HIDDEN_SCENARIO"},
        behavior_assertions=[{"expected": "HIDDEN_BEHAVIOR"}],
        capability_bindings=[{"tool_id": "HIDDEN_MAPPING"}],
        artifact_requirements={"expected": "HIDDEN_ARTIFACT"},
        expected_tools=["HIDDEN_TOOL"], forbidden_tools=["HIDDEN_FORBIDDEN"],
        required_sequence=["HIDDEN_SEQUENCE"], allowed_tools=["HIDDEN_ALLOWED"],
        parameter_expectations=[{"tool_id": "HIDDEN_PARAMETER", "arguments": {"key": "HIDDEN_VALUE"}}],
        outcome_assertions={"key": "HIDDEN_OUTCOME"}, fact_assertions=[{"key": "HIDDEN_FACT"}],
        intents=[{"id": "HIDDEN_INTENT"}], tags=["HIDDEN_TAG"],
        gates=[{"metric_id": "HIDDEN_GATE", "operator": "equals", "expected": True}],
        conversation=[
            {"type": "user_message", "content": "Current request"},
            {"type": "interaction_response", "interaction_id": "fixture-only", "response": {"answer": "HIDDEN_REPLY"}},
            {"type": "user_message", "content": "HIDDEN_FUTURE"},
        ],
    )


def request(case=None):
    return TargetRunRequestV1(
        request_id="run", session_id="session", case=case or case_with_answers(),
        execution_mode="dry_run", timeout_ms=1000,
    )


def response(*, pending=None, status="completed", trace_id="trace", events=None, version="1.0"):
    trace = TraceEnvelopeV1(
        contract_version=version, trace_id=trace_id, project_id="test",
        target_id="fake", target_version="1", status=status, output={"task_completed": True},
        events=events or [{"event_id": "model", "sequence": 0, "kind": "model.call"}],
    )
    return TargetRunResponseV1(
        contract_version=version, external_run_id="external", status=status, trace=trace,
        pending_interaction=pending,
    )


def assert_isolated(payload):
    encoded = json.dumps(payload)
    assert "HIDDEN" not in encoded
    assert payload["case"]["input"]["message"] == "Current request"
    assert payload["case"]["input"]["market"] == "DE"
    assert payload["case"]["input"]["assets"][0]["rows"] == [{"sku": "public-sku"}]
    assert set(payload["case"]) <= {"case_id", "version", "name", "input", "contract_version"}
    assert payload["case"]["case_id"] == "public-case"


@pytest.mark.parametrize("missing", [False, True])
def test_candidate_projection_is_safe_and_idempotent(monkeypatch, missing):
    if missing:
        def unavailable(_name):
            raise ModuleNotFoundError(name="commerce_eval.scenarios")
        monkeypatch.setattr("commerce_eval.targets.base.import_module", unavailable)
    original = case_with_answers()
    safe = candidate_case(original)
    assert safe is not original
    assert safe.conversation == [] and safe.expected_tools == [] and safe.gates == []
    assert safe.scenario_id is None
    assert_isolated(candidate_request_payload(request(original)))
    assert_isolated(candidate_request_payload(request(safe)))
    assert original.expected_tools == ["HIDDEN_TOOL"]
    assert candidate_case(original, 2).input["message"] == "HIDDEN_FUTURE"


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2"])
@pytest.mark.parametrize("missing_projector", [False, True])
async def test_python_transport_never_serializes_hidden_answers(monkeypatch, version, missing_projector):
    if missing_projector:
        def unavailable(_name):
            raise ModuleNotFoundError(name="commerce_eval.scenarios")
        monkeypatch.setattr("commerce_eval.targets.base.import_module", unavailable)
    sent = []
    class Process:
        returncode = 0
        async def communicate(self, message):
            data = json.loads(message)
            sent.append(data)
            return response(version=version).model_dump_json().encode(), b""
    async def create(*_args, **_kwargs):
        return Process()
    monkeypatch.setattr("asyncio.create_subprocess_exec", create)
    target = PythonAgentTarget(TargetDefinitionV1(
        target_id="fake", version="1", name="Fake", adapter_type="python", safe_for_eval=True,
        config={"command": ["unused-fake-command"], "protocol_version": version},
    ))
    result = await target.start(request())
    assert result.status.value == "completed"
    assert sent[0]["protocol_version"] == version
    assert_isolated(sent[0]["payload"])


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["1.0", "1.1"])
@pytest.mark.parametrize("missing_projector", [False, True])
async def test_http_transport_never_serializes_hidden_answers_and_accepts_headers(monkeypatch, version, missing_projector):
    if missing_projector:
        def unavailable(_name):
            raise ModuleNotFoundError(name="commerce_eval.scenarios")
        monkeypatch.setattr("commerce_eval.targets.base.import_module", unavailable)
    async def handle(wire):
        assert_isolated(json.loads(wire.content))
        assert wire.headers["X-Agent-Eval-Protocol"] == version
        assert wire.headers["X-Agent-Eval-Accept-Protocol"] == "1.0, 1.1, 1.2"
        return httpx.Response(200, headers={"X-Agent-Eval-Protocol": version}, json=response(version=version).model_dump(mode="json"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        target = HTTPAgentTarget(TargetDefinitionV1(
            target_id="fake", version="1", name="Fake", adapter_type="http", safe_for_eval=True,
            config={"base_url": "https://fake.invalid", "protocol_version": version},
        ), client=client)
        result = await target.start(request())
    assert result.status.value == "completed"


class FakeTarget:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.starts = []
        self.resumes = []
    async def start(self, value):
        self.starts.append(value)
        return next(self.responses)
    async def resume(self, value):
        self.resumes.append(value)
        return next(self.responses)


def spec():
    return ExperimentSpecV1(
        experiment_id="experiment", project_id="test", name="Test",
        dataset_id="dataset", dataset_version="1", target_id="fake", target_version="1",
    )


async def execute(target, case):
    return await ExperimentRunner(None)._execute_case(
        target, spec(), case, 1, session_id="session", request_id="run",
    )


def conversation_case(next_event):
    return EvalCaseV1(
        case_id="case", name="Case", expected_tools=["hidden.tool"],
        input={"message": "First", "assets": [{"asset_id": "rules", "permitted": True, "content": "Public policy"}]},
        conversation=[{"type": "user_message", "content": "First"}, next_event],
    )


def scripted(data):
    return {"type": "interaction_response", "interaction_id": "fixture-id", "response": data}


@pytest.mark.asyncio
@pytest.mark.parametrize("pending,data,reason", [
    ({"type": "clarification", "required_fields": ["market"]}, {"decision": "approve"}, "interaction_type_mismatch"),
    ({"type": "clarification", "required_fields": ["market", "source"]}, {"market": "DE"}, "interaction_fields_mismatch"),
    ({"type": "confirmation"}, {}, "explicit_confirmation_decision_required"),
    ({"type": "confirmation", "parameter_snapshot_hash": "current"}, {"decision": "approve", "parameter_snapshot_hash": "stale"}, "confirmation_binding_mismatch"),
])
async def test_script_mismatch_is_structured_and_does_not_resume(pending, data, reason):
    pending = {"interaction_id": "real-id", "prompt": "Question", **pending}
    target = FakeTarget([response(pending=pending, status="awaiting_input" if pending["type"] == "clarification" else "awaiting_confirmation")])
    result = await execute(target, conversation_case(scripted(data)))
    assert result.status.value == "failed"
    assert result.error_type == "interaction_protocol_error"
    assert result.trace.metadata["protocol_error"] == reason
    assert result.trace.events[-1].kind == "error"
    assert any(row.kind == "model.call" for row in result.trace.events)
    assert target.resumes == []
    assert target.starts[0].case.expected_tools == []


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["reject", "rejected", "decline"])
async def test_explicit_decline_is_forwarded_to_actual_pending_id(decision):
    pending = {"interaction_id": "real-id", "type": "confirmation", "prompt": "Publish?"}
    target = FakeTarget([response(pending=pending, status="awaiting_confirmation"), response(trace_id="last")])
    result = await execute(target, conversation_case(scripted({"decision": decision})))
    assert result.status.value == "completed"
    assert target.resumes[0].interaction_id == "real-id"
    assert target.resumes[0].response == {"decision": decision}
    assert len(target.starts) == 1
    actual = [row for row in result.trace.events if row.kind == "interaction.response"]
    assert len(actual) == 1 and actual[0].attributes["decision"] == decision


@pytest.mark.asyncio
@pytest.mark.parametrize("status,pending,next_event,reason", [
    ("completed", None, scripted({"answer": "DE"}), "response_without_pending"),
    ("awaiting_input", None, scripted({"answer": "DE"}), "missing_pending_interaction"),
    ("awaiting_input", {"interaction_id": "real", "type": "clarification", "prompt": "Market?"}, {"type": "user_message", "content": "Next"}, "start_while_pending"),
    ("completed", {"interaction_id": "real", "type": "confirmation", "prompt": "Approve?"}, scripted({"decision": "approve"}), "pending_status_mismatch"),
])
async def test_invalid_transitions_cannot_start_another_run(status, pending, next_event, reason):
    target = FakeTarget([response(status=status, pending=pending)])
    result = await execute(target, conversation_case(next_event))
    assert result.trace.metadata["protocol_error"] == reason
    assert len(target.starts) == 1 and not target.resumes


@pytest.mark.asyncio
async def test_unanswered_pending_at_end_is_not_success():
    target = FakeTarget([response(status="awaiting_confirmation", pending={"interaction_id": "real", "type": "confirmation", "prompt": "Approve?"})])
    result = await execute(target, EvalCaseV1(case_id="case", name="Case"))
    assert result.trace.metadata["protocol_error"] == "script_exhausted_while_pending"
    assert result.trace.output["task_completed"] is False


@pytest.mark.asyncio
async def test_later_user_turn_preserves_public_assets_but_not_future_messages():
    target = FakeTarget([response(), response(trace_id="second")])
    case = conversation_case({"type": "user_message", "content": "Second"})
    result = await execute(target, case)
    assert target.starts[0].case.input["message"] == "First"
    assert target.starts[1].case.input["message"] == "Second"
    assert target.starts[1].case.input["assets"][0]["content"] == "Public policy"
    messages = [row.attributes["content"] for row in result.trace.events if row.kind == "user.message"]
    assert messages == ["First", "Second"]


def test_cumulative_events_usage_and_model_input_references_are_not_duplicated():
    events = [
        {"event_id": "input", "sequence": 0, "kind": "model.input", "attributes": {
            "model_call_id": "model", "snapshot": {"model_call_id": "model", "messages": [{"role": "system", "content": "Actual system"}, {"role": "user", "content": "First"}]},
        }, "evidence_refs": ["model"]},
        {"event_id": "model", "sequence": 1, "kind": "model.call"},
    ]
    first = response(events=events).trace
    first.resource_usage.agent_llm_calls = 1
    first.resource_usage.agent_total_tokens = 10
    second = first.model_copy(deep=True)
    second.events.append(type(first.events[0])(event_id="model2", sequence=2, kind="model.call", parent_event_id="model"))
    second.resource_usage.agent_llm_calls = 2
    second.resource_usage.agent_total_tokens = 25
    merged = merge_turn_traces([first, second])
    assert len(merged.events) == 3
    assert merged.resource_usage.agent_llm_calls == 2
    assert merged.resource_usage.agent_total_tokens == 25
    snapshot, model, model2 = merged.events
    assert snapshot.attributes["snapshot"]["messages"][0]["content"] == "Actual system"
    assert snapshot.attributes["model_call_id"] == model.event_id
    assert snapshot.attributes["snapshot"]["model_call_id"] == model.event_id
    assert snapshot.evidence_refs == [model.event_id]
    assert model2.parent_event_id == model.event_id


def test_delta_trace_ids_reused_event_ids_are_distinct_and_chronological():
    first = response(trace_id="one").trace
    second = response(trace_id="two").trace
    first.resource_usage.agent_llm_calls = 1
    second.resource_usage.agent_llm_calls = 1
    merged = merge_turn_traces([first, second])
    assert len(merged.events) == 2
    assert len({row.event_id for row in merged.events}) == 2
    assert [row.sequence for row in merged.events] == [0, 1]
    assert merged.resource_usage.agent_llm_calls == 2


def test_demo_reference_does_not_follow_expected_tools():
    from commerce_eval.demo_runtime import _start
    payload = {"request_id": "demo", "case": {"case_id": "anything", "input": {"message": "Preview DE catalog"}, "expected_tools": ["hidden.answer"]}}
    result = _start(payload)
    assert "hidden.answer" not in json.dumps(result)
    assert result["trace"]["metadata"]["reference_actor"] is True
    assert result["trace"]["tags"]["actor"] == "scripted"


class MemoryRepository:
    def __init__(self, case, adapter="fake"):
        self.case = case
        self.adapter = adapter
        self.evaluations = []
        self.traces = []
        self.experiment = {}
    def get_target(self, *_args):
        return TargetDefinitionV1(target_id="fake", version="1", name="Fake", adapter_type=self.adapter, safe_for_eval=True)
    def get_dataset(self, *_args):
        return {"cases": [self.case.model_dump(mode="json")]}
    def get_evaluator_set(self, *_args):
        return {"metric_ids": []}
    def run_exists(self, *_args):
        return False
    def update_experiment(self, _identifier, **data):
        self.experiment.update(data)
    def experiment_is_cancelled(self, *_args):
        return False
    def save_trace(self, value, **_kwargs):
        self.traces.append(value)
        return value
    def save_evaluation(self, value):
        self.evaluations.append(value)
    def get_experiment(self, *_args):
        return self.experiment


@pytest.mark.asyncio
async def test_protocol_failed_case_cannot_pass_even_without_declared_gates():
    case = conversation_case(scripted({"answer": "DE"}))
    repository = MemoryRepository(case)
    target = FakeTarget([response()])
    resets = []
    async def reset(session_id):
        resets.append(session_id)
    target.reset = reset
    await ExperimentRunner(repository, target_factory=lambda _definition: target).run(spec())
    assert repository.evaluations[0].overall_pass is False
    assert repository.evaluations[0].gate_results[0].metric_id == "execution_protocol"
    assert "response_without_pending" in repository.evaluations[0].gate_failures[0]
    assert len(resets) == 1


@pytest.mark.asyncio
async def test_reference_fixture_is_explicitly_not_candidate_scored(monkeypatch):
    from commerce_eval.demo_runtime import ReferenceFixtureTarget
    from commerce_eval.targets import build_target
    declared = EvalCaseV1(case_id="fixture-case", name="Fixture", scenario_id="I01", scenario_data={"references": {"positive": []}})
    repository = MemoryRepository(declared, adapter="reference_fixture")
    observed = []
    def fixture(case, **_kwargs):
        observed.append(case)
        return response().trace
    monkeypatch.setattr("commerce_eval.demo_runtime.run_bank_fixture", fixture)
    target = build_target(repository.get_target())
    assert isinstance(target, ReferenceFixtureTarget)
    await ExperimentRunner(repository, target_factory=lambda _definition: target).run(spec())
    assert len(observed) == 1
    assert repository.evaluations == []
    assert repository.traces[0].metadata["candidate_evaluation"] is False
    assert repository.traces[0].metadata["reference_actor"] is False
    assert repository.traces[0].tags["actor"] == "reference_fixture"


@pytest.mark.asyncio
async def test_reference_fixture_only_accepts_evaluator_bound_case():
    from commerce_eval.demo_runtime import ReferenceFixtureTarget
    target = ReferenceFixtureTarget(MemoryRepository(EvalCaseV1(case_id="case", name="Case")).get_target())
    result = await target.start(request())
    assert result.status.value == "failed"
    assert result.error_type == "reference_case_not_bound"


@pytest.mark.asyncio
async def test_bank_script_is_consumed_only_after_matching_actual_pending():
    declared = EvalCaseV1(
        case_id="bank", name="Bank", scenario_id="M01", input={"message": "Choose store"},
        scenario_data={"interaction_script": [
            {"type": "clarification", "fields": ["store"], "response": {"store": "later-private"}},
        ]},
    )
    target = FakeTarget([
        response(status="awaiting_input", pending={
            "interaction_id": "actual", "type": "clarification", "prompt": "Store?", "required_fields": ["store"],
        }),
        response(trace_id="last"),
    ])
    result = await execute(target, declared)
    assert result.status.value == "completed"
    assert "later-private" not in target.starts[0].model_dump_json()
    assert target.resumes[0].interaction_id == "actual"
    assert target.resumes[0].response == {"store": "later-private"}


@pytest.mark.asyncio
async def test_bank_script_field_set_mismatch_cannot_use_other_question_answer():
    declared = EvalCaseV1(
        case_id="bank", name="Bank", scenario_id="M01",
        scenario_data={"interaction_script": [
            {"type": "clarification", "fields": ["store"], "response": {"answer": "harbor"}},
        ]},
    )
    target = FakeTarget([response(status="awaiting_input", pending={
        "interaction_id": "actual", "type": "clarification", "prompt": "Source?", "required_fields": ["source"],
    })])
    result = await execute(target, declared)
    assert result.trace.metadata["protocol_error"] == "interaction_fields_mismatch"
    assert not target.resumes


@pytest.mark.asyncio
async def test_bank_artifact_script_cannot_approve_risk_prompt():
    declared = EvalCaseV1(
        case_id="bank", name="Bank", scenario_id="A01",
        scenario_data={"interaction_script": [{"type": "artifact_review", "response": {"decision": "approved"}}]},
    )
    target = FakeTarget([response(status="awaiting_confirmation", pending={
        "interaction_id": "actual", "type": "confirmation", "confirmation_kind": "risk", "prompt": "Risk?",
    })])
    result = await execute(target, declared)
    assert result.trace.metadata["protocol_error"] == "interaction_type_mismatch"
    assert not target.resumes


@pytest.mark.asyncio
async def test_fixture_metadata_survives_real_repository_normalization(tmp_path):
    from commerce_eval.scenarios import compile_scenario, get_scenario_template
    from commerce_eval.demo_runtime import ReferenceFixtureTarget
    from commerce_eval.storage import Database, Repository
    definition = TargetDefinitionV1(
        target_id="fixture", version="0.2", name="Conformance", adapter_type="reference_fixture", safe_for_eval=True,
    )
    declared = compile_scenario(get_scenario_template("I01"))
    actor = ReferenceFixtureTarget(definition)
    actor.bind_fixture_cases([declared])
    result = await actor.start(request(candidate_case(declared)))
    database = Database(tmp_path / "fixture.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project(result.trace.project_id, "Fixture persistence")
    saved = repository.save_trace(result.trace)
    stored = repository.get_trace(saved.trace_id)
    assert stored["trace"]["metadata"]["reference_fixture"] is True
    assert stored["trace"]["metadata"]["reference_actor"] is False
    assert stored["trace"]["metadata"]["candidate_evaluation"] is False
    assert stored["metrics"] == []


@pytest.mark.asyncio
async def test_fixture_failure_still_carries_non_candidate_provenance(monkeypatch):
    from commerce_eval.targets import build_target
    declared = EvalCaseV1(case_id="fixture-case", name="Fixture", scenario_id="I01")
    repository = MemoryRepository(declared, adapter="reference_fixture")
    def fail(*_args, **_kwargs):
        raise ValueError("fixture-failed")
    monkeypatch.setattr("commerce_eval.demo_runtime.run_bank_fixture", fail)
    await ExperimentRunner(repository, target_factory=build_target).run(spec())
    assert repository.traces[0].metadata["reference_fixture"] is True
    assert repository.traces[0].metadata["candidate_execution"] is False
    assert not repository.evaluations


def test_cumulative_new_envelope_id_keeps_original_event_and_usage_identity():
    first = response().trace
    first.resource_usage.agent_llm_calls = 1
    second = first.model_copy(deep=True)
    second.trace_id = "different-envelope"
    second.events.append(type(first.events[0])(event_id="new-model", sequence=1, kind="model.call"))
    second.resource_usage.agent_llm_calls = 2
    merged = merge_turn_traces([first, second])
    assert len(merged.events) == 2
    assert merged.resource_usage.agent_llm_calls == 2


@pytest.mark.asyncio
async def test_changed_cumulative_history_is_structured_without_erasing_prior_input():
    first = response().trace
    second = first.model_copy(deep=True)
    second.metadata["event_scope"] = "cumulative"
    second.events[0].attributes["tampered"] = True
    target = FakeTarget([
        response().model_copy(update={"trace": first}),
        response().model_copy(update={"trace": second}),
    ])
    result = await execute(target, conversation_case({"type": "user_message", "content": "Second"}))
    assert result.status.value == "failed"
    assert result.trace.metadata["protocol_error"] == "cumulative_trace_history_changed"
    assert any(row.kind == "model.call" for row in result.trace.events)
    assert result.trace.events[0].attributes["content"] == "First"


@pytest.mark.asyncio
async def test_actual_pending_header_becomes_request_evidence_when_adapter_omits_event():
    from commerce_eval.core.evidence import protocol_checks
    pending = {"interaction_id": "actual", "type": "clarification", "prompt": "Market?", "required_fields": ["market"]}
    target = FakeTarget([response(status="awaiting_input", pending=pending), response(trace_id="done")])
    result = await execute(target, conversation_case(scripted({"market": "DE"})))
    requests = [row for row in result.trace.events if row.kind == "interaction.request"]
    assert len(requests) == 1
    assert requests[0].attributes["interaction_id"] == "actual"
    assert all(check["passed"] for check in protocol_checks(result.trace))


@pytest.mark.asyncio
async def test_resolved_interaction_id_cannot_be_reused_for_new_approval():
    pending = {"interaction_id": "actual", "type": "confirmation", "prompt": "Approve?"}
    target = FakeTarget([
        response(status="awaiting_confirmation", pending=pending),
        response(status="awaiting_confirmation", pending=pending, trace_id="second"),
    ])
    result = await execute(target, conversation_case(scripted({"decision": "approve"})))
    assert result.trace.metadata["protocol_error"] == "interaction_id_reused"
    assert len(target.resumes) == 1


@pytest.mark.asyncio
async def test_seeded_32_case_fixture_experiment_remains_ungraded_end_to_end(tmp_path):
    from commerce_eval.demo import seed_onboarding_demo
    from commerce_eval.storage import Database, Repository
    database = Database(tmp_path / "bank-experiment.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("bank-project", "Fixture integration")
    refs = seed_onboarding_demo(repository, "bank-project")
    run_spec = ExperimentSpecV1.model_validate(refs["experiment_spec"])
    repository.create_experiment(run_spec)
    result = await ExperimentRunner(repository).run(run_spec)
    assert result["status"] == "completed"
    assert result["completed_runs"] == 32
    rows = repository.list_traces(experiment_id=run_spec.experiment_id)
    assert len(rows) == 32
    for row in rows:
        stored = repository.get_trace(row["trace_id"])
        assert stored["trace"]["status"] == "completed"
        assert stored["trace"]["metadata"]["reference_fixture"] is True
        assert stored["trace"]["metadata"]["candidate_evaluation"] is False
        assert stored["trace"]["metadata"]["candidate_execution"] is False
        assert stored["evaluation_history"] == []
    database.dispose()


@pytest.mark.asyncio
async def test_fixture_target_uses_request_identity_without_mutating_static_fixture(monkeypatch):
    from commerce_eval.demo_runtime import ReferenceFixtureTarget
    declared = EvalCaseV1(case_id="case", name="Fixture", scenario_id="I01")
    static = response(trace_id="reference-I01-positive").trace
    monkeypatch.setattr("commerce_eval.demo_runtime.run_bank_fixture", lambda *_args, **_kwargs: static)
    target = ReferenceFixtureTarget(MemoryRepository(declared, adapter="reference_fixture").get_target())
    target.bind_fixture_cases([declared])
    outputs = []
    for identifier in ("request-project-a", "request-project-b"):
        run_request = request(declared).model_copy(update={"request_id": identifier})
        result = await target.start(run_request)
        assert result.trace.trace_id == result.external_run_id == identifier
        assert result.trace.metadata["fixture_trace_id"] == "reference-I01-positive"
        outputs.append(result.trace.trace_id)
    assert len(set(outputs)) == 2
    assert static.trace_id == "reference-I01-positive"


@pytest.mark.asyncio
@pytest.mark.parametrize("repetitions", [1, 2])
async def test_fixture_experiments_across_projects_have_unique_run_ids(tmp_path, repetitions):
    from commerce_eval.demo import seed_onboarding_demo
    from commerce_eval.storage import Database, Repository
    database = Database(tmp_path / "multiple-projects.db")
    database.initialize()
    repository = Repository(database)
    snapshots = {}
    try:
        for project in ("desktop-project", "mobile-project"):
            repository.create_project(project, project)
            refs = seed_onboarding_demo(repository, project)
            run_spec = ExperimentSpecV1.model_validate({
                **refs["experiment_spec"], "experiment_id": f"fixture-{project}",
                "repetitions": repetitions,
            })
            repository.create_experiment(run_spec)
            result = await ExperimentRunner(repository).run(run_spec)
            assert result["status"] == "completed"
            assert result["completed_runs"] == 32 * repetitions
            rows = repository.list_traces(experiment_id=run_spec.experiment_id, limit=128)
            assert len(rows) == 32 * repetitions
            assert len({row["case_id"] for row in rows}) == 32
            assert not set(snapshots).intersection(row["trace_id"] for row in rows)
            for row in rows:
                stored = repository.get_trace(row["trace_id"])
                assert stored["trace"]["project_id"] == project
                assert stored["trace"]["experiment_id"] == run_spec.experiment_id
                assert stored["trace"]["repetition"] in range(1, repetitions + 1)
                assert stored["evaluation_history"] == []
                assert stored["trace"]["metadata"]["reference_fixture"] is True
                snapshots[row["trace_id"]] = stored["trace"]
            resumed = await ExperimentRunner(repository).run(run_spec)
            assert resumed["completed_runs"] == 32 * repetitions
        assert len(repository.list_traces(limit=256)) == 64 * repetitions
        assert len(snapshots) == 64 * repetitions
        for identifier, snapshot in snapshots.items():
            assert repository.get_trace(identifier)["trace"] == snapshot
    finally:
        database.dispose()



@pytest.mark.asyncio
async def test_policy_exception_retains_simulation_provenance_and_failed_evaluation(monkeypatch):
    from commerce_eval.targets.reference_policy import ReferencePolicyTarget
    case = EvalCaseV1(case_id="policy-case", name="Policy", scenario_id="sandbox",
                      scenario_data={"environment": {"healthy": True}})
    repository = MemoryRepository(case, adapter="reference_policy")
    async def crash(_self, _request):
        raise ValueError("unexpected_policy_failure")
    monkeypatch.setattr(ReferencePolicyTarget, "start", crash)
    await ExperimentRunner(repository).run(spec())
    trace = repository.traces[0]
    assert trace.status.value == "failed"
    assert trace.metadata["actor"] == "reference_policy"
    assert trace.metadata["simulation"] is True
    assert trace.metadata["production_agent"] is False
    assert trace.metadata["candidate_evaluation"] is True
    assert trace.resource_usage.agent_llm_calls == 0
    assert repository.evaluations[0].overall_pass is False



def test_merge_preserves_causal_receipts_and_earlier_delta_evidence_without_rewriting_arguments():
    traces = []
    for index in range(3):
        identifier = f"operation-{index}"
        trace = response(trace_id=f"trace-{index}", events=[
            {"event_id": identifier, "sequence": 0, "kind": "tool.call",
             "attributes": {"tool_id": "actual.read", "arguments": {"tool_call_id": "public-business-value"}}},
            {"event_id": f"receipt-event-{index}", "sequence": 1, "kind": "observation",
             "attributes": {"tool_call_id": identifier, "result": {"tool_call_id": identifier, "receipt_id": f"receipt-{index}", "status": "ok"}}},
        ]).trace
        trace.metadata["event_scope"] = "delta"
        traces.append(trace)
    traces[-1].events.append(type(traces[-1].events[0])(
        event_id="final", sequence=2, kind="final_answer", attributes={"outcome": "completed"},
        evidence_refs=["receipt-event-0", "receipt-event-1", "receipt-event-2"],
    ))
    merged = merge_turn_traces(traces)
    by_id = {event.event_id: event for event in merged.events}
    final = merged.events[-1]
    assert all(reference in by_id for reference in final.evidence_refs)
    for observation in (event for event in merged.events if event.kind == "observation"):
        linked = by_id[observation.attributes["tool_call_id"]]
        assert linked.kind == "tool.call"
        assert linked.attributes["arguments"]["tool_call_id"] == "public-business-value"
        assert observation.attributes["result"]["tool_call_id"] == linked.event_id


def test_reused_delta_tool_ids_are_namespaced_with_receipts_not_business_arguments():
    first = response(events=[
        {"event_id": "call", "sequence": 0, "kind": "tool.call", "attributes": {"tool_call_id": "call", "arguments": {"tool_call_id": "call"}}},
        {"event_id": "receipt", "sequence": 1, "kind": "observation", "attributes": {"tool_call_id": "call", "result": {"tool_call_id": "call"}}},
    ]).trace
    second = first.model_copy(deep=True)
    first.metadata["event_scope"] = second.metadata["event_scope"] = "delta"
    merged = merge_turn_traces([first, second])
    calls = [event for event in merged.events if event.kind == "tool.call"]
    observations = [event for event in merged.events if event.kind == "observation"]
    assert calls[0].event_id != calls[1].event_id
    for call, observation in zip(calls, observations):
        assert call.attributes["tool_call_id"] == observation.attributes["tool_call_id"] == call.event_id
        assert observation.attributes["result"]["tool_call_id"] == call.event_id
        assert call.attributes["arguments"] == {"tool_call_id": "call"}



@pytest.mark.asyncio
@pytest.mark.parametrize("script_shape", ["scenario_script", "case_conversation"])
async def test_completed_task_starts_new_audit_in_same_session_with_target_owned_receipt(script_shape):
    initial_message = "Publish the current catalog."
    followup_message = "FUTURE_AUDIT: audit the successful publication at a negative ten percent threshold."
    case = EvalCaseV1(
        case_id="continuation", name="Private examiner title", scenario_id="generic-continuation",
        input={"message": initial_message, "assets": [{"asset_id": "rules", "permitted": True, "content": "Current public policy"}]},
        expected_tools=["HIDDEN_EXPECTATION"],
        scenario_data={
            "interaction_script": [{"type": "user_message", "content": followup_message}],
            "references": {"positive": "HIDDEN_REFERENCE"},
        },
    )
    if script_shape == "case_conversation":
        payload = case.model_dump()
        payload["conversation"] = [
            {"type": "user_message", "content": initial_message},
            {"type": "user_message", "content": followup_message},
        ]
        # Fixture-only prompting must not override the compiled candidate turns.
        payload["scenario_data"]["interaction_script"] = [
            {"type": "clarification", "fields": ["next_task"], "response": {"next_task": "HIDDEN_FIXTURE_RESPONSE"}},
        ]
        case = EvalCaseV1.model_validate(payload)

    class ReceiptOwningTarget:
        def __init__(self):
            self.starts = []
            self.operations = []
            self.receipts = {}
            self.resets = []

        async def start(self, value):
            self.starts.append(value.model_copy(deep=True))
            wire = value.case.model_dump_json()
            assert "HIDDEN" not in wire
            assert "target-owned-artifact" not in wire
            prior = self.receipts.get(value.session_id)
            if prior is None:
                assert value.case.input["message"] == initial_message
                assert followup_message not in wire and "FUTURE_AUDIT" not in wire
                operation = "actual.publish"
                args = {}
                receipt = {"artifact_id": "target-owned-artifact", "version": "target-owned-version",
                           "receipt_id": "target-owned-publication-receipt"}
                self.receipts[value.session_id] = receipt
            else:
                assert value.case.input["message"] == followup_message
                operation = "actual.audit_margin"
                args = {**prior, "threshold_percent": -10}
                receipt = {"receipt_id": "target-owned-audit-receipt", "publication_receipt": prior["receipt_id"]}
            self.operations.append(operation)
            call_id = value.request_id + "-operation"
            result = response(trace_id=value.request_id, events=[
                {"event_id": call_id, "sequence": 0, "kind": "tool.call",
                 "attributes": {"tool_id": operation, "arguments": args}},
                {"event_id": value.request_id + "-receipt", "sequence": 1, "kind": "observation",
                 "attributes": {"tool_call_id": call_id, "result": {**receipt, "status": "ok"}}},
                {"event_id": value.request_id + "-final", "sequence": 2, "kind": "final_answer",
                 "attributes": {"outcome": "completed"}, "evidence_refs": [value.request_id + "-receipt"]},
            ])
            result.external_run_id = value.request_id
            result.trace.metadata["event_scope"] = "delta"
            return result

        async def resume(self, value):
            pytest.fail("A new task after completion must not become a synthetic interaction response.")

        async def reset(self, session_id):
            assert self.operations == ["actual.publish", "actual.audit_margin"]
            self.resets.append(session_id)
            self.receipts.pop(session_id, None)

    target = ReceiptOwningTarget()
    repository = MemoryRepository(case)
    await ExperimentRunner(repository, target_factory=lambda _definition: target).run(spec())
    assert len(target.starts) == 2
    first, second = target.starts
    assert first.session_id == second.session_id
    assert first.request_id != second.request_id
    assert target.operations == ["actual.publish", "actual.audit_margin"]
    assert target.resets == [first.session_id]
    trace = repository.traces[0]
    assert trace.status.value == "completed" and repository.evaluations[0].overall_pass is True
    messages = [event.attributes["content"] for event in trace.events if event.kind == "user.message"]
    assert messages == [initial_message, followup_message]
    audit = next(event for event in trace.events if event.kind == "tool.call" and event.attributes["tool_id"] == "actual.audit_margin")
    assert audit.attributes["arguments"]["receipt_id"] == "target-owned-publication-receipt"
    assert audit.attributes["arguments"]["artifact_id"] == "target-owned-artifact"
    finals = [event for event in trace.events if event.kind == "final_answer"]
    user_turns = [event for event in trace.events if event.kind == "user.message"]
    assert finals[0].sequence < user_turns[1].sequence < audit.sequence
    assert trace.metadata.get("protocol_error") is None


@pytest.mark.asyncio
async def test_compiled_m03_delivers_new_user_message_after_legitimate_completion():
    from commerce_eval.scenarios import compile_scenario, get_scenario_template
    case = compile_scenario(get_scenario_template("M03"))
    target = FakeTarget([
        response(status="awaiting_confirmation", pending={
            "interaction_id": "actual-artifact-review", "type": "confirmation",
            "confirmation_kind": "artifact", "prompt": "Review this generated artifact.",
        }, trace_id="review"),
        response(status="awaiting_confirmation", pending={
            "interaction_id": "actual-publication-approval", "type": "confirmation",
            "confirmation_kind": "risk", "prompt": "Approve this publication.", "required_fields": ["publish"],
        }, trace_id="approval"),
        response(status="completed", trace_id="published"),
        response(status="completed", trace_id="audited"),
    ])
    result = await execute(target, case)
    assert result.status.value == "completed", result.trace.metadata.get("protocol_error")
    assert len(target.starts) == 2 and len(target.resumes) == 2
    first, audit = target.starts
    assert first.session_id == audit.session_id
    assert first.request_id != audit.request_id
    assert audit.case.input["message"] != first.case.input["message"]
    assert audit.case.input["message"] not in first.case.model_dump_json()
    assert [item.interaction_id for item in target.resumes] == ["actual-artifact-review", "actual-publication-approval"]
    assert all(item.external_run_id == "external" for item in target.resumes)
    assert not audit.case.conversation and not audit.case.scenario_data
    messages = [event.attributes["content"] for event in result.trace.events if event.kind == "user.message"]
    assert messages == [first.case.input["message"], audit.case.input["message"]]



@pytest.mark.asyncio
async def test_unprompted_scenario_response_cannot_be_reinterpreted_as_new_user_task():
    case = EvalCaseV1(
        case_id="invalid-followup", name="Invalid follow-up", scenario_id="generic-continuation",
        input={"message": "Publish the current catalog."},
        scenario_data={"interaction_script": [
            {"type": "clarification", "fields": ["next_task"],
             "response": {"next_task": "audit_margin", "threshold_percent": -10}},
        ]},
    )
    target = FakeTarget([response(status="completed")])
    result = await execute(target, case)
    assert result.status.value == "failed"
    assert result.trace.metadata["protocol_error"] == "response_without_pending"
    assert len(target.starts) == 1 and not target.resumes
