from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from commerce_eval.api import create_app

    monkeypatch.setenv("AGENT_API_ENV_FILE", str(tmp_path / "disabled.env"))
    monkeypatch.delenv("COMMERCE_EVAL_API_TOKEN", raising=False)
    app = create_app(database_path=tmp_path / "api.db", static_dir=tmp_path / "missing")
    app.state.repository.create_project("first", "First project")
    app.state.repository.create_project("second", "Second project")
    with TestClient(app) as test_client:
        yield test_client
    app.state.database.dispose()


@pytest.mark.parametrize(
    ("kind", "listing", "items_key"),
    [
        ("trace", "traces", "items"),
        ("dataset", "datasets", "items"),
        ("tool-contracts", "tool-contracts", "items"),
        ("products", None, None),
        ("rules", None, None),
        ("target", "targets", "items"),
        ("evaluator-set", "evaluators", "sets"),
    ],
)
def test_commit_stays_in_preview_project_after_project_switch(client, kind, listing, items_key):
    template_response = client.get("/api/v1/imports/templates", params={"kind": kind})
    assert template_response.status_code == 200
    template = template_response.json()
    response = client.post(
        "/api/v1/imports/preview",
        json={
            "project_id": "first",
            "kind": kind,
            "files": [{"name": template["filename"], "content": template["content"]}],
            "options": {"id": "shared", "version": "1"},
        },
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["status"] == "ready", preview

    # Simulate project-scoped reads after back/forward navigation and selection.
    for project_id in ("second", "first", "second"):
        scoped = client.get("/api/v1/datasets", params={"project_id": project_id})
        assert scoped.status_code == 200
        assert scoped.json()["items"] == []

    commit_url = f"/api/v1/imports/{preview['import_id']}/commit"
    # Extra client project hints are not part of the commit contract and cannot retarget it.
    committed = client.post(
        commit_url, params={"project_id": "second"}, json={"project_id": "second"}
    )
    assert committed.status_code == 200, committed.text
    result = committed.json()
    assert result["project_id"] == "first"
    assert result["resources"]
    assert all(ref["project_id"] == "first" for ref in result["resources"])
    replay = client.post(commit_url)
    assert replay.status_code == 200, replay.text
    assert replay.json() == result

    if listing is not None:
        original = client.get(f"/api/v1/{listing}", params={"project_id": "first"})
        alternate = client.get(f"/api/v1/{listing}", params={"project_id": "second"})
        assert original.status_code == alternate.status_code == 200
        assert len(original.json()[items_key]) == 1
        assert alternate.json()[items_key] == []
    else:
        ref = result["resources"][0]
        suffix = f"{kind}/{ref['asset_id']}/{ref['version']}"
        original = client.get(f"/api/v1/assets/first/{suffix}")
        assert original.status_code == 200, original.text
        assert original.json()["project_id"] == "first"
        assert client.get(f"/api/v1/assets/second/{suffix}").status_code == 404

    if kind == "trace":
        trace_id = result["resources"][0]["trace_id"]
        detail = client.get(f"/api/v1/traces/{trace_id}").json()
        assert detail["trace"]["project_id"] == "first"
        assert detail["evaluation_history"] == []
        assert detail["overall_pass"] is None


def test_two_project_drafts_commit_independently_in_reverse_order(client):
    template = client.get("/api/v1/imports/templates", params={"kind": "dataset"}).json()
    drafts = {}
    for project_id in ("first", "second"):
        response = client.post(
            "/api/v1/imports/preview",
            json={
                "project_id": project_id,
                "kind": "dataset",
                "files": [{"name": template["filename"], "content": template["content"]}],
                "options": {"id": "shared", "version": "1", "name": project_id},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "ready", response.text
        drafts[project_id] = response.json()["import_id"]

    for project_id, selected_project in (("second", "first"), ("first", "second")):
        response = client.post(
            f"/api/v1/imports/{drafts[project_id]}/commit",
            params={"project_id": selected_project},
            json={"project_id": selected_project},
        )
        assert response.status_code == 200, response.text
        assert response.json()["project_id"] == project_id
        ref = response.json()["resources"][0]
        detail = client.get(
            f"/api/v1/datasets/{project_id}/{ref['dataset_id']}/{ref['version']}"
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["name"] == project_id
    assert len(client.get("/api/v1/datasets").json()["items"]) == 2
