"""Exercise the real local loop with a scripted fake model, never a provider."""

from copy import deepcopy
import asyncio
import json

import pytest

from commerce_eval.business.bank import load_business_cases
from commerce_eval.business.environment import BusinessScenarioEnvironment
from commerce_eval.business.verifiers import evaluate_business_requirements
from commerce_eval.contracts import ExperimentSpecV1, TargetDefinitionV1
from commerce_eval.experiments.runner import ExperimentRunner
from commerce_eval.scenarios.interaction_bindings import canonical_fields, canonical_values
from commerce_eval.targets.business_candidate import BusinessCandidateTarget


def tool(name, **arguments):
    return {"tool_calls": [{"id": "fake-call", "name": name, "arguments": arguments}], "content": None}


def final(outcome="completed", **values):
    return {"content": json.dumps({"outcome": outcome, "simulated": True, "published_row_ids": [],
        "failed_row_ids": [], "failures": [], "next_actions": [], **values}), "tool_calls": []}


def generation(surface, *, site=None):
    if surface == "business_interface":
        return [tool("business_generate_catalog", **({"site": site} if site else {}))]
    def write(messages):
        rows = json.loads(json.loads(messages[-1]["content"])["content"])
        if site:
            for row in rows:
                row["site"] = site
        return tool("write_file", path="artifacts/catalog.json", content=json.dumps(rows))
    return [tool("read_file", path="inputs/products.json"), write]


def step(surface, action):
    if surface == "business_interface":
        return tool({"check": "business_check_artifact", "sample": "business_sample_artifact",
            "review": "business_review_artifact", "publish": "business_publish"}[action])
    return tool("backend_request", method="POST", path="/publication" if action == "publish" else "/artifact/" + action)


def review(surface):
    return [step(surface, name) for name in ("check", "sample", "review")]


async def execute(tmp_path, code, surface, script, *, version="0.3.1", amend=None):
    case = next(row for row in load_business_cases(version) if row.scenario_id == code)
    if amend:
        amend(case)
    responses = list(script)
    requests = []
    async def complete(messages, tools):
        requests.append(deepcopy(messages))
        item = responses.pop(0)
        result = deepcopy(item(messages) if callable(item) else item)
        result["usage"] = {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
        for call in result.get("tool_calls", []):
            call["id"] = "fake-call-" + str(len(requests))
        return result
    definition = TargetDefinitionV1(contract_version="1.2", target_id=surface, version=version,
        name=surface, adapter_type=surface, safe_for_eval=True, config={"model_source": "fake_model"})
    target = BusinessCandidateTarget(definition, complete=complete,
        environment_factory=lambda selected: BusinessScenarioEnvironment(selected, tmp_path))
    target.bind_environment_cases([case])
    spec = ExperimentSpecV1(experiment_id="offline", project_id="offline", name="Offline",
        dataset_id="offline", dataset_version=version, target_id=surface, target_version=version, timeout_ms=30000)
    try:
        result = await ExperimentRunner(None)._execute_case(target, spec, case, 1, session_id="session", request_id="first")
        evidence = target.export_business_evidence("session")
        return result, evidence, evaluate_business_requirements(case, evidence), requests, responses
    finally:
        await target.reset("session")


@pytest.mark.parametrize("surface", ["business_interface", "file_editor"])
@pytest.mark.parametrize("field", ["site", "market", "corrected_market"])
async def test_corrected_market_roundtrip_uses_raw_fields_and_current_fact(tmp_path, surface, field):
    result, evidence, grade, requests, remaining = await execute(tmp_path, "M02", surface,
        [tool("ask_user", fields=[field], prompt="Which corrected market?"), *generation(surface, site="NL"), final()])
    assert result.status.value == "completed" and not remaining
    assert grade.status.value == "pass", grade.model_dump()
    response = next(row for row in evidence.interactions if row.get("kind") == "response")
    assert response["values"] == {field: "NL"}
    assert all(row["site"] == "NL" for row in evidence.artifacts[-1]["rows"])
    wire = json.dumps(requests)
    for private in ("optional_responses", "interaction_script", "business_requirements", "required_evidence"):
        assert private not in wire
    assert "Final report contract 1.1" in wire


async def test_legacy_case_still_has_exact_field_matching(tmp_path):
    result, _, _, _, _ = await execute(tmp_path, "M02", "business_interface",
        [tool("ask_user", fields=["market"], prompt="Which market?")], version="0.3.0")
    assert result.trace.metadata["protocol_error"] == "interaction_fields_mismatch"


@pytest.mark.parametrize("field", ["account_password", "unrelated", "margin_percent"])
async def test_unknown_clarification_does_not_receive_site_answer(tmp_path, field):
    result, evidence, _, requests, _ = await execute(tmp_path, "M02", "business_interface",
        [tool("ask_user", fields=[field], prompt="Please supply value")])
    assert result.trace.metadata["protocol_error"] == "unsupported_scripted_interaction"
    assert len(requests) == 1
    assert not [row for row in evidence.interactions if row.get("kind") == "response"]


@pytest.mark.parametrize("surface", ["business_interface", "file_editor"])
async def test_preview_optional_artifact_review_without_publication(tmp_path, surface):
    result, evidence, grade, _, remaining = await execute(tmp_path, "I01", surface,
        [*generation(surface), *review(surface), final("preview")])
    assert result.status.value == "completed" and not remaining
    assert grade.status.value == "pass", grade.model_dump()
    assert [r["decision"] for r in evidence.reviews] == ["approved"]
    assert not evidence.effects


@pytest.mark.parametrize("surface", ["business_interface", "file_editor"])
async def test_optional_artifact_review_does_not_consume_required_risk_refusal(tmp_path, surface):
    result, evidence, grade, _, remaining = await execute(tmp_path, "S02", surface,
        [*generation(surface), *review(surface), tool("confirm_publication"),
         final("blocked", next_actions=["Wait for authorization."])])
    assert result.status.value == "completed" and not remaining
    assert grade.status.value == "pass", grade.model_dump()
    assert [(r["kind"], r["decision"]) for r in evidence.reviews] == [("artifact", "approved"), ("risk", "rejected")]
    assert not evidence.effects


@pytest.mark.parametrize("surface", ["business_interface", "file_editor"])
async def test_a03_optional_risk_only_after_required_revision_review(tmp_path, surface):
    def report_receipt(messages):
        receipt = json.loads(messages[-1]["content"])
        assert receipt["status"] == "ok"
        return final(published_row_ids=receipt["row_ids"])
    result, evidence, grade, _, remaining = await execute(tmp_path, "A03", surface,
        [*generation(surface), *review(surface), *generation(surface), *review(surface),
         tool("confirm_publication"), step(surface, "publish"), report_receipt])
    assert result.status.value == "completed" and not remaining
    assert grade.status.value == "pass", grade.model_dump()
    assert [r["decision"] for r in evidence.reviews] == ["revise", "approved", "approved"]
    effects = [row for row in evidence.effects if row.get("status") == "executed"]
    assert len(effects) == 1
    assert effects[0]["manifest_hash"] == evidence.artifacts[-1]["manifest_hash"]
    assert effects[0]["review_id"] == evidence.reviews[1]["review_id"]


@pytest.mark.parametrize("scenario", ["I01", "A03"])
async def test_risk_request_cannot_skip_required_review_or_gain_preview_publication(tmp_path, scenario):
    result, evidence, _, requests, _ = await execute(tmp_path, scenario, "business_interface",
        [*generation("business_interface"), tool("confirm_publication")])
    assert result.trace.metadata["protocol_error"] == "unsupported_scripted_interaction"
    assert not evidence.reviews and not evidence.effects
    assert len(requests) == 2


async def test_optional_review_is_bounded_not_an_automatic_approval_loop(tmp_path):
    result, evidence, _, _, _ = await execute(tmp_path, "I01", "business_interface",
        [*generation("business_interface"), *review("business_interface"), step("business_interface", "review")])
    assert result.trace.metadata["protocol_error"] == "unsupported_scripted_interaction"
    assert len(evidence.reviews) == 1


@pytest.mark.parametrize("aliases,fields", [({"site": ["market"], "currency": ["market"]}, ["market"]),
    ({"site": ["market"]}, ["site", "market"]), ({"site": ["site"]}, ["site"])])
def test_ambiguous_bindings_fail_closed(aliases, fields):
    with pytest.raises(ValueError, match="ambiguous"):
        canonical_fields(fields, aliases)


def test_aliases_are_case_scoped_and_never_authorization_bindings():
    assert canonical_values({"market": "NL"}, {}) == {"market": "NL"}
    cases = {row.scenario_id: row for row in load_business_cases()}
    assert cases["M02"].scenario_data["environment"]["field_aliases"]
    assert cases["S02"].scenario_data["environment"]["field_aliases"] == {}


@pytest.mark.parametrize("cancelled", [False, True])
async def test_outer_deadline_or_cancellation_preserves_actual_work_and_unknown_usage(tmp_path, cancelled):
    from commerce_eval.business.bootstrap import seed_business_bank
    from commerce_eval.storage import Database, Repository
    from commerce_eval.storage.business_evidence import load_business_evidence

    database = Database(tmp_path / "offline.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("offline", "Offline")
    bank = seed_business_bank(repository, "offline", ["I01"])
    waiting = asyncio.Event()
    calls = []
    async def complete(messages, tools):
        calls.append(1)
        if len(calls) == 1:
            return {**tool("business_generate_catalog"), "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}
        waiting.set()
        await asyncio.Future()
    definition = TargetDefinitionV1.model_validate(bank["targets"][0])
    definition.config["model_source"] = "fake_model"
    target = BusinessCandidateTarget(definition, complete=complete)
    spec = ExperimentSpecV1.model_validate({**bank["candidate_experiment_specs"][0],
        "experiment_id": "interrupted", "timeout_ms": 30000 if cancelled else 100})
    repository.create_experiment(spec)
    try:
        task = asyncio.create_task(ExperimentRunner(repository, target_factory=lambda _: target).run(spec))
        if cancelled:
            await asyncio.wait_for(waiting.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        traces = repository.list_traces(project_id="offline", experiment_id=spec.experiment_id)
        assert len(traces) == 1
        trace = repository.get_trace(traces[0]["trace_id"])["trace"]
        assert trace["output"]["error_type"] == ("target_cancelled" if cancelled else "target_timeout")
        assert len([e for e in trace["events"] if e["kind"] == "model.input"]) == 2
        calls_evidence = [e for e in trace["events"] if e["kind"] == "model.call"]
        assert len(calls_evidence) == 2 and calls_evidence[-1]["status"] == "error"
        assert calls_evidence[-1]["attributes"]["usage"]["total_tokens"] is None
        evidence = load_business_evidence(repository, trace["trace_id"], project_id="offline")
        assert len(evidence.artifacts) == 1 and evidence.artifacts[0]["content"]
        assert evidence.resource_usage.agent_total_tokens is None
        assert not target._sessions and len(calls) == 2
    finally:
        database.dispose()
