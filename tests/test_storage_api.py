from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from commerce_eval.api import create_app
from commerce_eval.contracts import EvalCaseV1, ExperimentSpecV1, ToolContractV1, TraceEnvelopeV1
from commerce_eval.storage import Database, Repository, VersionConflictError


def _case() -> EvalCaseV1:
    return EvalCaseV1(
        case_id="case-1",
        name="One deterministic check",
        input={"message": "Inspect the fixture."},
        gates=[{"metric_id": "task_completion", "operator": "equals", "expected": True}],
    )


def test_versioned_dataset_is_immutable(tmp_path) -> None:
    database = Database(tmp_path / "platform.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("project", "Project")
    repository.save_dataset("project", "dataset", "1", "Dataset", [_case()])
    repository.save_dataset("project", "dataset", "1", "Dataset", [_case()])
    changed = _case().model_copy(update={"name": "Changed"})
    with pytest.raises(VersionConflictError, match="dataset_version_immutable_conflict"):
        repository.save_dataset("project", "dataset", "1", "Dataset", [changed])


def test_database_restart_marks_active_experiment_interrupted(tmp_path) -> None:
    path = tmp_path / "platform.db"
    database = Database(path)
    database.initialize()
    repository = Repository(database)
    repository.create_project("project", "Project")
    repository.save_dataset("project", "dataset", "1", "Dataset", [_case()])
    repository.create_experiment(
        ExperimentSpecV1(
            experiment_id="experiment",
            project_id="project",
            name="Experiment",
            dataset_id="dataset",
            dataset_version="1",
            target_id="target",
            target_version="1",
        )
    )
    repository.update_experiment("experiment", status="running")
    database.dispose()

    reopened = Database(path)
    reopened.initialize()
    assert Repository(reopened).get_experiment("experiment")["status"] == "interrupted"


def test_repository_uses_pinned_tool_contract_for_business_field_redaction(tmp_path) -> None:
    database = Database(tmp_path / "contract-redaction.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("project", "Project")
    repository.save_tool_contract_set(
        "project",
        "contract-set",
        "1",
        [
            ToolContractV1(
                tool_id="catalog.lookup_listing",
                version="1",
                title="Lookup listing",
                sensitive_fields=["merchant_reference"],
            )
        ],
    )
    repository.save_trace(
        TraceEnvelopeV1(
            trace_id="trace-contract-redaction",
            project_id="project",
            target_id="target",
            target_version="1",
            tool_contract_set_id="contract-set",
            tool_contract_version="1",
            started_at=datetime.now(timezone.utc),
            input={"merchant_reference": "merchant-private-42"},
            output={"merchant_reference": "merchant-private-42"},
            events=[
                {
                    "event_id": "tool-1",
                    "sequence": 0,
                    "kind": "tool.call",
                    "attributes": {
                        "tool_id": "catalog.lookup_listing",
                        "arguments": {"merchant_reference": "merchant-private-42"},
                    },
                }
            ],
        )
    )
    persisted = repository.get_trace("trace-contract-redaction")
    serialized = str(persisted)
    assert "merchant-private-42" not in serialized
    assert "[REDACTED]" in serialized
    assert persisted["trace"]["tool_contract_set_id"] == "contract-set"

def test_api_ingests_only_redacted_normalized_trace(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "api.db", static_dir=tmp_path / "missing-static")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/traces",
            json=TraceEnvelopeV1(
                trace_id="trace-api",
                project_id="project-api",
                target_id="target",
                target_version="1",
                started_at=datetime.now(timezone.utc),
                input={"api_key": "must-not-persist", "message": "token=also-secret"},
                events=[{"event_id": "e", "sequence": 8, "kind": "vendor.future"}],
            ).model_dump(mode="json"),
        )
        assert response.status_code == 201
        detail = client.get("/api/v1/traces/trace-api")
        assert detail.status_code == 200
        serialized = detail.text
        assert "must-not-persist" not in serialized
        assert "also-secret" not in serialized
        assert "[REDACTED]" in serialized
        assert detail.json()["trace"]["events"][0]["sequence"] == 0


def test_trace_import_creates_non_executable_experiment_placeholder(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "import.db", static_dir=tmp_path / "missing-static")
    with TestClient(app) as client:
        trace = TraceEnvelopeV1(
            trace_id="trace-import",
            project_id="import-project",
            target_id="external-target",
            target_version="4",
            experiment_id="external-experiment",
            started_at=datetime.now(timezone.utc),
        )
        assert client.post("/api/v1/traces", json=trace.model_dump(mode="json")).status_code == 201
        experiment = client.get("/api/v1/experiments/external-experiment")
        assert experiment.status_code == 200
        assert experiment.json()["status"] == "imported"
        assert experiment.json()["spec"]["source"] == "trace_import"


def test_api_contract_crud_and_dashboard(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "crud.db", static_dir=tmp_path / "missing-static")
    with TestClient(app) as client:
        assert client.post("/api/v1/projects", json={"project_id": "p", "name": "Project"}).status_code == 201
        dataset = client.post(
            "/api/v1/datasets",
            json={
                "project_id": "p",
                "dataset_id": "d",
                "version": "1",
                "name": "Dataset",
                "cases": [_case().model_dump(mode="json")],
            },
        )
        assert dataset.status_code == 201
        assert dataset.json()["case_count"] == 1
        assert client.get("/api/v1/evaluators").status_code == 200
        dashboard = client.get("/api/v1/dashboard", params={"project_id": "p"})
        assert dashboard.status_code == 200
        assert dashboard.json()["trace_count"] == 0

