from __future__ import annotations

import sys

import httpx
import pytest

from commerce_eval.contracts import (
    EvalCaseV1,
    ExperimentSpecV1,
    TargetDefinitionV1,
    TargetResumeRequestV1,
    TargetRunRequestV1,
)
from commerce_eval.demo import seed_demo
from commerce_eval.experiments import ExperimentRunner
from commerce_eval.storage import Database, Repository
from commerce_eval.targets import HTTPAgentTarget, PythonAgentTarget, build_target


def _run_request(case: EvalCaseV1) -> TargetRunRequestV1:
    return TargetRunRequestV1(
        request_id="request-1",
        session_id="session-1",
        case=case,
        execution_mode="dry_run",
        timeout_ms=5000,
    )


@pytest.mark.asyncio
async def test_python_target_uses_json_line_protocol() -> None:
    definition = TargetDefinitionV1(
        target_id="fixture-agent",
        version="1",
        name="Fixture",
        adapter_type="python",
        safe_for_eval=True,
        config={"command": [sys.executable, "-m", "commerce_eval.demo_target"], "project_id": "demo"},
    )
    case = EvalCaseV1(case_id="case", name="Case", expected_tools=["catalog.generate_listing"])
    response = await PythonAgentTarget(definition).start(_run_request(case))
    assert response.status.value == "completed"
    assert any(event.kind == "tool.call" for event in response.trace.events)



@pytest.mark.asyncio
async def test_demo_target_really_pauses_and_resumes_clarification() -> None:
    definition = TargetDefinitionV1(
        target_id="fixture-agent",
        version="1",
        name="Fixture",
        adapter_type="python",
        safe_for_eval=True,
        config={"command": ["$PYTHON", "-m", "commerce_eval.demo_runtime"], "project_id": "demo"},
    )
    target = PythonAgentTarget(definition)
    case = EvalCaseV1(
        case_id="clarify-market",
        name="Clarify",
        input={"message": "Prepare a listing."},
    )
    started = await target.start(_run_request(case))
    assert started.status.value == "awaiting_input"
    assert started.pending_interaction is not None
    assert not any(event.kind == "tool.call" for event in started.trace.events)
    resumed = await target.resume(
        TargetResumeRequestV1(
            request_id="resume-1",
            external_run_id=started.external_run_id,
            session_id="session-1",
            interaction_id=started.pending_interaction.interaction_id,
            response={"answer": "DE"},
            timeout_ms=5000,
        )
    )
    assert resumed.status.value == "completed"
    calls = [event for event in resumed.trace.events if event.kind == "tool.call"]
    assert calls[0].attributes["arguments"]["market"] == "DE"

@pytest.mark.asyncio
async def test_http_target_contract_with_injected_transport() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/runs"
        python_definition = TargetDefinitionV1(
            target_id="fixture-agent",
            version="1",
            name="Fixture",
            adapter_type="python",
            safe_for_eval=True,
            config={"command": [sys.executable, "-m", "commerce_eval.demo_target"], "project_id": "demo"},
        )
        case = EvalCaseV1(case_id="case", name="Case")
        response = await PythonAgentTarget(python_definition).start(_run_request(case))
        return httpx.Response(200, json=response.model_dump(mode="json"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    definition = TargetDefinitionV1(
        target_id="http-agent",
        version="1",
        name="HTTP",
        adapter_type="http",
        safe_for_eval=True,
        config={"base_url": "https://agent.invalid", "project_id": "demo"},
    )
    response = await HTTPAgentTarget(definition, client=client).start(_run_request(EvalCaseV1(case_id="case", name="Case")))
    await client.aclose()
    assert response.status.value == "completed"


def test_unsafe_or_live_target_is_rejected() -> None:
    unsafe = TargetDefinitionV1(target_id="unsafe", version="1", name="Unsafe", adapter_type="http", safe_for_eval=False, config={"base_url": "https://agent.invalid"})
    with pytest.raises(ValueError, match="target_not_safe_for_eval"):
        build_target(unsafe)
    live = unsafe.model_copy(update={"safe_for_eval": True, "config": {"base_url": "https://agent.invalid", "execution_mode": "live"}})
    with pytest.raises(ValueError, match="live_target_not_allowed"):
        build_target(live)


@pytest.mark.asyncio
async def test_experiment_runner_executes_dataset_and_persists_evidence(tmp_path) -> None:
    database = Database(tmp_path / "experiment.db")
    database.initialize()
    repository = Repository(database)
    seed_demo(repository)
    spec = ExperimentSpecV1(
        experiment_id="exp-test-runner",
        project_id="commerce-demo",
        name="Runner test",
        dataset_id="commerce-operations",
        dataset_version="1.0.0",
        target_id="fixture-agent",
        target_version="1.0.0",
        tool_contract_set_id="default",
        tool_contract_version="1.0.0",
        evaluator_set_version="1.0.0",
        repetitions=1,
        concurrency=2,
    )
    repository.create_experiment(spec)
    result = await ExperimentRunner(repository).run(spec)
    traces = repository.list_traces(experiment_id=spec.experiment_id)
    assert result["status"] == "completed"
    assert result["completed_runs"] == 3
    assert len(traces) == 3
    assert all(repository.get_trace(row["trace_id"])["metrics"] for row in traces)

