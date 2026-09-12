"""Timeout correction coverage with synthetic credentials and fake DNS/transports only."""

import asyncio
import json
import socket
from types import SimpleNamespace

import httpx
import pytest

from commerce_eval.business import smoke
from commerce_eval.core import content_checksum
from commerce_eval.providers import CentralEnvStore, CredentialResolver, NativeCompatibleClient, ProviderError
from commerce_eval.storage import Database, Repository


@pytest.fixture(autouse=True)
def forbid_machine_access(monkeypatch):
    attempted = []

    def forbidden(*args, **kwargs):
        attempted.append(True)
        raise AssertionError("real credentials, DNS and network are forbidden")

    monkeypatch.setattr(CredentialResolver, "resolve", forbidden)
    monkeypatch.setattr(CentralEnvStore, "_read", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    yield
    assert not attempted


@pytest.fixture
def repository(tmp_path):
    database = Database(tmp_path / "timeout.db")
    database.initialize()
    yield Repository(database)
    database.dispose()


class FakeService:
    def __init__(self, handler=None):
        self.requests = []
        self.resolutions = []
        self.dns_calls = []
        self.credentials = SimpleNamespace(resolve=self.resolve)
        self.transport = httpx.MockTransport(handler or self.respond)

    def get(self, provider_id, version):
        return {"model": "test-model", "credential_env": "OFFLINE_API_KEY",
                "base_url": "https://model.example/v1", "allow_localhost": False}

    def require_active(self, provider_id, version):
        return self.get(provider_id, version)

    def resolve(self, name):
        self.resolutions.append(name)
        return SimpleNamespace(configured=True,
                               value=SimpleNamespace(get_secret_value=lambda: "offline-placeholder"))

    async def dns_resolver(self, host, port):
        self.dns_calls.append((host, port))
        return ["93.184.216.34"]

    def respond(self, request):
        self.requests.append({"timeout": request.extensions["timeout"], "body": json.loads(request.content)})
        return httpx.Response(200, json={"choices": [{"message": {"content": "No work claimed."}}]})


def options(**changes):
    return {"project_id": "timeout-test", "provider_id": "test-provider", "provider_version": 1,
            "model": "test-model", "allow_paid": True, "template_ids": ["I01"], **changes}


def native_client(service, **changes):
    return NativeCompatibleClient(service, provider_id="test-provider", version=1,
        transport=service.transport, dns_resolver=service.dns_resolver,
        **{"allow_paid": True, "timeout_seconds": 120.0, **changes})


def completion(*, messages, tools):
    return {"content": "No work claimed.", "tool_calls": [], "usage": None}


@pytest.mark.parametrize("changes,seconds,tokens", [({}, 120.0, 4096),
    ({"model_timeout_seconds": 37.5, "timeout_ms": 200000, "max_completion_tokens": 512}, 37.5, 512),
    ({"model_timeout_seconds": 300, "max_completion_tokens": 32768}, 300.0, 32768)])
async def test_smoke_passes_per_call_limits_to_fake_transport(repository, changes, seconds, tokens):
    service = FakeService()
    result = await smoke.run_business_smoke(repository, **options(**changes), service=service)
    assert len(service.requests) == len(service.dns_calls) == 2
    for request in service.requests:
        assert request["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), seconds)
        assert request["body"]["max_tokens"] == tokens
        assert request["body"]["model"] == "test-model"
    assert result["calls"]["provider_budget_attempts"] == 2
    assert result["model_source"] == "injected_transport"
    assert result["limits"]["model_timeout_seconds"] == seconds


INVALID_TIMEOUTS = [True, False, None, "120", float("nan"), float("inf"), float("-inf"), 0, -1, 300.01]
INVALID_TOKENS = [True, False, None, "4096", float("nan"), float("inf"), float("-inf"), 0, -1, 1.5, 4096.0, 32769]


@pytest.mark.parametrize("field,value", [("timeout_seconds", value) for value in INVALID_TIMEOUTS]
                         + [("max_completion_tokens", value) for value in INVALID_TOKENS])
def test_native_request_limits_reject_invalid_values_before_credentials(field, value):
    service = FakeService()
    with pytest.raises(ProviderError, match="provider_request_budget_invalid"):
        native_client(service, **{field: value})
    assert service.resolutions == service.requests == service.dns_calls == []


@pytest.mark.parametrize("field,value,code", [
    *(("model_timeout_seconds", value, "smoke_model_timeout_invalid") for value in INVALID_TIMEOUTS),
    *(("max_completion_tokens", value, "smoke_completion_budget_invalid") for value in INVALID_TOKENS),
    *(("timeout_ms", value, "smoke_timeout_invalid") for value in
      [True, False, None, "100", float("nan"), float("inf"), float("-inf"), 99, 100.5, 300001]),
    *(("max_calls", value, "smoke_call_budget_invalid") for value in
      [True, False, None, "1", float("nan"), float("inf"), float("-inf"), 0, 1.5, 129]),
])
async def test_smoke_rejects_invalid_limits_before_seed_or_credentials(repository, field, value, code):
    service = FakeService()
    with pytest.raises(smoke.SmokeError, match=code):
        await smoke.run_business_smoke(repository, **options(**{field: value}), service=service)
    assert repository.list_projects() == repository.list_experiments() == []
    assert service.resolutions == service.requests == service.dns_calls == []


@pytest.mark.parametrize("changed", [{"model_timeout_seconds": 121}, {"timeout_ms": 299999},
                                    {"max_completion_tokens": 4095}, {"max_calls": 127}])
async def test_each_limit_changes_immutable_model_pin_without_touching_history(repository, changed):
    first = await smoke.run_business_smoke(repository, **options(), complete=completion)
    originals = [repository.get_experiment(row["experiment_id"]) for row in first["experiments"]]
    second = await smoke.run_business_smoke(repository, **options(**changed), complete=completion)
    assert first["model_config_version"] != second["model_config_version"]
    assert originals == [repository.get_experiment(row["experiment_id"]) for row in first["experiments"]]
    for result in (first, second):
        config = {"provider_id": "test-provider", "provider_version": 1, "model": "test-model", **result["limits"]}
        assert result["model_config_version"] == "model-" + content_checksum(config)[:48]
        for row in result["experiments"]:
            spec = repository.get_experiment(row["experiment_id"])["spec"]
            assert spec["model_config_version"] == result["model_config_version"]
            assert spec["timeout_ms"] == result["limits"]["whole_case_timeout_ms"]
            assert all(spec["tags"][key] == str(value) for key, value in result["limits"].items())


async def test_equivalent_numeric_timeouts_share_pin_and_callback_signature_stays_compatible(repository):
    first = await smoke.run_business_smoke(repository, **options(model_timeout_seconds=120), complete=completion)

    async def async_completion(*, messages, tools):
        return completion(messages=messages, tools=tools)

    second = await smoke.run_business_smoke(repository, **options(model_timeout_seconds=120.0), complete=async_completion)
    assert first["model_config_version"] == second["model_config_version"]
    assert first["calls"]["callback_invocations"] == second["calls"]["callback_invocations"] == 2


@pytest.mark.parametrize("changes", [{"timeout_seconds": 30}, {"max_calls": 1}, {"max_completion_tokens": 8}])
async def test_injected_native_client_cannot_misstate_pinned_limits(repository, changes):
    service = FakeService()
    client = native_client(service, **changes)
    with pytest.raises(smoke.SmokeError, match="smoke_client_configuration_mismatch"):
        await smoke.run_business_smoke(repository, **options(), client=client)
    assert repository.list_projects() == []
    assert service.resolutions == service.requests == []


@pytest.mark.parametrize("mode", ["default", "service", "callback"])
async def test_no_optin_does_not_construct_provider_resolve_or_seed(repository, monkeypatch, mode):
    touched = []

    def forbidden(*args, **kwargs):
        touched.append(True)
        raise AssertionError("opt-in required")

    monkeypatch.setattr(smoke, "ProviderConfigService", forbidden)
    service = FakeService()
    injected = {"service": service} if mode == "service" else {"complete": forbidden} if mode == "callback" else {}
    with pytest.raises(smoke.SmokeError, match="paid_call_not_authorized"):
        await smoke.run_business_smoke(repository, **options(allow_paid=False), **injected)
    assert touched == service.resolutions == service.requests == service.dns_calls == []
    assert repository.list_projects() == repository.list_experiments() == []


async def test_native_no_optin_never_resolves_or_sends():
    service = FakeService()
    client = native_client(service, allow_paid=False)
    with pytest.raises(ProviderError, match="paid_call_not_authorized"):
        await client.complete([{"role": "user", "content": "test"}])
    assert client.call_count == 0
    assert service.resolutions == service.requests == service.dns_calls == []


async def test_native_external_cancellation_reaches_transport_without_retry():
    entered, cancelled = asyncio.Event(), asyncio.Event()
    sends = []

    async def blocked(request):
        sends.append(True)
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    client = native_client(FakeService(blocked))
    task = asyncio.create_task(client.complete([{"role": "user", "content": "test"}]))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert cancelled.is_set() and sends == [True] and client.call_count == 1


async def test_native_deadline_cancels_transport_once_with_fake_clock_latency():
    sends, cancelled = [], []
    now = [100.0]

    async def blocked(request):
        sends.append(True)
        try:
            await asyncio.Future()
        finally:
            now[0] = 100.25
            cancelled.append(True)

    client = native_client(FakeService(blocked), timeout_seconds=0.01, clock=lambda: now[0])
    with pytest.raises(ProviderError, match="provider_timeout") as failure:
        await client.complete([{"role": "user", "content": "test"}])
    assert failure.value.latency_ms == 250.0
    assert sends == cancelled == [True] and client.call_count == 1


@pytest.mark.parametrize("model_seconds,case_ms", [(0.01, 300000), (120.0, 100)])
async def test_shorter_deadline_wins_without_duplicate_requests(repository, model_seconds, case_ms):
    entered, cancelled = [], []

    async def blocked(request):
        entered.append(request.extensions["timeout"]["read"])
        try:
            await asyncio.Future()
        finally:
            cancelled.append(True)

    result = await smoke.run_business_smoke(repository, **options(model_timeout_seconds=model_seconds,
        timeout_ms=case_ms), service=FakeService(blocked))
    assert entered == [model_seconds, model_seconds] and cancelled == [True, True]
    assert result["counts"]["uncompleted"] == 2
    assert result["calls"]["provider_budget_attempts"] == 2
    assert all(row["recorded_runs"] == 1 for row in result["experiments"])
    if model_seconds < case_ms / 1000:
        assert all("provider_timeout" in row["runs"][0]["error_codes"] for row in result["experiments"])


def cli_args(path):
    return ["--database", str(path), "--project", "timeout-test", "--provider", "test-provider",
            "--provider-version", "1", "--model", "test-model"]


@pytest.mark.parametrize("extra,expected", [([], (120.0, 300000)),
    (["--model-timeout-seconds", "75.5", "--timeout-ms", "1000"], (75.5, 1000))])
def test_cli_forwards_independent_timeouts_to_offline_runner(tmp_path, capsys, extra, expected):
    called = []

    async def run(repository, **kwargs):
        called.append(kwargs)
        return {"overall_pass": True}

    assert smoke.main(cli_args(tmp_path / "cli.db") + ["--allow-paid"] + extra, run_fn=run) == 0
    assert (called[0]["model_timeout_seconds"], called[0]["timeout_ms"]) == expected
    assert json.loads(capsys.readouterr().out) == {"overall_pass": True}


@pytest.mark.parametrize("extra,code", [(["--model-timeout-seconds", value], "smoke_model_timeout_invalid")
    for value in ("nan", "inf", "0", "301")] + [(["--timeout-ms", "99"], "smoke_timeout_invalid")])
def test_cli_invalid_timeouts_do_not_create_database(tmp_path, capsys, extra, code):
    path = tmp_path / "not-created.db"
    assert smoke.main(cli_args(path) + ["--allow-paid"] + extra) == 2
    assert not path.exists()
    assert json.loads(capsys.readouterr().out) == {"error_type": code, "executed": False}


def test_cli_timeout_options_do_not_bypass_optin(tmp_path, capsys):
    path = tmp_path / "not-created.db"
    assert smoke.main(cli_args(path) + ["--model-timeout-seconds", "120", "--timeout-ms", "300000"]) == 2
    assert not path.exists()
    assert json.loads(capsys.readouterr().out) == {"error_type": "paid_call_not_authorized", "executed": False}
