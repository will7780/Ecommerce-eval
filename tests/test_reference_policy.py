"""Independent no-key baseline: only public intent and actual feedback drive calls."""

from copy import deepcopy
import json

import pytest

from commerce_eval.contracts import (
    EvalCaseV1, ExperimentSpecV1, TargetDefinitionV1, TargetResumeRequestV1, TargetRunRequestV1,
)
from commerce_eval.experiments.runner import ExperimentRunner, merge_turn_traces
from commerce_eval.scenarios import project_candidate_input, product_rows
from commerce_eval.targets import build_target
from commerce_eval.targets.base import candidate_case


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_API_ENV_FILE", str(tmp_path / "disabled.env"))


def definition():
    return TargetDefinitionV1(
        target_id="public-policy", version="0.2.0", name="Deterministic Public Policy (Simulated)",
        adapter_type="reference_policy", safe_for_eval=True,
        config={"project_id": "policy-project", "execution_mode": "dry_run", "max_steps": 24},
    )


def sandbox_case(message="Preview the Harbor catalog.", *, capabilities=None, script=None, facts=None, environment=None):
    capabilities = capabilities or ["catalog.read", "catalog.preview", "catalog.publish"]
    facts = {"store": "harbor"} if facts is None else facts
    rows = product_rows("clean")
    rules = [{"scope": {"store": "harbor"}, "version": "policy-1", "priority": 1, "text": "Only synthetic catalog data.",
              "policy": {"rule_version": "policy-1", "currency": "EUR", "minimum_margin_percent": 15}}]
    return EvalCaseV1(
        case_id="public-task", name="Public task", scenario_id="custom-sandbox",
        input={"message": message, "assets": [
            {"asset_id": "products", "permitted": True, "rows": rows},
            {"asset_id": "rules", "permitted": True, "content": rules},
            {"asset_id": "task", "permitted": True, "content": {"facts": facts}},
        ]},
        capability_bindings=[{"capability_id": capability, "tool_id": "vendor." + capability} for capability in capabilities],
        scenario_data={
            "initial_data": {"products": rows, "facts": facts, "suggested_prices": {},
                             "unit_costs": {row["row_id"]: round(row["price"] * 0.75, 2) for row in rows}},
            "rules": rules, "environment": {"healthy": True, **(environment or {})},
            "interaction_script": script or [], "references": {"positive": [{"capability": "catalog.publish", "arguments": {}}]},
        },
    )


def request(case, *, identifier="policy-run", session="session"):
    return TargetRunRequestV1(request_id=identifier, session_id=session, case=candidate_case(case),
                              execution_mode="dry_run", timeout_ms=30000)


def calls(trace):
    return [(row.attributes["tool_id"], row.attributes["arguments"]) for row in trace.events if row.kind == "tool.call"]


def resume_request(started, value, *, identifier="resume", interaction_id=None):
    return TargetResumeRequestV1(
        request_id=identifier, session_id="session", external_run_id=started.external_run_id,
        interaction_id=interaction_id or started.pending_interaction.interaction_id, response=value, timeout_ms=30000,
    )


@pytest.mark.asyncio
async def test_policy_trajectory_ignores_poisoned_evaluator_material():
    original = sandbox_case()
    poison = original.model_copy(deep=True)
    poison.name = "POISON_NAME"
    poison.scenario_id = "POISON_SCENARIO"
    poison.expected_tools = ["POISON_EXPECTATION"]
    poison.forbidden_tools = ["vendor.catalog.read", "vendor.catalog.preview"]
    poison.outcome_assertions = {"POISON_OUTCOME": True}
    poison.behavior_assertions = [{"type": "POISON_BEHAVIOR"}]
    poison.scenario_data["references"] = {"positive": "POISON_PLAN", "answers": "POISON_ANSWERS"}
    poison.scenario_data["interaction_script"] = [{"type": "confirmation", "response": {"decision": "POISON_FUTURE"}}]
    outputs = []
    for case in (original, poison):
        target = build_target(definition())
        target.bind_environment_cases([case])
        try:
            output = await target.start(request(case))
            assert output.status.value == "completed"
            assert "POISON" not in json.dumps(target._sessions["session"].policy.__dict__, default=str)
            assert "POISON" not in output.trace.model_dump_json()
            assert output.trace.metadata["actor"] == "reference_policy"
            assert output.trace.metadata["reference_fixture"] is False
            assert output.trace.resource_usage.agent_llm_calls == 0
            assert not any(row.kind == "model.call" for row in output.trace.events)
            outputs.append(calls(output.trace))
        finally:
            await target.reset("session")
    assert outputs[0] == outputs[1]
    assert [tool for tool, _ in outputs[0]] == ["vendor.catalog.read", "vendor.catalog.preview"]


@pytest.mark.asyncio
async def test_policy_unknown_public_intent_honestly_fails():
    case = sandbox_case("Compose a sonata.")
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        output = await target.start(request(case))
        assert output.status.value == "failed"
        assert output.trace.output["task_completed"] is False
        assert output.trace.output["reason_code"] == "unsupported_public_intent"
        assert calls(output.trace) == []
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_policy_clarification_uses_exact_pending_id_and_actual_response():
    case = sandbox_case(
        "Ask which store before reading a catalog preview.",
        capabilities=["interaction.ask", "catalog.read", "catalog.preview"],
        facts={"store": None},
        script=[{"type": "clarification", "fields": ["store"], "response": {"store": "harbor"}}],
    )
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        started = await target.start(request(case))
        assert started.status.value == "awaiting_input"
        assert started.pending_interaction.required_fields == ["store"]
        invalid = await target.resume(resume_request(started, {"store": "harbor"}, interaction_id="unrelated"))
        assert invalid.status.value == "failed"
        assert calls(invalid.trace) == []
        resumed = await target.resume(resume_request(started, {"store": "harbor"}, identifier="accepted"))
        assert resumed.status.value == "completed"
        assert resumed.external_run_id == started.external_run_id
        assert calls(resumed.trace)[0][1]["store"] == "harbor"
        assert [tool for tool, _ in calls(resumed.trace)] == ["vendor.catalog.read", "vendor.catalog.preview"]
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_policy_rejection_never_prepares_or_publishes():
    case = sandbox_case(
        "Ask whether to publish Harbor catalog.",
        capabilities=["interaction.ask", "artifact.prepare", "catalog.publish"],
        script=[{"type": "confirmation", "fields": ["publish"], "response": {"decision": "rejected"}}],
    )
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        started = await target.start(request(case))
        assert started.status.value == "awaiting_confirmation"
        resumed = await target.resume(resume_request(started, {"decision": "rejected"}))
        assert resumed.trace.output["outcome"] == "cancelled"
        assert resumed.trace.output["task_completed"] is False
        assert calls(resumed.trace) == []
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_policy_preparation_failure_never_claims_or_attempts_publication():
    case = sandbox_case(
        "Prepare a catalog and publish after review.",
        capabilities=["artifact.prepare", "artifact.check", "artifact.sample", "artifact.review", "catalog.publish"],
        environment={"healthy": False},
    )
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        result = await target.start(request(case))
        assert result.trace.output["outcome"] == "blocked"
        assert result.trace.output["task_completed"] is False
        assert [tool for tool, _ in calls(result.trace)] == ["vendor.artifact.prepare"]
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_policy_publication_is_bound_to_observed_artifact_and_resume_does_not_replay():
    from commerce_eval.contracts import EvaluationContext
    from commerce_eval.packs.core import tool_confirmation_compliance
    from commerce_eval.scenarios import build_tool_contracts
    case = sandbox_case(
        "Prepare a catalog, validate and review it, then publish in the sandbox.",
        capabilities=["artifact.prepare", "artifact.check", "artifact.sample", "artifact.review", "catalog.publish"],
        script=[{"type": "artifact_review", "response": {"decision": "approved"}}],
    )
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        started = await target.start(request(case))
        assert started.pending_interaction.confirmation_kind == "artifact"
        assert started.pending_interaction.parameter_snapshot_hash
        resumed = await target.resume(resume_request(started, {"decision": "approved"}))
        assert resumed.status.value == "completed"
        assert [tool for tool, _ in calls(resumed.trace)] == ["vendor.catalog.publish"]
        combined = merge_turn_traces([started.trace, resumed.trace])
        context = EvaluationContext(case=case, trace=combined, prior_results={},
                                    tool_contracts={tool.tool_id: tool for tool in build_tool_contracts(case)})
        assert tool_confirmation_compliance(context).value == 1.0
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_policy_replans_only_from_actual_failure_observation():
    case = sandbox_case(
        "Preview Harbor catalog and recover using the supported mirror if the primary fails.",
        capabilities=["catalog.read", "workflow.plan", "catalog.search", "catalog.preview"],
        environment={"primary_failure": True},
    )
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        result = await target.start(request(case))
        assert result.trace.output["task_completed"] is True
        assert [tool for tool, _ in calls(result.trace)] == [
            "vendor.catalog.read", "vendor.catalog.search", "vendor.catalog.preview",
        ]
        assert calls(result.trace)[1][1]["source"] == "mirror"
        decision = next(event for event in result.trace.events
                        if event.kind == "model.decision" and event.attributes["tool_id"] == "vendor.catalog.search")
        assert decision.attributes["source"] == "reference_policy"
        assert decision.attributes["decision_type"] == "deterministic_policy"
        receipt = next(event for event in result.trace.events if event.event_id == decision.attributes["observation_id"])
        assert receipt.kind == "observation" and receipt.status.value == "error"
        assert decision.evidence_refs == [receipt.event_id]
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_policy_all_32_bank_runs_are_no_key_ordinary_evaluations_with_honest_failures(tmp_path):
    from commerce_eval.demo import seed_onboarding_demo
    from commerce_eval.storage import Database, Repository
    database = Database(tmp_path / "policy-bank.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("policy-project", "Policy baseline")
    refs = seed_onboarding_demo(repository, "policy-project")
    spec = ExperimentSpecV1.model_validate({
        **refs["policy_experiment_spec"], "experiment_id": "independent-policy-bank",
    })
    registered = repository.get_target(spec.project_id, spec.target_id, spec.target_version)
    assert registered.adapter_type == "reference_policy"
    assert registered.config["max_steps"] == 32
    repository.create_experiment(spec)
    try:
        result = await ExperimentRunner(repository).run(spec)
        assert result["completed_runs"] == 32
        rows = repository.list_traces(experiment_id=spec.experiment_id)
        assert len(rows) == 32
        verdicts = []
        for row in rows:
            stored = repository.get_trace(row["trace_id"])
            assert stored["trace"]["metadata"]["actor"] == "reference_policy"
            assert stored["trace"]["metadata"]["reference_fixture"] is False
            assert stored["trace"]["resource_usage"]["agent_llm_calls"] == 0
            assert len(stored["evaluation_history"]) == 1
            verdicts.append(stored["evaluation_history"][0]["overall_pass"])
        assert any(verdicts)
        assert not all(verdicts)
    finally:
        database.dispose()


GENERATION = ["catalog.generate_listing", "artifact.check", "artifact.sample", "artifact.review", "catalog.publish"]


@pytest.mark.asyncio
async def test_policy_missing_file_asks_before_generation_and_pending_blocks_start():
    case = sandbox_case(
        "Generate the Harbor catalog preview from an input file.",
        capabilities=["interaction.ask", "catalog.generate_listing", "catalog.preview"],
        environment={"input_file_missing": True},
        script=[{"type": "clarification", "fields": ["input_file"], "response": {"input_file": "products"}}],
    )
    case.input["assets"][0]["permitted"] = False
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        started = await target.start(request(case))
        assert started.pending_interaction.required_fields == ["input_file"]
        assert [tool for tool, _ in calls(started.trace)] == ["vendor.interaction.ask"]
        rejected = await target.start(request(case, identifier="forbidden-start"))
        assert rejected.status.value == "failed"
        assert calls(rejected.trace) == []
        resumed = await target.resume(resume_request(started, {"input_file": "products"}))
        assert resumed.trace.output["task_completed"] is True
        assert [tool for tool, _ in calls(resumed.trace)] == ["vendor.catalog.generate_listing", "vendor.catalog.preview"]
        assert calls(resumed.trace)[0][1]["input_file"] == "products"
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_policy_generate_publish_audit_uses_observed_binding_and_actual_mapped_names():
    case = sandbox_case(
        "Generate Harbor catalog with an 18% margin, validate and review, publish, then audit at 18%.",
        capabilities=GENERATION + ["pricing.audit_margin"],
        script=[{"type": "artifact_review", "response": {"decision": "approved"}}],
    )
    for binding in case.capability_bindings:
        if binding["capability_id"] == "catalog.generate_listing":
            binding.update(argument_mapping={"input_file": "/source/file", "store": "/scope/company",
                                              "margin_percent": "/pricing/rate"},
                           unit_scale={"margin_percent": 0.01})
        if binding["capability_id"] == "pricing.audit_margin":
            binding.update(argument_mapping={"threshold_percent": "/floor/rate"},
                           unit_scale={"threshold_percent": 0.01})
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        started = await target.start(request(case))
        first = calls(started.trace)[0]
        assert first[0] == "vendor.catalog.generate_listing"
        assert first[1]["source"]["file"] == "products"
        assert first[1]["pricing"]["rate"] == pytest.approx(0.18)
        resumed = await target.resume(resume_request(started, {"decision": "approved"}))
        assert resumed.trace.output["task_completed"] is True
        publish, audit = calls(resumed.trace)
        assert publish[0] == "vendor.catalog.publish"
        assert audit[0] == "vendor.pricing.audit_margin"
        assert audit[1]["artifact_id"] == publish[1]["artifact_id"]
        assert audit[1]["version"] == publish[1]["version"]
        assert audit[1]["floor"]["rate"] == pytest.approx(0.18)
        assert started.pending_interaction.tool_call_id in [row.event_id for row in resumed.trace.events]
    finally:
        await target.reset("session")


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", [{"generation_failure": True}, {"generation_outcome": "empty"}, {"generation_outcome": "simulated"}])
async def test_policy_no_successful_artifact_means_no_publish(environment):
    case = sandbox_case(
        "Generate the Harbor catalog, review and publish it.", capabilities=GENERATION, environment=environment,
    )
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        result = await target.start(request(case))
        assert result.trace.output["task_completed"] is False
        assert result.trace.output["outcome"] == "blocked"
        assert [tool for tool, _ in calls(result.trace)] == ["vendor.catalog.generate_listing"]
        assert not result.pending_interaction
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_policy_ambiguous_export_timeout_queries_status_without_retry():
    case = sandbox_case(
        "Export Harbor catalog. An ambiguous timeout requires a status check.",
        capabilities=["catalog.read", "catalog.export", "job.status"],
        environment={"export_timeout": True},
    )
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        result = await target.start(request(case))
        assert result.trace.output["task_completed"] is True
        assert [tool for tool, _ in calls(result.trace)] == ["vendor.catalog.read", "vendor.catalog.export", "vendor.job.status"]
        assert calls(result.trace)[1][1] == calls(result.trace)[2][1]
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_policy_never_selects_expired_or_other_company_rules():
    case = sandbox_case("Generate Harbor catalog under company rules.", capabilities=["rules.read", "catalog.generate_listing"])
    rules = case.scenario_data["rules"]
    rules.extend([
        {**deepcopy(rules[0]), "status": "expired", "priority": 999,
         "policy": {"rule_version": "expired-rule", "currency": "USD"}},
        {**deepcopy(rules[0]), "scope": {"store": "elsewhere"}, "priority": 999,
         "policy": {"rule_version": "other-company-rule", "currency": "USD"}},
    ])
    case.input["assets"][1]["content"] = deepcopy(rules)
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        result = await target.start(request(case))
        assert result.trace.output["task_completed"] is True
        assert calls(result.trace)[-1][1]["rule_version"] == "policy-1"
    finally:
        await target.reset("session")


@pytest.mark.asyncio
async def test_policy_unsupported_catalog_workflow_does_not_claim_completion():
    case = sandbox_case("Translate the catalog into French.")
    target = build_target(definition())
    target.bind_environment_cases([case])
    try:
        result = await target.start(request(case))
        assert result.status.value == "failed"
        assert result.trace.output["task_completed"] is False
        assert calls(result.trace) == []
    finally:
        await target.reset("session")
