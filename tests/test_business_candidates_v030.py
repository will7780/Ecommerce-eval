"""Fake-model tests exercise the real candidate loop without credentials or DNS."""

from copy import deepcopy
import json

import pytest

from commerce_eval.business.bank import load_business_cases
from commerce_eval.business.candidates import ModelRequestBudget
from commerce_eval.business.environment import BusinessScenarioEnvironment
from commerce_eval.business.verifiers import evaluate_business_requirements
from commerce_eval.contracts.models import TargetDefinitionV1, TargetResumeRequestV1, TargetRunRequestV1
from commerce_eval.targets.business_candidate import BusinessCandidateTarget


def case(code):
    return next(row for row in load_business_cases() if row.scenario_id == code)


def definition(surface="business_interface"):
    return TargetDefinitionV1(contract_version="1.2", target_id=surface, version="0.3.0", name=surface,
                              adapter_type=surface, safe_for_eval=True,
                              config={"project_id": "isolated-project", "model_source": "fake_model"})


def request(case, session_id="session", request_id="request"):
    return TargetRunRequestV1(contract_version="1.2", request_id=request_id, session_id=session_id,
                              case=case, execution_mode="sandbox", timeout_ms=30000)


def call(name, **arguments):
    return {"content": None, "tool_calls": [{"id": "tool-" + str(call.count), "name": name, "arguments": arguments}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30,
                      "reasoning_tokens": 2, "cache_hit_tokens": 5, "cache_miss_tokens": 15}, "latency_ms": 1}


call.count = 0


def final(outcome="completed", **extra):
    return {"content": json.dumps({"outcome": outcome, "simulated": True, "published_row_ids": [],
            "failed_row_ids": [], "failures": [], "next_actions": [], **extra}),
            "tool_calls": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, "latency_ms": 1}


class FakeModel:
    def __init__(self, *responses, clock=None):
        self.responses = list(responses)
        self.requests = []
        self.clock = clock

    async def complete(self, messages, tools):
        self.requests.append({"messages": deepcopy(messages), "tools": deepcopy(tools)})
        if self.clock:
            self.clock[0] += .005
        item = self.responses.pop(0)
        if callable(item):
            item = item(messages)
        item = deepcopy(item)
        for index, tool in enumerate(item.get("tool_calls", [])):
            tool["id"] = f"tool-{len(self.requests)}-{index}"
        return item


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["business_interface", "file_editor"])
async def test_actual_model_messages_and_files_without_private_answers(tmp_path, surface):
    selected = case("I01")
    selected.scenario_data["private_sentinel"] = "PRIVATE_ANSWER_NEVER_VISIBLE"
    selected.scenario_data["interaction_script"] = [{"response": {"answer": "FUTURE_RESPONSE_NEVER_VISIBLE"}}]
    if surface == "business_interface":
        model = FakeModel(call("business_generate_catalog"), final())
    else:
        def write_from_observed_file(messages):
            rows = json.loads(json.loads(messages[-1]["content"])["content"])
            return call("write_file", path="artifacts/from-editor.json", content=json.dumps(rows))
        model = FakeModel(call("read_file", path="inputs/products.json"), write_from_observed_file, final())
    target = BusinessCandidateTarget(definition(surface), complete=model.complete,
                                     environment_factory=lambda c: BusinessScenarioEnvironment(c, tmp_path))
    target.bind_environment_cases([selected])
    result = await target.start(request(selected))
    try:
        assert result.status.value == "completed"
        bundle = target.export_business_evidence("session")
        assert bundle.project_id == "isolated-project"
        assert bundle.collector_id == "builtin-business-environment-v1"
        assert bundle.run_id == "session" and bundle.complete
        assert evaluate_business_requirements(selected, bundle).status.value == "pass"
        text = json.dumps(model.requests)
        assert "PRIVATE_ANSWER_NEVER_VISIBLE" not in text and "FUTURE_RESPONSE_NEVER_VISIBLE" not in text
        assert "business_requirements" not in text and "reference" not in text
        snapshots = [event for event in result.trace.events if event.kind == "model.input"]
        assert len(snapshots) == len(model.requests)
        assert snapshots[0].attributes["messages"] == model.requests[0]["messages"]
        assert result.trace.metadata["actor"] == "fake_model"
        assert result.trace.resource_usage.agent_reasoning_tokens is None  # final response omits it
    finally:
        await target.reset("session")
    with pytest.raises(ValueError, match="not_found"):
        target.export_business_evidence("session")


@pytest.mark.asyncio
async def test_clarification_uses_same_model_context_and_dynamic_interaction_id(tmp_path):
    selected = case("M02")
    model = FakeModel(call("ask_user", fields=["site"], prompt="Which current market?"),
                      call("business_generate_catalog", site="NL"), final())
    target = BusinessCandidateTarget(definition(), complete=model.complete,
                                     environment_factory=lambda c: BusinessScenarioEnvironment(c, tmp_path))
    target.bind_environment_cases([selected])
    first = await target.start(request(selected))
    assert first.status.value == "awaiting_input"
    assert not target.export_business_evidence("session").complete
    pending = first.pending_interaction
    resumed = await target.resume(TargetResumeRequestV1(request_id="resume", external_run_id=first.external_run_id,
        session_id="session", interaction_id=pending.interaction_id, response={"site": "NL"}, timeout_ms=30000))
    try:
        assert resumed.status.value == "completed"
        assert '"site": "NL"' in json.dumps(model.requests[-1]) .replace('\\"', '"')
        assert evaluate_business_requirements(selected, target.export_business_evidence("session")).status.value == "pass"
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_risk_refusal_and_tampered_resume_never_execute(tmp_path):
    selected = case("S02")
    model = FakeModel(call("business_generate_catalog"), call("confirm_publication"),
                      final("blocked", next_actions=["Wait for authorization."]))
    target = BusinessCandidateTarget(definition(), complete=model.complete,
                                     environment_factory=lambda c: BusinessScenarioEnvironment(c, tmp_path))
    target.bind_environment_cases([selected])
    first = await target.start(request(selected))
    assert first.status.value == "awaiting_confirmation"
    pending = first.pending_interaction
    base = dict(request_id="resume", external_run_id=first.external_run_id, session_id="session",
                interaction_id=pending.interaction_id, timeout_ms=30000)
    invalid = await target.resume(TargetResumeRequestV1(**base, response={"decision": "approved", "arguments": {}}))
    assert invalid.error_type == "interaction_response_invalid"
    assert len(model.requests) == 2
    assert not target.export_business_evidence("session").effects
    resumed = await target.resume(TargetResumeRequestV1(**base, response={"decision": "rejected"}))
    try:
        assert resumed.status.value == "completed"
        evidence = target.export_business_evidence("session")
        assert not evidence.effects
        graded = evaluate_business_requirements(selected, evidence)
        assert graded.status.value == "pass", [(r["status"], r.get("reason_code")) for r in graded.details["requirement_results"]]
        duplicate = await target.resume(TargetResumeRequestV1(**base, response={"decision": "approved"}))
        assert duplicate.error_type == "response_without_pending"
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_mixed_control_calls_are_all_blocked(tmp_path):
    mixed = call("ask_user", fields=["site"], prompt="Site?")
    mixed["tool_calls"].append({"id": "different", "name": "business_generate_catalog", "arguments": {}})
    model = FakeModel(mixed, final("blocked"))
    selected = case("M01")
    target = BusinessCandidateTarget(definition(), complete=model.complete,
                                     environment_factory=lambda c: BusinessScenarioEnvironment(c, tmp_path))
    target.bind_environment_cases([selected])
    try:
        result = await target.start(request(selected))
        assert result.status.value == "completed"
        assert not target.export_business_evidence("session").artifacts
        assert "interaction_tool_must_be_single" in json.dumps(result.trace.model_dump(mode="json"))
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_shared_request_budget_stops_both_surfaces_without_extra_model_call(tmp_path):
    budget = ModelRequestBudget(1)
    model = FakeModel(final())
    targets = [BusinessCandidateTarget(definition(shape), complete=model.complete, request_budget=budget,
               environment_factory=lambda c: BusinessScenarioEnvironment(c, tmp_path)) for shape in ("business_interface", "file_editor")]
    selected = case("I01")
    for target in targets:
        target.bind_environment_cases([selected])
    try:
        assert (await targets[0].start(request(selected, "one"))).status.value == "completed"
        second = await targets[1].start(request(selected, "two"))
        assert second.error_type == "model_request_budget_exhausted"
        assert len(model.requests) == 1
        assert second.trace.resource_usage.agent_total_tokens is None
    finally:
        await targets[0].reset("one")
        await targets[1].reset("two")


@pytest.mark.asyncio
async def test_missing_complete_does_not_look_for_any_credentials(tmp_path, monkeypatch):
    from commerce_eval.providers import CredentialResolver
    def forbidden(*args, **kwargs):
        raise AssertionError("must not resolve a key")
    monkeypatch.setattr(CredentialResolver, "resolve", forbidden)
    target = BusinessCandidateTarget(definition(), environment_factory=lambda c: BusinessScenarioEnvironment(c, tmp_path))
    selected = case("I01")
    target.bind_environment_cases([selected])
    try:
        assert (await target.start(request(selected))).error_type == "model_client_missing"
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_wait_time_is_excluded_with_injected_clock(tmp_path):
    clock = [0.0]
    model = FakeModel(call("ask_user", fields=["site"], prompt="Site?"), call("business_generate_catalog", site="DE"), final(), clock=clock)
    target = BusinessCandidateTarget(definition(), complete=model.complete, clock=lambda: clock[0],
                                     environment_factory=lambda c: BusinessScenarioEnvironment(c, tmp_path))
    selected = case("M01")
    target.bind_environment_cases([selected])
    first = await target.start(request(selected))
    clock[0] += 100
    result = await target.resume(TargetResumeRequestV1(request_id="resume", external_run_id=first.external_run_id,
            session_id="session", interaction_id=first.pending_interaction.interaction_id, response={"site": "DE"}, timeout_ms=30000))
    try:
        usage = result.trace.resource_usage
        assert usage.active_runtime_ms == pytest.approx(15)
        assert usage.user_wait_ms == pytest.approx(100000)
        assert usage.wall_runtime_ms == pytest.approx(100015)
        assert usage.estimated_cost is None
        evidence = target.export_business_evidence("session")
        assert (evidence.ended_at-evidence.started_at).total_seconds()*1000 == pytest.approx(usage.wall_runtime_ms)
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_company_change_starts_new_context_and_does_not_carry_approvals(tmp_path):
    model = FakeModel(final(), final())
    target = BusinessCandidateTarget(definition(), complete=model.complete,
                                     environment_factory=lambda c: BusinessScenarioEnvironment(c, tmp_path))
    first, second = case("I01"), case("M04")
    first.input["message"] = "PREVIOUS_COMPANY_PRIVATE_MARKER"
    target.bind_environment_cases([first, second])
    await target.start(request(first))
    await target.start(request(second, request_id="second"))
    try:
        assert "PREVIOUS_COMPANY_PRIVATE_MARKER" not in json.dumps(model.requests[-1])
        assert target.export_business_evidence("session").company_id == "summit"
    finally:
        await target.reset("session")


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["business_interface", "file_editor"])
async def test_s04_independent_resource_accounting_matches_candidate_collector(tmp_path, surface):
    selected = case("S04")
    if surface == "business_interface":
        model = FakeModel(call("business_generate_catalog"), final())
    else:
        def write(messages):
            content = json.loads(messages[-1]["content"])["content"]
            return call("write_file", path="artifacts/catalog.json", content=content)
        model = FakeModel(call("read_file", path="inputs/products.json"), write, final())
    target = BusinessCandidateTarget(definition(surface), complete=model.complete,
                                     environment_factory=lambda c: BusinessScenarioEnvironment(c, tmp_path))
    target.bind_environment_cases([selected])
    try:
        await target.start(request(selected))
        bundle = target.export_business_evidence("session")
        result = evaluate_business_requirements(selected, bundle)
        assert result.status.value == "pass", [(item["status"], item.get("reason_code")) for item in result.details["requirement_results"]]
        assert bundle.resource_usage.judge_total_tokens == 0
        assert bundle.resource_usage.agent_total_tokens > 0
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_model_hidden_fields_and_secret_json_do_not_reach_trace(tmp_path):
    selected = case("I01")
    response = final()
    response["reasoning_content"] = "PRIVATE_REASONING_DO_NOT_STORE"
    response["content"] = json.dumps({"api_key": "PRIVATE_CREDENTIAL_DO_NOT_STORE"})
    model = FakeModel(response)
    target = BusinessCandidateTarget(definition(), complete=model.complete,
                                     environment_factory=lambda c: BusinessScenarioEnvironment(c, tmp_path))
    target.bind_environment_cases([selected])
    try:
        result = await target.start(request(selected))
        output = result.model_dump_json() + target.export_business_evidence("session").model_dump_json()
        assert "PRIVATE_REASONING_DO_NOT_STORE" not in output
        assert "PRIVATE_CREDENTIAL_DO_NOT_STORE" not in output
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_previous_company_real_approval_cannot_authorize_new_company(tmp_path):
    prior, current = case("S01"), case("M04")
    model = FakeModel(call("business_generate_catalog"), call("business_check_artifact"),
        call("business_sample_artifact"), call("business_review_artifact"), call("confirm_publication"), final(),
        call("business_read_rules"), call("business_generate_catalog"), final())
    target = BusinessCandidateTarget(definition(), complete=model.complete,
                                     environment_factory=lambda c: BusinessScenarioEnvironment(c, tmp_path))
    target.bind_environment_cases([prior, current])
    result = await target.start(request(prior))
    for index in range(2):
        assert result.pending_interaction is not None
        result = await target.resume(TargetResumeRequestV1(request_id="approve-"+str(index), external_run_id=result.external_run_id,
                session_id="session", interaction_id=result.pending_interaction.interaction_id,
                response={"decision": "approved"}, timeout_ms=30000))
    old = target.export_business_evidence("session")
    assert len(old.reviews) == 2 and len(old.artifacts) == 1
    model.responses.insert(-1, call("business_publish", review_id=old.reviews[0]["review_id"], approval_id=old.reviews[1]["review_id"]))
    result = await target.start(request(current, request_id="new-company"))
    try:
        evidence = target.export_business_evidence("session")
        assert evidence.initial_state["prior_context"]["authorization_count"] == 2
        assert evidence.initial_state["prior_context"]["retained_messages"] == 0
        assert not evidence.reviews
        assert not [effect for effect in evidence.effects if effect["status"] == "executed"]
        assert any(effect.get("error_type") == "authorization_scope_denied" for effect in evidence.effects)
        assert all(event["company_id"] == "summit" for event in evidence.observations)
        graded = evaluate_business_requirements(current, evidence)
        assert graded.status.value == "pass", [(r["status"], r.get("reason_code")) for r in graded.details["requirement_results"]]
    finally:
        await target.reset("session")


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["business_interface", "file_editor"])
async def test_runner_a03_binds_scripted_revision_and_exports_before_reset(tmp_path, surface):
    from commerce_eval.business.bootstrap import seed_business_bank
    from commerce_eval.contracts import ExperimentSpecV1
    from commerce_eval.experiments.runner import ExperimentRunner
    from commerce_eval.storage import Database, Repository
    from commerce_eval.storage.business_evidence import load_business_evidence

    database = Database(tmp_path / "runner.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("isolated-project", "Offline Runner")
    bank = seed_business_bank(repository, "isolated-project", ["A03"])

    def step(action):
        if surface == "business_interface":
            return call({"check": "business_check_artifact", "sample": "business_sample_artifact",
                         "review": "business_review_artifact", "publish": "business_publish"}[action])
        return call("backend_request", method="POST",
                    path="/publication" if action == "publish" else "/artifact/" + action)

    def write_observed_source(messages):
        return call("write_file", path="artifacts/catalog.json",
                    content=json.loads(messages[-1]["content"])["content"])

    def generation():
        return [call("business_generate_catalog")] if surface == "business_interface" else [
            call("read_file", path="inputs/products.json"), write_observed_source]

    def report_observed_receipt(messages):
        receipt = json.loads(messages[-1]["content"])
        assert receipt["status"] == "ok", receipt
        return final(published_row_ids=receipt["row_ids"])

    model = FakeModel(*generation(), step("check"), step("sample"), step("review"),
                      *generation(), step("check"), step("sample"), step("review"),
                      step("publish"), report_observed_receipt)
    index = 0 if surface == "business_interface" else 1
    target_definition = TargetDefinitionV1.model_validate(bank["targets"][index])
    target_definition.config["model_source"] = "fake_model"
    target = BusinessCandidateTarget(target_definition, complete=model.complete,
        environment_factory=lambda selected: BusinessScenarioEnvironment(selected, tmp_path / "workspace"))
    spec = ExperimentSpecV1.model_validate({**bank["candidate_experiment_specs"][index],
                                           "experiment_id": "runner-a03-" + surface})
    repository.create_experiment(spec)
    try:
        result = await ExperimentRunner(repository, target_factory=lambda _: target).run(spec)
        assert result["status"] == "completed"
        traces = repository.list_traces(project_id="isolated-project", experiment_id=spec.experiment_id)
        assert len(traces) == 1
        detail = repository.get_trace(traces[0]["trace_id"])
        business = next(row for row in detail["metrics"] if row["metric_id"] == "business_acceptance_pass")
        assert business["status"] == "pass", json.dumps({"metric": business, "trace_output": detail["trace"]["output"]}, default=str)
        evidence = load_business_evidence(repository, traces[0]["trace_id"], project_id="isolated-project")
        assert evidence is not None
        assert [row["decision"] for row in evidence.reviews] == ["revise", "approved"]
        assert len(evidence.artifacts) == 2
        assert evidence.artifacts[0]["content_hash"] != evidence.artifacts[1]["content_hash"]
        published = [row for row in evidence.effects if row["status"] == "executed"]
        assert len(published) == 1
        assert published[0]["content_hash"] == evidence.artifacts[-1]["content_hash"]
        assert published[0]["review_id"] == evidence.reviews[-1]["review_id"]
        requests = [row for row in evidence.interactions if row["kind"] == "request"]
        responses = [row for row in evidence.interactions if row["kind"] == "response"]
        assert [row["interaction_id"] for row in requests] == [row["interaction_id"] for row in responses]
        assert target._sessions == {}
        assert model.responses == []
    finally:
        for session_id in list(target._sessions):
            await target.reset(session_id)
        database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["provider_address_forbidden", "provider_timeout", "provider_authentication_denied",
                                  "provider_backend_error", "provider_call_budget_exhausted"])
async def test_provider_failure_retains_safe_cause_latency_and_unknown_usage(tmp_path, monkeypatch, code):
    import socket
    from commerce_eval.providers import CredentialResolver, ProviderError

    def forbidden(*args, **kwargs):
        raise AssertionError("offline test must not resolve credentials or DNS")
    monkeypatch.setattr(CredentialResolver, "resolve", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    clock = [0.0]
    failure = ProviderError(code)
    failure.args = ("PRIVATE_EXCEPTION_VALUE_DO_NOT_LOG",)
    failure.response = {"api_key": "PRIVATE_RESPONSE_VALUE_DO_NOT_LOG"}
    failure.latency_ms = 17.5
    failure.usage = {"total_tokens": 999}  # A failed call does not establish billable usage.
    async def complete(messages, tools):
        clock[0] += .025
        raise failure
    target = BusinessCandidateTarget(definition(), complete=complete, clock=lambda: clock[0],
        environment_factory=lambda selected: BusinessScenarioEnvironment(selected, tmp_path))
    selected = case("I01")
    target.bind_environment_cases([selected])
    try:
        result = await target.start(request(selected))
        assert result.status.value == "failed"
        assert result.error_type == "model_request_failed"
        assert result.trace.output["error_type"] == "model_request_failed"
        assert result.trace.output["provider_error_type"] == code
        assert result.trace.output["failure_category"] == "provider_failure"
        assert result.trace.output["task_completed"] is False
        assert result.trace.output["latency_ms"] == 17.5
        usage = result.trace.resource_usage
        assert usage.agent_llm_calls == 1 and usage.agent_llm_latency_ms == 17.5
        assert usage.active_runtime_ms == pytest.approx(25)
        assert usage.agent_total_tokens is None and usage.estimated_cost is None
        errors = [event for event in result.trace.events if event.kind == "error"]
        assert errors[-1].attributes["provider_error_type"] == code
        assert errors[-1].attributes["latency_ms"] == 17.5
        models = [event for event in result.trace.events if event.kind == "model.call"]
        assert len(models) == 1 and models[0].status == "error"
        assert models[0].attributes["provider_error_type"] == code
        evidence = target.export_business_evidence("session")
        observed = next(row for row in evidence.observations if row["kind"] == "model_failure")
        assert observed["data"]["provider_error_type"] == code and observed["data"]["latency_ms"] == 17.5
        llm_usage = [row for row in evidence.observations if row["kind"] == "llm_usage"]
        assert len(llm_usage) == 1 and llm_usage[0]["data"]["total_tokens"] is None
        assert not evidence.effects and not evidence.artifacts
        exported = result.model_dump_json() + evidence.model_dump_json()
        assert "PRIVATE_EXCEPTION_VALUE_DO_NOT_LOG" not in exported
        assert "PRIVATE_RESPONSE_VALUE_DO_NOT_LOG" not in exported
    finally:
        await target.reset("session")


@pytest.mark.asyncio
@pytest.mark.parametrize("latency", [None, -1, True, "SECRET_LATENCY_DO_NOT_LOG", float("nan"), float("inf")])
async def test_provider_failure_invalid_latency_uses_injected_clock(tmp_path, latency):
    from commerce_eval.providers import ProviderError
    clock = [0.0]
    async def complete(messages, tools):
        clock[0] += .037
        failure = ProviderError("provider_address_forbidden")
        failure.latency_ms = latency
        raise failure
    target = BusinessCandidateTarget(definition(), complete=complete, clock=lambda: clock[0],
        environment_factory=lambda selected: BusinessScenarioEnvironment(selected, tmp_path))
    selected = case("I01")
    target.bind_environment_cases([selected])
    try:
        result = await target.start(request(selected))
        assert result.trace.output["latency_ms"] == pytest.approx(37)
        assert result.trace.resource_usage.agent_llm_latency_ms == pytest.approx(37)
        assert "SECRET_LATENCY_DO_NOT_LOG" not in result.model_dump_json()
    finally:
        await target.reset("session")


@pytest.mark.asyncio
@pytest.mark.parametrize("known_type", [False, True])
async def test_unknown_exception_fields_cannot_impersonate_safe_provider_codes(tmp_path, known_type):
    from commerce_eval.providers import ProviderError
    failure = ProviderError("PRIVATE_CODE_DO_NOT_LOG") if known_type else RuntimeError("PRIVATE_EXCEPTION_DO_NOT_LOG")
    if not known_type:
        failure.code = "provider_address_forbidden"
        failure.latency_ms = 1234
    clock = [0.0]
    async def complete(messages, tools):
        clock[0] += .01
        raise failure
    target = BusinessCandidateTarget(definition(), complete=complete, clock=lambda: clock[0],
        environment_factory=lambda selected: BusinessScenarioEnvironment(selected, tmp_path))
    selected = case("I01")
    target.bind_environment_cases([selected])
    try:
        result = await target.start(request(selected))
        assert result.error_type == "model_request_failed"
        assert result.trace.output.get("provider_error_type") == ("provider_error" if known_type else None)
        assert result.trace.resource_usage.agent_llm_latency_ms == pytest.approx(10)
        dumped = result.model_dump_json() + target.export_business_evidence("session").model_dump_json()
        assert "PRIVATE_CODE_DO_NOT_LOG" not in dumped and "PRIVATE_EXCEPTION_DO_NOT_LOG" not in dumped
        if not known_type:
            assert "provider_address_forbidden" not in dumped
    finally:
        await target.reset("session")
