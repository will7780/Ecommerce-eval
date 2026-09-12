from datetime import datetime, timezone
import json

import pytest
from pydantic import ValidationError

from commerce_eval.contracts import (
    BusinessEvidenceBundleV1, BusinessRequirementV1, EvalCaseV1, ExperimentSpecV1,
    ToolContractV1, TraceEnvelopeV1,
)
from commerce_eval.core import EvaluationEngine
from commerce_eval.storage import Database, Repository
from commerce_eval.storage.business_evidence import load_business_evidence, save_collected_business_evidence
from commerce_eval.targets.base import candidate_case, candidate_request_payload


def _trace():
    return TraceEnvelopeV1(contract_version="1.2", trace_id="t", project_id="p",
                           target_id="candidate", target_version="1",
                           output={"success": True}, metadata={"trusted": True, "complete": True})


def _bundle():
    now = datetime.now(timezone.utc)
    return BusinessEvidenceBundleV1(run_id="session", project_id="p", company_id="fictional",
                                   collector_id="sandbox-v1", started_at=now, ended_at=now, complete=True)


def _repository(tmp_path):
    database = Database(tmp_path / "platform.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("p", "Synthetic")
    repository.save_trace(_trace())
    return repository


def test_contract_v12_preserves_raw_tool_name_and_legacy_dotted_validation():
    assert ToolContractV1(contract_version="1.2", tool_id="write_file", version="1", title="Write").tool_id == "write_file"
    with pytest.raises(ValidationError):
        ToolContractV1(tool_id="write_file", version="1", title="Write")
    old = EvalCaseV1(case_id="old", name="Old")
    assert "business_requirements" not in old.model_dump()
    assert EvalCaseV1.model_validate_json(old.model_dump_json()) == old


def test_missing_evidence_cannot_be_satisfied_by_self_report():
    case = EvalCaseV1(contract_version="1.2", case_id="business", name="Business", business_requirements=[
        BusinessRequirementV1(requirement_id="no-side-effect", verifier_id="side_effects", expected={"allowed_actions": []})
    ])
    result = EvaluationEngine([]).evaluate(case, _trace())
    assert result.overall_pass is False
    assert "business_acceptance_pass" in result.gate_failures[0]
    metric = next(item for item in result.metric_results if item.metric_id == "business_acceptance_pass")
    assert metric.status.value == "error"


def test_business_answer_projection_does_not_expose_requirements():
    case = EvalCaseV1(contract_version="1.2", case_id="private", name="Private",
        input={"message": "Generate a preview", "business_requirements": [{"expected": "PRIVATE_ANSWER"}]},
        business_requirements=[BusinessRequirementV1(requirement_id="private", verifier_id="artifact",
                                                     expected={"marker": "PRIVATE_ANSWER"})])
    projected = candidate_case(case)
    assert projected.business_requirements == []
    assert "PRIVATE_ANSWER" not in projected.model_dump_json()


def test_provider_pin_requires_full_snapshot_and_preserves_old_spec_serialization():
    base = dict(experiment_id="e", project_id="p", name="Experiment", dataset_id="d",
                dataset_version="1", target_id="c", target_version="1")
    assert "allow_paid" not in ExperimentSpecV1(**base).model_dump()
    with pytest.raises(ValidationError):
        ExperimentSpecV1(**base, contract_version="1.2", provider_id="custom")
    new = ExperimentSpecV1(**base, contract_version="1.2", provider_id="custom",
                           provider_version="1", model="model", allow_paid=True)
    assert ExperimentSpecV1.model_validate_json(new.model_dump_json()) == new


def test_evidence_is_immutable_scope_pinned_and_survives_restart(tmp_path):
    repository = _repository(tmp_path)
    bundle = _bundle()
    save_collected_business_evidence(repository, "t", bundle, session_id="session", project_id="p", collector_id="sandbox-v1")
    repository.database.dispose()
    reopened = Database(tmp_path / "platform.db")
    reopened.initialize()
    repository = Repository(reopened)
    assert load_business_evidence(repository, "t", project_id="p") == bundle
    with pytest.raises(ValueError, match="scope_mismatch"):
        save_collected_business_evidence(repository, "t", bundle, session_id="other", project_id="p", collector_id="sandbox-v1")
    with pytest.raises(ValueError, match="immutable_conflict"):
        save_collected_business_evidence(repository, "t", bundle.model_copy(update={"complete": False}),
                                         session_id="session", project_id="p", collector_id="sandbox-v1")
    with pytest.raises(ValueError, match="integrity"):
        load_business_evidence(repository, "t", project_id="other")
    reopened.dispose()


def test_redacted_evidence_is_not_claimed_complete(tmp_path):
    repository = _repository(tmp_path)
    bundle = _bundle().model_copy(update={"report": {"api_key": "PRIVATE_FIXTURE", "chain_of_thought": "HIDDEN_FIXTURE"}})
    stored = save_collected_business_evidence(repository, "t", bundle, session_id="session", project_id="p", collector_id="sandbox-v1")
    assert stored.complete is False
    assert "evidence_redacted_or_truncated" in stored.omission_reasons
    assert "PRIVATE_FIXTURE" not in stored.model_dump_json()
    assert "HIDDEN_FIXTURE" not in stored.model_dump_json()
    repository.database.dispose()


def test_imported_trust_flag_cannot_create_harness_evidence_or_pass(tmp_path):
    from fastapi.testclient import TestClient
    from commerce_eval.api import create_app
    from commerce_eval.business.bootstrap import seed_business_bank

    app = create_app(database_path=tmp_path / "import.db")
    repository = app.state.repository
    repository.create_project("p", "Synthetic")
    bank = seed_business_bank(repository, "p", ["I01"])
    imported = _trace().model_copy(update={"metadata": {
        "trusted": True, "collector_id": "builtin-business-environment-v1",
        "business_evidence": _bundle().model_dump(mode="json"),
    }})
    with TestClient(app) as client:
        assert client.post("/api/v1/traces", json=imported.model_dump(mode="json")).status_code == 201
        assert client.get("/api/v1/traces/t").json()["business_evidence"] is None
        result = client.post("/api/v1/evaluations", json={
            "trace_id": "t", "project_id": "p", "dataset_id": bank["dataset_id"],
            "dataset_version": bank["dataset_version"], "case_id": "public-I01",
            "tool_contract_set_id": bank["tool_contract_set_id"], "tool_contract_version": bank["tool_contract_version"],
            "evaluator_set_id": bank["evaluator_set_id"], "evaluator_set_version": bank["evaluator_set_version"],
        })
        assert result.status_code == 201
        assert "evidence_missing" in result.text
        assert result.json()["overall_pass"] is False
    app.state.database.dispose()


def test_business_compilation_does_not_depend_on_tool_spelling():
    from commerce_eval.business.bank import load_business_templates
    from commerce_eval.scenarios import compile_scenario

    template = load_business_templates()[0]
    left = compile_scenario(template, [{"capability_id": "anything", "tool_id": "suite.Generate"}])
    right = compile_scenario(template, [{"capability_id": "anything", "tool_id": "write_file"}])
    assert left == right
    assert left.contract_version == "1.2"
    assert left.business_requirements
    assert left.required_sequence == []


@pytest.mark.asyncio
async def test_business_onboarding_checks_evidence_not_identical_tool_names(tmp_path):
    from commerce_eval.business.bootstrap import seed_business_bank
    from commerce_eval.services.onboarding import OnboardingService

    repository = _repository(tmp_path)
    bank = seed_business_bank(repository, "p", ["I01"])
    for target in bank["targets"]:
        result = await OnboardingService(repository).check(
            "p", target["target_id"], target["version"], dataset_id=bank["dataset_id"], dataset_version=bank["dataset_version"])
        assert result["business_readiness"]["ready"] is True
        assert result["business_readiness"]["tool_name_matching_required"] is False
        assert result["executed"] is False
    repository.database.dispose()


@pytest.mark.asyncio
async def test_runner_persists_collected_files_before_reset_and_regrades(tmp_path):
    from commerce_eval.business.bootstrap import seed_business_bank
    from commerce_eval.experiments import ExperimentRunner
    from commerce_eval.services.evaluations import EvaluationService
    from commerce_eval.targets.business_candidate import BusinessCandidateTarget

    repository = _repository(tmp_path)
    bank = seed_business_bank(repository, "p", ["I01"])
    calls = 0

    async def complete(messages, tools):
        nonlocal calls
        calls += 1
        assert "business_requirements" not in json.dumps(messages)
        if calls == 1:
            return {"content": None, "tool_calls": [{"id": "generate-1", "name": "business_generate_catalog", "arguments": {}}],
                    "usage": {}, "latency_ms": 1}
        return {"content": json.dumps({"outcome": "completed", "simulated": True, "published_row_ids": []}),
                "tool_calls": [], "usage": {}, "latency_ms": 1}

    class RecordingTarget(BusinessCandidateTarget):
        async def reset(self, session_id):
            traces = repository.list_traces(project_id="p", experiment_id="integration-business")
            assert len(traces) == 1
            saved = load_business_evidence(repository, traces[0]["trace_id"], project_id="p")
            assert saved is not None and saved.artifacts
            await super().reset(session_id)

    target = RecordingTarget(repository.get_target("p", bank["target_id"], bank["target_version"]), complete=complete)
    spec = ExperimentSpecV1.model_validate({**bank["experiment_spec"], "experiment_id": "integration-business"})
    repository.create_experiment(spec)
    result = await ExperimentRunner(repository, target_factory=lambda definition: target).run(spec)
    assert result["status"] == "completed"
    assert target._sessions == {}
    traces = repository.list_traces(project_id="p", experiment_id=spec.experiment_id)
    detail = repository.get_trace(traces[0]["trace_id"])
    business = next(row for row in detail["metrics"] if row["metric_id"] == "business_acceptance_pass")
    assert business["status"] == "pass", business
    reevaluated = EvaluationService(repository).evaluate(traces[0]["trace_id"], project_id="p",
        dataset_id=bank["dataset_id"], dataset_version=bank["dataset_version"], case_id="public-I01",
        tool_contract_set_id=bank["tool_contract_set_id"], tool_contract_version=bank["tool_contract_version"],
        evaluator_set_id=bank["evaluator_set_id"], evaluator_set_version=bank["evaluator_set_version"])
    assert reevaluated["overall_pass"] is True
    assert calls == 2
    repository.database.dispose()


def test_paid_retry_requires_fresh_approval_origin_and_valid_pin(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from commerce_eval.api import create_app
    from commerce_eval.business.bootstrap import seed_business_bank

    app = create_app(database_path=tmp_path / "retry.db")
    repository = app.state.repository
    repository.create_project("p", "Synthetic")
    bank = seed_business_bank(repository, "p", ["I01"])
    spec = ExperimentSpecV1.model_validate({**bank["experiment_spec"], "experiment_id": "paid-original",
        "provider_id": "not-configured", "provider_version": "1", "model": "offline-fixture", "allow_paid": True})
    repository.create_experiment(spec)
    repository.update_experiment(spec.experiment_id, status="completed")
    starts = []
    monkeypatch.setattr(app.state.experiment_manager, "start", lambda value: starts.append(value))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        url = f"/api/v1/experiments/{spec.experiment_id}/retry"
        assert client.post(url, json={"allow_paid": True}).status_code == 403
        headers = {"Origin": "http://127.0.0.1"}
        assert client.post(url, headers=headers).status_code == 400
        assert client.post(url, headers=headers, json={"allow_paid": False}).status_code == 400
        assert client.post(url, headers=headers, json={"allow_paid": "true"}).status_code == 422
        assert client.post(url, headers=headers, json={"allow_paid": True}).status_code == 404
        assert len(repository.list_experiments(project_id="p")) == 1
        assert starts == []
    app.state.database.dispose()
