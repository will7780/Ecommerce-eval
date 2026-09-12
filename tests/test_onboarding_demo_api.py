from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from commerce_eval.api import create_app
from commerce_eval.contracts import TargetDefinitionV1, TraceEnvelopeV1


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_API_ENV_FILE", str(tmp_path / "disabled.env"))
    monkeypatch.delenv("COMMERCE_EVAL_API_TOKEN", raising=False)
    app = create_app(database_path=tmp_path / "demo.db", static_dir=tmp_path / "absent")
    app.state.repository.create_project("p", "Project")
    with TestClient(app) as client:
        yield client
    app.state.database.dispose()


def test_demo_refs_are_idempotent_and_do_not_start_experiments(client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("onboarding must never start an experiment")

    monkeypatch.setattr(client.app.state.experiment_manager, "start", forbidden)
    response = client.post("/api/v1/onboarding/demo", json={"project_id": "p", "template_ids": ["I01", "I02"]})
    assert response.status_code == 200, response.text
    refs = response.json()
    assert refs["status"] == "ready" and refs["readiness"]["ready"] is True
    assert refs["case_count"] == 2
    assert refs["candidate_evaluation"] is False
    assert refs["evaluator_set_version"] == "0.2.0"
    spec = refs["experiment_spec"]
    assert spec["dataset_id"] == refs["dataset_id"]
    repository = client.app.state.repository
    target = repository.get_target("p", refs["target_id"], refs["target_version"])
    assert target.adapter_type == "reference_fixture" and target.safe_for_eval is True
    again = client.post("/api/v1/onboarding/demo", json={"project_id": "p", "template_ids": ["I02", "I01"]})
    assert again.status_code == 200, again.text
    assert again.json() == refs
    assert repository.list_experiments() == repository.list_traces() == []
    checked = client.post("/api/v1/onboarding/check", json={"project_id": "p", "target_id": refs["target_id"], "target_version": refs["target_version"]})
    assert checked.status_code == 200 and checked.json()["status"] == "ready"
    assert checked.json()["executed"] is False


def test_demo_late_conflict_rolls_back_dataset_and_sets(client):
    repository = client.app.state.repository
    repository.save_target("p", TargetDefinitionV1(target_id="standard-reference-fixtures", version="0.2.0",
                             name="Already registered different target", adapter_type="http", safe_for_eval=True,
                             config={"base_url": "http://127.0.0.1:9000"}))
    response = client.post("/api/v1/onboarding/demo", json={"project_id": "p", "template_ids": ["I01"]})
    assert response.status_code == 409, response.text
    assert repository.list_datasets("p") == []
    assert repository.list_tool_contract_sets("p") == []
    assert repository.list_evaluator_sets("p") == []
    assert repository.list_experiments() == []


def test_reference_fixture_cannot_be_explicitly_graded_as_candidate(client):
    refs = client.post("/api/v1/onboarding/demo", json={"project_id": "p", "template_ids": ["I01"]}).json()
    repository = client.app.state.repository
    repository.save_trace(TraceEnvelopeV1(trace_id="reference", project_id="p", target_id=refs["target_id"],
                                          target_version=refs["target_version"]))
    body = {key: refs[key] for key in ("project_id", "dataset_id", "dataset_version", "tool_contract_set_id",
                                     "tool_contract_version", "evaluator_set_id", "evaluator_set_version")}
    case = repository.get_dataset("p", refs["dataset_id"], refs["dataset_version"])["cases"][0]
    response = client.post("/api/v1/evaluations", json={**body, "trace_id": "reference", "case_id": case["case_id"]})
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "reference_fixture_not_candidate"
    assert repository.get_trace("reference")["evaluation_history"] == []
