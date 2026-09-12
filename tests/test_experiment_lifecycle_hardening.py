from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from commerce_eval.api import create_app
from commerce_eval.contracts import ExperimentSpecV1
from commerce_eval.demo import seed_demo
from commerce_eval.experiments import ExperimentManager, ExperimentRunner
from commerce_eval.storage import Database, Repository


def _repository(tmp_path, name: str = "lifecycle.db") -> Repository:
    database = Database(tmp_path / name)
    database.initialize()
    repository = Repository(database)
    seed_demo(repository)
    return repository


def _spec(experiment_id: str, **updates) -> ExperimentSpecV1:
    payload = {
        "experiment_id": experiment_id,
        "project_id": "commerce-demo",
        "name": "Lifecycle",
        "dataset_id": "commerce-operations",
        "dataset_version": "1.0.0",
        "target_id": "fixture-agent",
        "target_version": "1.0.0",
        "tool_contract_set_id": "default",
        "tool_contract_version": "1.0.0",
        "evaluator_set_id": "default",
        "evaluator_set_version": "1.0.0",
        "timeout_ms": 100,
        "concurrency": 2,
    }
    payload.update(updates)
    return ExperimentSpecV1.model_validate(payload)


class HangingTarget:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.reset_sessions: list[str] = []

    async def capabilities(self):
        return {"operations": ["start", "resume", "reset"]}

    async def start(self, _request):
        self.started.set()
        await asyncio.Event().wait()

    async def resume(self, _request):
        await asyncio.Event().wait()

    async def reset(self, session_id: str) -> None:
        self.reset_sessions.append(session_id)


@pytest.mark.asyncio
async def test_runner_enforces_timeout_and_resets_every_session(tmp_path) -> None:
    repository = _repository(tmp_path)
    spec = _spec("exp-timeout")
    repository.create_experiment(spec)
    target = HangingTarget()
    result = await ExperimentRunner(repository, target_factory=lambda _definition: target).run(spec)
    traces = repository.list_traces(experiment_id=spec.experiment_id)
    assert result["status"] == "completed"
    assert result["completed_runs"] == 3
    assert len(target.reset_sessions) == 3
    assert len(traces) == 3
    assert all(repository.get_trace(item["trace_id"])["trace"]["output"]["error_type"] == "target_timeout" for item in traces)


@pytest.mark.asyncio
async def test_manager_cancellation_marks_experiment_and_runs_reset(tmp_path) -> None:
    repository = _repository(tmp_path, "cancel.db")
    spec = _spec("exp-cancel", concurrency=1, timeout_ms=5000)
    repository.create_experiment(spec)
    target = HangingTarget()
    manager = ExperimentManager(ExperimentRunner(repository, target_factory=lambda _definition: target))
    task = manager.start(spec)
    await asyncio.wait_for(target.started.wait(), timeout=1)
    assert manager.cancel(spec.experiment_id) is True
    with pytest.raises(asyncio.CancelledError):
        await task
    assert repository.get_experiment(spec.experiment_id)["status"] == "cancelled"
    assert len(target.reset_sessions) == 1


@pytest.mark.asyncio
async def test_interrupted_run_resumes_without_repeating_completed_cases(tmp_path) -> None:
    repository = _repository(tmp_path, "resume.db")
    spec = _spec("exp-resume", timeout_ms=5000, model_config_version="model-config-7")
    repository.create_experiment(spec)
    runner = ExperimentRunner(repository)
    first = await runner.run(spec)
    assert first["completed_runs"] == 3
    repository.update_experiment(spec.experiment_id, status="interrupted", completed_runs=1)
    second = await runner.run(spec)
    assert second["status"] == "completed"
    assert second["completed_runs"] == 3
    traces = repository.list_traces(experiment_id=spec.experiment_id)
    assert len(traces) == 3
    assert all(repository.get_trace(item["trace_id"])["trace"]["metadata"]["model_config_version"] == "model-config-7" for item in traces)


def test_retry_creates_new_immutable_experiment(tmp_path) -> None:
    database_path = tmp_path / "retry.db"
    app = create_app(database_path=database_path)
    repository = app.state.repository
    seed_demo(repository)
    source = _spec("exp-source", timeout_ms=5000)
    repository.create_experiment(source)
    repository.update_experiment(source.experiment_id, status="failed", error_type="test_failure")
    with TestClient(app) as client:
        response = client.post(f"/api/v1/experiments/{source.experiment_id}/retry")
        assert response.status_code == 202
        retry = response.json()
        assert retry["experiment_id"].startswith("exp-source-retry-")
        assert retry["experiment_id"] != source.experiment_id
        assert client.get(f"/api/v1/experiments/{source.experiment_id}").json()["status"] == "failed"
