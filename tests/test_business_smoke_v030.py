from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from commerce_eval.business import smoke
from commerce_eval.business.smoke import DEFAULT_CASES, SmokeError, run_business_smoke
from commerce_eval.providers import CentralEnvStore, CredentialResolver, ProviderConfigService
from commerce_eval.storage import Database, Repository
from commerce_eval.storage.business_evidence import BusinessEvidenceRow
from commerce_eval.storage.models import ExperimentRow


@pytest.fixture
def repository(tmp_path):
    database = Database(tmp_path / "smoke.db")
    database.initialize()
    result = Repository(database)
    yield result
    database.dispose()


def options(**changes):
    return {"project_id": "smoke-test", "provider_id": "test-provider", "provider_version": 1,
            "model": "test-model", "allow_paid": True, **changes}


def response(content="No completed work is claimed.", calls=None, usage=None):
    return {"content": content, "tool_calls": calls or [], "usage": usage, "latency_ms": 1.0}


def call(name, arguments, identifier="test-call"):
    return {"id": identifier, "name": name, "arguments": arguments}


async def test_no_paid_optin_does_not_seed_resolve_credentials_or_invoke_callback(repository, monkeypatch):
    touched = []

    def forbidden(*args, **kwargs):
        touched.append(True)
        raise AssertionError("paid optin missing")

    monkeypatch.setattr(smoke, "ProviderConfigService", forbidden)
    with pytest.raises(SmokeError, match="paid_call_not_authorized"):
        await run_business_smoke(repository, **options(allow_paid=False), complete=forbidden)
    assert not touched and repository.list_projects() == []
    assert repository.list_experiments() == []


async def test_same_default_eight_cases_both_specs_exist_before_model_failure(repository):
    seen, scopes = [], []

    async def failing_model(*, messages, tools):
        experiments = repository.list_experiments("smoke-test")
        assert len(experiments) == 2
        seen.append({item["function"]["name"] for item in tools})
        scopes.append([item["status"] for item in experiments].count("running"))
        public = json.dumps(messages)
        for hidden in ("business_requirements", "verifier_id", "reference_actions", "interaction_script", "gates"):
            assert hidden not in public
        raise RuntimeError("offline-" + "sensitive" + "-failure-value")

    result = await run_business_smoke(repository, **options(), complete=failing_model)
    assert result["total_runs"] == 16
    assert result["counts"] == {"pass": 0, "fail": 0, "error": 16, "uncompleted": 0}
    assert sum(result["counts"].values()) == 16 and not result["overall_pass"]
    assert result["calls"]["callback_invocations"] == 16
    assert result["calls"]["provider_budget_attempts"] is None
    assert result["calls"]["http_requests_sent"] is None
    assert "provider_request_attempts" not in result["calls"]
    assert set(scopes) == {1}
    assert all("business_generate_catalog" in tools and "write_file" not in tools for tools in seen[:8])
    assert all("write_file" in tools and "business_generate_catalog" not in tools for tools in seen[8:])
    for experiment in result["experiments"]:
        assert {run["scenario_id"] for run in experiment["runs"]} == set(DEFAULT_CASES)
        assert experiment["recorded_runs"] == 8
        saved = repository.get_experiment(experiment["experiment_id"])
        assert saved["spec"]["concurrency"] == 1 and saved["spec"]["repetitions"] == 1
        assert saved["spec"]["provider_version"] == "1" and saved["spec"]["model"] == "test-model"
    assert result["model_source"] == "injected_callback"
    assert result["resource_usage"]["estimated_cost"] is None
    assert result["resource_usage"]["total_tokens"] is None
    assert "sensitive-failure-value" not in json.dumps(result)
    with repository.database.sessions() as session:
        assert len(session.scalars(select(BusinessEvidenceRow)).all()) == 16


async def test_shared_budget_across_surfaces_marks_remaining_cases_uncompleted(repository):
    calls = []

    async def one_call(*, messages, tools):
        calls.append(tools)
        return response()

    result = await run_business_smoke(repository, **options(), complete=one_call, max_calls=3)
    assert len(calls) == 3
    assert result["calls"]["candidate_attempts"] == 3
    assert result["calls"]["budget_exhausted"] and result["calls"]["remaining"] == 0
    assert result["counts"]["uncompleted"] == 13
    assert result["experiments"][1]["counts"]["uncompleted"] == 8
    assert all(item["recorded_runs"] == 8 for item in result["experiments"])
    assert result["resource_usage"]["total_tokens"] is None


async def test_offline_decisions_really_write_artifacts_and_evidence_survives_reset(repository):
    calls = []

    async def preview_model(*, messages, tools):
        names = {tool["function"]["name"] for tool in tools}
        previous = [message for message in messages if message["role"] == "tool"]
        if not previous:
            action = call("business_generate_catalog", {}) if "business_generate_catalog" in names else call("read_file", {"path": "inputs/products.json"})
            calls.append(action["name"])
            return response(calls=[action])
        if "write_file" in names and len(previous) == 1:
            actual_rows = json.loads(previous[-1]["content"])["content"]
            calls.append("write_file")
            return response(calls=[call("write_file", {"path": "artifacts/catalog.json", "content": actual_rows}, "write-actual-bytes")])
        return response(json.dumps({"outcome": "preview", "simulated": True}))

    result = await run_business_smoke(repository, **options(), template_ids=["I01"], complete=preview_model)
    assert calls == ["business_generate_catalog", "read_file", "write_file"]
    assert result["counts"] == {"pass": 2, "fail": 0, "error": 0, "uncompleted": 0}
    assert result["calls"]["callback_invocations"] == 5
    with repository.database.sessions() as session:
        evidence = session.scalars(select(BusinessEvidenceRow)).all()
    assert len(evidence) == 2
    for row in evidence:
        assert row.payload["artifacts"]
        assert row.payload["artifacts"][-1]["content"]
        assert len(row.payload["artifacts"][-1]["rows"]) == 20
        assert row.payload["complete"]


async def test_repeat_smoke_creates_new_experiments_and_preserves_old_records(repository):
    async def incomplete_model(**kwargs):
        return response()

    first = await run_business_smoke(repository, **options(), template_ids=["I01"], complete=incomplete_model)
    ids = [item["experiment_id"] for item in first["experiments"]]
    originals = [repository.get_experiment(identifier) for identifier in ids]
    second = await run_business_smoke(repository, **options(), template_ids=["I01"], complete=incomplete_model)
    assert first["smoke_id"] != second["smoke_id"]
    assert len(repository.list_experiments("smoke-test")) == 4
    assert originals == [repository.get_experiment(identifier) for identifier in ids]
    assert all(result["recorded_runs"] == 1 for result in second["experiments"])


async def test_injected_service_constructs_one_native_client_same_pinned_model_offline(repository, tmp_path):
    calls = []

    async def dns(host, port):
        return ["93.184.216.34"]

    def transport(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "No work claimed."}}],
                                       "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}})

    store = CentralEnvStore(tmp_path / "central.env", environ={})
    store.set_secret("TEST_PROVIDER_API_KEY", "offline-" + "sample-value-12345", expected_version=store.status()["version"])
    service = ProviderConfigService(repository, credential_resolver=CredentialResolver(store, environ={}),
        transport=httpx.MockTransport(transport), dns_resolver=dns)
    service.save({"provider_id": "test-provider", "kind": "custom", "name": "Offline model",
        "base_url": "https://model.example/v1", "model": "not-the-override",
        "credential_env": "TEST_PROVIDER_API_KEY", "endpoint_confirmed": True})
    result = await run_business_smoke(repository, **options(), service=service, template_ids=["I01"])
    assert len(calls) == 2 and all(item["model"] == "test-model" for item in calls)
    assert result["calls"]["provider_budget_attempts"] == 2
    assert result["calls"]["provider_preflight_rejections"] == 0
    assert result["calls"]["http_requests_sent"] is None
    assert result["calls"]["billable_requests"] is None
    assert result["model_usage"]["total_tokens"] == 20
    assert result["model_usage"]["cache_hit_tokens"] is None
    assert result["resource_usage"]["estimated_cost"] is None
    assert result["model_source"] == "injected_transport"


async def test_timeout_is_uncompleted_and_retains_two_run_records(repository):
    async def slow_model(**kwargs):
        await asyncio.sleep(1)
        return response()

    result = await run_business_smoke(repository, **options(), template_ids=["I01"], complete=slow_model, timeout_ms=100)
    assert result["counts"]["uncompleted"] == 2
    assert result["calls"]["callback_invocations"] == 2
    assert all(item["recorded_runs"] == 1 for item in result["experiments"])
    assert result["resource_usage"]["total_tokens"] is None


async def test_runner_setup_failure_keeps_both_immutable_specs_and_honest_records(repository, monkeypatch):
    def broken_target(*args, **kwargs):
        raise RuntimeError("not printed: " + "sensitive-detail")

    monkeypatch.setattr(smoke, "BusinessCandidateTarget", broken_target)
    result = await run_business_smoke(repository, **options(), complete=lambda **_: response(), template_ids=["I01"])
    assert result["counts"] == {"pass": 0, "fail": 0, "error": 2, "uncompleted": 0}
    assert result["calls"]["callback_invocations"] == 0
    for experiment in result["experiments"]:
        trace = repository.get_trace(experiment["runs"][0]["trace_id"])["trace"]
        assert trace["metadata"]["source"] == "smoke_runner"
        assert trace["metadata"]["model_trace_unavailable"]
        assert all(event["kind"] == "error" for event in trace["events"])
    assert "sensitive-detail" not in json.dumps(result)


async def test_cancellation_does_not_continue_paid_calls_on_second_surface(repository):
    calls = []

    async def cancelled(**kwargs):
        calls.append(1)
        raise asyncio.CancelledError

    result = await run_business_smoke(repository, **options(), complete=cancelled, template_ids=["I01"])
    assert len(calls) == 1 and result["cancelled"]
    assert result["counts"]["uncompleted"] == 2
    assert result["experiments"][1]["status"] == "cancelled"


@pytest.mark.parametrize("change", [{"max_calls": 129}, {"provider_version": True}, {"model": ""},
                                  {"provider_id": "token=" + "not-a-key"}])
async def test_invalid_configuration_cannot_start_or_seed(repository, change):
    with pytest.raises(SmokeError):
        await run_business_smoke(repository, **options(**change), complete=lambda **_: response())
    assert repository.list_experiments() == []


def test_cli_requires_paid_flag_before_creating_database_or_reading_configuration(tmp_path, capsys):
    path = tmp_path / "not-created.db"
    code = smoke.main(["--database", str(path), "--project", "smoke", "--provider", "deepseek",
                       "--provider-version", "1", "--model", "test-model"])
    assert code == 2 and not path.exists()
    assert json.loads(capsys.readouterr().out) == {"error_type": "paid_call_not_authorized", "executed": False}


def test_cli_supports_injected_offline_runner_and_outputs_json(tmp_path, capsys):
    called = []

    async def injected(repository, **kwargs):
        called.append(kwargs)
        return {"overall_pass": False, "counts": {"pass": 0, "fail": 1, "error": 0, "uncompleted": 0},
                "resource_usage": {"estimated_cost": None}}

    code = smoke.main(["--database", str(tmp_path / "cli.db"), "--project", "smoke", "--provider", "deepseek",
                       "--provider-version", "1", "--model", "test-model", "--allow-paid"], run_fn=injected)
    assert code == 1 and called[0]["allow_paid"]
    assert json.loads(capsys.readouterr().out)["resource_usage"]["estimated_cost"] is None


def test_classification_does_not_count_diagnostic_metric_errors_as_business_failures():
    detail = {"trace": {"status": "completed", "events": [], "output": {}, "metadata": {}},
              "metrics": [{"metric_id": "diagnostic", "status": "error"},
                          {"metric_id": "business_acceptance_pass", "status": "pass"}],
              "gates": [{"metric_id": "business_acceptance_pass", "passed": True}], "overall_pass": True}
    assert smoke._classify(detail) == "pass"
    detail["metrics"][1]["status"] = "error"
    detail["overall_pass"] = False
    assert smoke._classify(detail) == "error"
    detail["metrics"][1]["status"] = "fail"
    assert smoke._classify(detail) == "fail"


def test_cli_does_not_interrupt_another_active_experiment(repository, capsys):
    from commerce_eval.business.bootstrap import seed_business_bank
    from commerce_eval.contracts import ExperimentSpecV1

    repository.create_project("already-running", "Existing UI project")
    seeded = seed_business_bank(repository, "already-running", ["I01"])
    spec = ExperimentSpecV1.model_validate(seeded["candidate_experiment_specs"][0])
    repository.create_experiment(spec)
    repository.update_experiment(spec.experiment_id, status="running")

    async def injected(*args, **kwargs):
        return {"overall_pass": True}

    assert smoke.main(["--database", str(repository.database.path), "--project", "smoke", "--provider", "deepseek",
                       "--provider-version", "1", "--model", "test-model", "--allow-paid"], run_fn=injected) == 0
    assert repository.get_experiment(spec.experiment_id)["status"] == "running"


async def test_injected_client_identity_is_checked_and_one_callback_is_shared(repository):
    class Client:
        provider_id = "test-provider"
        version = 1
        model = "test-model"
        call_count = 0

        async def complete(self, **kwargs):
            self.call_count += 1
            return response()

    client = Client()
    result = await run_business_smoke(repository, **options(), client=client, template_ids=["I01"])
    assert client.call_count == 2 and result["calls"]["provider_budget_attempts"] == 2
    with pytest.raises(SmokeError, match="smoke_client_configuration_mismatch"):
        await run_business_smoke(repository, **options(model="different-model"), client=client, template_ids=["I01"])


@pytest.mark.parametrize("location", ["output", "metadata", "event"])
def test_provider_cause_is_uncompleted_environment_failure_not_business_failure(location):
    detail = {"trace": {"status": "failed", "events": [], "output": {"error_type": "model_request_failed"}, "metadata": {}},
              "metrics": [{"metric_id": "business_acceptance_pass", "status": "fail"}],
              "gates": [{"metric_id": "business_acceptance_pass", "passed": False}], "overall_pass": False}
    cause = {"provider_error_type": "provider_address_forbidden"}
    if location == "event":
        detail["trace"]["events"].append({"kind": "error", "attributes": cause})
    else:
        detail["trace"][location].update(cause)
    assert smoke._classify(detail) == "uncompleted"
    assert smoke._failure_category(detail, "uncompleted") == "environment_unavailable"
    assert smoke._error_codes(detail) == {"model_request_failed", "provider_address_forbidden"}


@pytest.mark.parametrize("cause", [None, ["provider_address_forbidden"], {"arbitrary": "field"}, "private-" + "failure-value"])
def test_legacy_or_unknown_cause_does_not_fabricate_environment_diagnosis(cause):
    detail = {"trace": {"status": "failed", "events": [], "output": {"error_type": "model_request_failed", "provider_error_type": cause}, "metadata": {}},
              "metrics": [], "gates": [], "overall_pass": False}
    assert smoke._classify(detail) == "error"
    assert smoke._failure_category(detail, "error") == "execution_error"
    assert smoke._error_codes(detail) == {"model_request_failed"}


def offline_native_service(repository, tmp_path, *, addresses, transport):
    async def dns(host, port):
        return addresses

    store = CentralEnvStore(tmp_path / "unused-central.env", environ={})
    credentials = CredentialResolver(store, environ={"TEST_PROVIDER_API_KEY": "offline-" + "sample-value-12345"})
    service = ProviderConfigService(repository, credential_resolver=credentials,
        transport=httpx.MockTransport(transport), dns_resolver=dns)
    service.save({"provider_id": "test-provider", "kind": "custom", "name": "Offline model",
        "base_url": "https://model.example/v1", "model": "test-model",
        "credential_env": "TEST_PROVIDER_API_KEY", "endpoint_confirmed": True})
    return service


async def test_dns_safety_rejection_is_not_a_sent_or_paid_request(repository, tmp_path):
    sent = []

    def must_not_send(request):
        sent.append(True)
        raise AssertionError("preflight must reject before HTTP")

    service = offline_native_service(repository, tmp_path, addresses=["198.18.0.7"], transport=must_not_send)
    result = await run_business_smoke(repository, **options(), service=service)
    assert sent == []
    assert result["counts"] == {"pass": 0, "fail": 0, "error": 0, "uncompleted": 16}
    assert result["environment_unavailable_runs"] == 16
    assert not result["overall_pass"]
    assert result["calls"]["callback_invocations"] == 16
    assert result["calls"]["provider_budget_attempts"] == 16
    assert result["calls"]["provider_preflight_rejections"] == 16
    assert result["calls"]["http_requests_sent"] == 0
    assert result["calls"]["http_count_status"] == "preflight_only_no_send"
    assert result["calls"]["billable_requests"] is None
    assert "not_http_sends" in result["calls"]["count_semantics"]["provider_budget_attempts"]
    for experiment in result["experiments"]:
        assert experiment["recorded_runs"] == experiment["environment_unavailable_runs"] == 8
        for run in experiment["runs"]:
            assert run["failure_category"] == "environment_unavailable"
            assert "provider_address_forbidden" in run["error_codes"]
            assert "model_request_failed" in run["error_codes"]
            assert repository.get_trace(run["trace_id"])["trace"]["status"] == "failed"
    assert result["model_usage"]["total_tokens"] is None
    assert result["resource_usage"]["estimated_cost"] is None
    assert "sample-value-12345" not in json.dumps(result)


@pytest.mark.parametrize("status,cause", [(401, "provider_authentication_denied"), (429, "provider_rate_limited"), (503, "provider_backend_error")])
async def test_provider_http_failure_is_visible_environment_failure_with_unknown_accounting(repository, tmp_path, status, cause):
    sent = []

    def rejected(request):
        sent.append(True)
        return httpx.Response(status, json={"error": "not-reported-" + "private-provider-body"})

    service = offline_native_service(repository, tmp_path, addresses=["93.184.216.34"], transport=rejected)
    result = await run_business_smoke(repository, **options(), service=service, template_ids=["I01"])
    assert len(sent) == 2
    assert result["counts"] == {"pass": 0, "fail": 0, "error": 0, "uncompleted": 2}
    assert result["calls"]["provider_budget_attempts"] == 2
    assert result["calls"]["provider_preflight_rejections"] == 0
    assert result["calls"]["http_requests_sent"] is None
    assert result["calls"]["http_count_status"] == "not_instrumented"
    assert result["calls"]["billable_requests"] is None
    assert all(cause in item["runs"][0]["error_codes"] for item in result["experiments"])
    assert "private-provider-body" not in json.dumps(result)
