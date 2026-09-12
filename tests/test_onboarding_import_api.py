from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from commerce_eval.contracts import EvalCaseV1, TargetDefinitionV1, TraceEnvelopeV1


@pytest.fixture
def client(tmp_path, monkeypatch):
    from commerce_eval.api import create_app

    monkeypatch.setenv("AGENT_API_ENV_FILE", str(tmp_path / "disabled.env"))
    monkeypatch.delenv("COMMERCE_EVAL_API_TOKEN", raising=False)
    app = create_app(database_path=tmp_path / "api.db", static_dir=tmp_path / "missing")
    app.state.repository.create_project("p", "Project")
    with TestClient(app) as client:
        yield client
    app.state.database.dispose()


def test_fixed_json_upload_contract_and_download_templates(client):
    template = client.get("/api/v1/imports/templates", params={"kind": "trace"})
    assert template.status_code == 200
    assert set(template.json()) == {"filename", "content"}
    content = template.json()
    payload = {"project_id": "p", "kind": "trace", "files": [{"name": content["filename"], "content": content["content"]}], "options": {}}
    response = client.post("/api/v1/imports/preview", json=payload)
    assert response.status_code == 200, response.text
    ready = response.json()
    assert set(ready) == {"import_id", "status", "counts", "errors", "preview", "expires_at"}
    assert ready["status"] == "ready", ready
    assert client.get("/api/v1/traces").json()["items"] == []
    committed = client.post(f"/api/v1/imports/{ready['import_id']}/commit")
    assert committed.status_code == 200, committed.text
    trace_id = committed.json()["resources"][0]["trace_id"]
    detail = client.get(f"/api/v1/traces/{trace_id}").json()
    assert detail["overall_pass"] is None
    assert detail["evaluation_history"] == []
    download = client.get("/api/v1/imports/templates", params={"kind": "products", "download": True})
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.text.startswith("sku,")


def test_api_error_and_auth_never_echo_payload(client, monkeypatch):
    marker = "private-" + "request-marker"
    response = client.post("/api/v1/imports/preview", json={"project_id": marker, "kind": "bad", "files": []})
    assert response.status_code == 422 and marker not in response.text
    monkeypatch.setenv("COMMERCE_EVAL_API_TOKEN", marker)
    assert client.post("/api/v1/onboarding/check", json={"project_id": "p"}).status_code == 401
    assert client.get("/api/v1/imports/templates", params={"kind": "trace"},
                      headers={"Authorization": "Bearer " + marker}).status_code == 200


def test_public_target_registration_checks_both_entry_points(client, monkeypatch):
    target = {"target_id": "target", "version": "1", "name": "Target", "adapter_type": "python",
              "safe_for_eval": True, "config": {"command": ["$PYTHON", "-m", "commerce_eval.demo_runtime"]}}
    assert client.post("/api/v1/targets?project_id=p", json=target).status_code == 400
    assert client.post("/api/v1/onboarding/check", json={"project_id": "p", "definition": target}).status_code == 400
    target.update(adapter_type="http", config={"base_url": "http://127.0.0.1:9999", "credential_env": "TEST_HTTP_ENV"})
    response = client.post("/api/v1/targets?project_id=p", json=target)
    assert response.status_code == 201, response.text
    assert response.json()["config"]["token_env"] == "TEST_HTTP_ENV"
    monkeypatch.delenv("TEST_HTTP_ENV", raising=False)
    checked = client.post("/api/v1/onboarding/check", json={"project_id": "p", "definition": target})
    assert checked.status_code == 200
    assert checked.json()["executed"] is False
    assert checked.json()["checks"][0]["code"] == "credential_reference_unavailable"
    assert not client.get("/api/v1/experiments").json()["items"]


def test_explicit_evaluation_api_preserves_history(client):
    repository = client.app.state.repository
    repository.save_trace(TraceEnvelopeV1(trace_id="trace", project_id="p", target_id="t", target_version="1"))
    repository.save_tool_contract_set("p", "tools", "1", [])
    repository.save_evaluator_set("p", "evaluators", "1", ["task_completion"])
    repository.save_dataset("p", "dataset", "1", "Dataset", [EvalCaseV1(case_id="case", name="Case")])
    body = {"trace_id": "trace", "dataset_id": "dataset", "dataset_version": "1", "case_id": "case",
            "tool_contract_set_id": "tools", "tool_contract_version": "1", "evaluator_set_id": "evaluators", "evaluator_set_version": "1"}
    first = client.post("/api/v1/evaluations", json=body)
    assert first.status_code == 201, first.text
    second = client.post("/api/v1/evaluations", json=body)
    assert second.status_code == 201, second.text
    assert first.json()["evaluation_id"] != second.json()["evaluation_id"]
    assert len(client.get("/api/v1/traces/trace").json()["evaluation_history"]) == 2
    assert client.get("/api/v1/evaluations/" + first.json()["evaluation_id"]).json() == first.json()


def test_scenario_selection_is_one_dataset_or_no_dataset(client):
    templates = client.get("/api/v1/scenario-templates")
    assert templates.status_code == 200, templates.text
    ids = [item["scenario_id"] for item in templates.json()["items"][:2]]
    body = {"project_id": "p", "dataset_id": "selected", "version": "1", "template_ids": ids}
    bad = client.post("/api/v1/scenario-templates/bank/instantiate", json={**body, "template_ids": [*ids, "missing"]})
    assert bad.status_code == 200, bad.text
    assert bad.json()["readiness"]["ready"] is False
    assert client.get("/api/v1/datasets").json()["items"] == []
    ready = client.post("/api/v1/scenario-templates/bank/instantiate", json=body)
    assert ready.status_code == 200, ready.text
    assert ready.json()["readiness"]["ready"] is True
    assert ready.json()["case_count"] == 2
    assert len(client.get("/api/v1/datasets").json()["items"]) == 1
    assert client.post("/api/v1/scenario-templates/bank/instantiate", json=body).status_code == 200
    assert not client.get("/api/v1/experiments").json()["items"]
