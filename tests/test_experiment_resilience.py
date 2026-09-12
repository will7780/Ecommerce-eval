from __future__ import annotations

import asyncio
import sys

import httpx
import pytest

from commerce_eval.contracts import EvalCaseV1, ExperimentSpecV1, TargetDefinitionV1, TargetRunRequestV1
from commerce_eval.demo import seed_demo
from commerce_eval.experiments import ExperimentEventBus, ExperimentRunner
from commerce_eval.packs import all_evaluators
from commerce_eval.storage import Database, Repository
from commerce_eval.targets import HTTPAgentTarget, PythonAgentTarget


def _request(timeout_ms: int = 100) -> TargetRunRequestV1:
    return TargetRunRequestV1(
        request_id="request",
        session_id="session",
        case=EvalCaseV1(case_id="case", name="Case"),
        execution_mode="dry_run",
        timeout_ms=timeout_ms,
    )


@pytest.mark.asyncio
async def test_python_target_timeout_is_structured() -> None:
    target = PythonAgentTarget(
        TargetDefinitionV1(
            target_id="slow",
            version="1",
            name="Slow",
            adapter_type="python",
            safe_for_eval=True,
            config={"command": [sys.executable, "-c", "import time; time.sleep(2)"]},
        )
    )
    response = await target.start(_request())
    assert response.status.value == "failed"
    assert response.error_type == "target_timeout"


@pytest.mark.asyncio
async def test_http_permission_denial_is_structured() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "denied"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    target = HTTPAgentTarget(
        TargetDefinitionV1(
            target_id="remote",
            version="1",
            name="Remote",
            adapter_type="http",
            safe_for_eval=True,
            config={"base_url": "https://agent.invalid", "project_id": "project"},
        ),
        client=client,
    )
    response = await target.start(_request(1000))
    await client.aclose()
    assert response.error_type == "target_permission_denied"


@pytest.mark.asyncio
async def test_experiment_uses_the_pinned_evaluator_set(tmp_path) -> None:
    database = Database(tmp_path / "pinned.db")
    database.initialize()
    repository = Repository(database)
    seed_demo(repository)
    repository.save_evaluator_set("commerce-demo", "minimal", "1.0.0", ["task_completion"])
    spec = ExperimentSpecV1(
        experiment_id="exp-minimal",
        project_id="commerce-demo",
        name="Minimal",
        dataset_id="commerce-operations",
        dataset_version="1.0.0",
        target_id="fixture-agent",
        target_version="1.0.0",
        tool_contract_set_id="default",
        tool_contract_version="1.0.0",
        evaluator_set_id="minimal",
        evaluator_set_version="1.0.0",
    )
    repository.create_experiment(spec)
    await ExperimentRunner(repository).run(spec)
    for row in repository.list_traces(experiment_id="exp-minimal"):
        assert [metric["metric_id"] for metric in repository.get_trace(row["trace_id"])["metrics"]] == ["task_completion"]


@pytest.mark.asyncio
async def test_repetitions_create_distinct_version_pinned_runs(tmp_path) -> None:
    database = Database(tmp_path / "repeat.db")
    database.initialize()
    repository = Repository(database)
    seed_demo(repository)
    spec = ExperimentSpecV1(
        experiment_id="exp-repeat",
        project_id="commerce-demo",
        name="Repeat",
        dataset_id="commerce-operations",
        dataset_version="1.0.0",
        target_id="fixture-agent",
        target_version="1.0.0",
        tool_contract_set_id="default",
        tool_contract_version="1.0.0",
        evaluator_set_id="default",
        evaluator_set_version="1.0.0",
        repetitions=2,
        concurrency=2,
    )
    repository.create_experiment(spec)
    result = await ExperimentRunner(repository).run(spec)
    assert result["completed_runs"] == 6
    assert len(repository.list_traces(experiment_id="exp-repeat")) == 6


@pytest.mark.asyncio
async def test_sse_bus_replays_history_before_live_events() -> None:
    bus = ExperimentEventBus()
    await bus.publish("exp", "experiment.started", {"total_runs": 1})
    stream = bus.stream("exp")
    first = await anext(stream)
    assert first["type"] == "experiment.started"
    await stream.aclose()
