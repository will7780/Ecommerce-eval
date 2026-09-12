from __future__ import annotations

import asyncio
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import create_engine, inspect, select

from commerce_eval.providers import (
    CentralEnvStore, CredentialResolver, NativeCompatibleClient, ProviderConfigService,
    ProviderConfigVersionRow, ProviderError, build_provider_router, parse_usage,
)
from commerce_eval.providers.network import normalize_base_url
from commerce_eval.storage import Database, Repository


@pytest.fixture(autouse=True)
def never_real_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("COMMERCE_EVAL_DISABLE_CENTRAL_ENV", "1")
    monkeypatch.setenv("AGENT_API_ENV_FILE", str(tmp_path / "not-a-real-central-file.env"))
    for name in tuple(os.environ):
        if name.endswith("_API_KEY"):
            monkeypatch.delenv(name)


@pytest.fixture
def service(tmp_path):
    database = Database(tmp_path / "providers.db")
    database.initialize()
    store = CentralEnvStore(tmp_path / "central" / ".env", environ={})
    result = ProviderConfigService(Repository(database),
        credential_resolver=CredentialResolver(store, environ={}))
    yield result
    database.dispose()


def config(**changes):
    return {"provider_id": "deepseek", "kind": "deepseek", "name": "DeepSeek",
            "base_url": "https://api.deepseek.com", "model": "test-model",
            "credential_env": "DEEPSEEK_API_KEY", "enabled": True, "allow_localhost": False,
            "endpoint_confirmed": True, "expected_version": None, **changes}


def secret_fixture(label="central"):
    return "offline-" + label + "-" + "Q" * 20


def configure(service):
    row = service.save(config())
    service.set_credential("deepseek", {"version": row["version"], "secret": secret_fixture(),
        "expected_env_version": service.credentials.store.status()["version"], "acknowledge_shared": True})
    return row


async def public_dns(host, port):
    return ["93.184.216.34"]


def completion_response(**extras):
    return {"choices": [{"message": {"content": "OK", "role": "assistant"}}], **extras}


def test_configuration_is_immutable_nonsecret_and_network_free(service, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network_or_default_credential_access")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    assert len(service.list()["items"]) == 2
    first = service.save(config())
    assert first["version"] == 1 and not first["configured"]
    second = service.save(config(expected_version=1, model="different-model"))
    assert second["version"] == 2
    assert service.get("deepseek", 1)["model"] == "test-model"
    assert service.save(config(expected_version=2, model="different-model"))["version"] == 2
    with pytest.raises(ProviderError, match="provider_version_conflict"):
        service.save(config(expected_version=1, model="stale"))
    assert service.list()["items"][0]["last_check"] is None


def test_central_pointer_default_and_process_precedence(tmp_path):
    pointer = tmp_path / "shared.env"
    store = CentralEnvStore(environ={"AGENT_API_ENV_FILE": str(pointer)}, home=tmp_path, platform_name="nt")
    assert store.path == pointer and store.source == "pointer"
    fallback = CentralEnvStore(environ={}, home=tmp_path, platform_name="nt")
    assert fallback.path == tmp_path / "Desktop" / "api" / ".env"
    assert CentralEnvStore(environ={}, platform_name="posix").status()["error_type"] == "central_env_path_required"
    store.set_secret("DEEPSEEK_API_KEY", secret_fixture(), expected_version=store.status()["version"])
    assert CredentialResolver(store, environ={}).resolve("DEEPSEEK_API_KEY").source == "central_env"
    process = CredentialResolver(store, environ={"DEEPSEEK_API_KEY": secret_fixture("process")})
    resolved = process.resolve("DEEPSEEK_API_KEY")
    assert resolved.source == "process_env" and resolved.value.get_secret_value() == secret_fixture("process")
    assert secret_fixture("process") not in repr(resolved)
    empty_override = CredentialResolver(store, environ={"DEEPSEEK_API_KEY": ""}).resolve("DEEPSEEK_API_KEY")
    assert not empty_override.configured and empty_override.source == "process_env"


def test_atomic_write_preserves_unrelated_bindings_and_leaves_no_backup(service):
    store = service.credentials.store
    store.path.parent.mkdir()
    before = "# keep comment\r\nexport OTHER_VALUE=\"line one\nline two\"\r\nUNRELATED='x=y#z'\r\n"
    store.path.write_bytes(before.encode())
    permissions = stat.S_IMODE(store.path.stat().st_mode)
    result = store.set_secret("DEEPSEEK_API_KEY", secret_fixture(), expected_version=store.status()["version"])
    assert store.path.read_bytes().startswith(before.encode())
    assert stat.S_IMODE(store.path.stat().st_mode) == permissions
    assert result["available"] and secret_fixture() not in json.dumps(result)
    assert {path.name for path in store.path.parent.iterdir()} <= {".env", ".env.lock"}
    second = store.set_secret("DEEPSEEK_API_KEY", secret_fixture("rotated"), expected_version=result["version"])
    assert second["version"] != result["version"]
    assert store.path.read_text().count("DEEPSEEK_API_KEY=") == 1


def test_concurrent_env_rotation_has_exactly_one_winner(service):
    store = service.credentials.store
    store.path.parent.mkdir()
    version = store.status()["version"]

    def save(index):
        try:
            store.set_secret("DEEPSEEK_API_KEY", secret_fixture(str(index)), expected_version=version)
            return "saved"
        except ProviderError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [1, 2]))
    assert sorted(results) == ["central_env_version_conflict", "saved"]


def test_permission_failure_does_not_create_fallback_secret_file(service, monkeypatch):
    from commerce_eval.providers import credentials

    configure(service)
    store = service.credentials.store
    before = store.path.read_bytes()

    def denied(*args):
        raise PermissionError(secret_fixture("must-not-escape"))

    monkeypatch.setattr(credentials, "_replace_preserving_permissions", denied)
    with pytest.raises(ProviderError, match="central_env_write_failed") as error:
        store.set_secret("DEEPSEEK_API_KEY", secret_fixture("new"), expected_version=store.status()["version"])
    assert store.path.read_bytes() == before
    assert "must-not-escape" not in str(error.value)
    assert not list(store.path.parent.glob(".env-write-*"))


@pytest.mark.parametrize("raw", ["BROKEN='unterminated", "OTHER=1\nOTHER=2\n"])
def test_invalid_env_is_not_silently_rewritten(service, raw):
    store = service.credentials.store
    store.path.parent.mkdir()
    store.path.write_text(raw)
    assert store.status()["error_type"] == "central_env_invalid"
    assert store.path.read_text() == raw


def test_linked_central_file_is_rejected(service, tmp_path):
    actual = tmp_path / "actual.env"
    actual.write_text("OTHER=unchanged\n")
    link = tmp_path / "linked.env"
    try:
        link.symlink_to(actual)
    except OSError:
        pytest.skip("symlink creation unavailable")
    store = CentralEnvStore(link, environ={})
    assert store.status()["error_type"] == "central_env_link_forbidden"
    with pytest.raises(ProviderError, match="central_env_link_forbidden"):
        store.set_secret("DEEPSEEK_API_KEY", secret_fixture(), expected_version="old")
    assert actual.read_text() == "OTHER=unchanged\n"


def test_credential_write_is_acknowledged_version_bound_and_not_in_database(service):
    saved = service.save(config())
    payload = {"version": 1, "secret": secret_fixture(),
               "expected_env_version": service.credentials.store.status()["version"]}
    with pytest.raises(ProviderError, match="acknowledgement"):
        service.set_credential("deepseek", payload)
    public = service.set_credential("deepseek", {**payload, "acknowledge_shared": True})
    assert public["configured"] and secret_fixture() not in json.dumps(public)
    assert secret_fixture() not in json.dumps(service.list())
    with service.database.engine.connect() as connection:
        payloads = connection.execute(select(ProviderConfigVersionRow.payload_json)).scalars().all()
    assert secret_fixture() not in json.dumps(payloads)
    service.save(config(expected_version=saved["version"], enabled=False))
    assert service.credentials.resolve("DEEPSEEK_API_KEY").configured
    with pytest.raises(ProviderError, match="provider_disabled"):
        service.require_active("deepseek", 1)


@pytest.mark.parametrize("field,value", [
    ("name", "token=" + "never-store-value"),
    ("model", "sk-" + "test-value-only-123456"),
    ("credential_env", "AGENT_API_ENV_FILE"),
    ("credential_env", "OTHER_API_KEY"),
    ("base_url", "https://user:password@example.com"),
])
def test_sensitive_or_dangerous_config_fields_never_persist(service, field, value):
    with pytest.raises(ProviderError):
        service.save(config(**{field: value}))
    with service.database.sessions() as session:
        assert not session.scalars(select(ProviderConfigVersionRow)).all()


@pytest.mark.parametrize("url", ["http://api.example.com", "https://169.254.169.254", "https://10.1.1.1",
    "https://metadata.google.internal", "https://127.0.0.1", "https://example.com?q=secret",
    "https://example.com/%2e%2e/", "https://example.com/../", "https://example.com/chat/completions"])
def test_endpoint_policy_rejects_metadata_private_and_ambiguous_urls(url):
    with pytest.raises(ProviderError):
        normalize_base_url(url)
    assert normalize_base_url("http://127.0.0.1:8779/v1/", allow_localhost=True) == "http://127.0.0.1:8779/v1"


def app_for(service):
    app = FastAPI()
    app.include_router(build_provider_router(service.database, service=service))
    return app


async def csrf_headers(client):
    result = await client.get("/api/v1/providers/csrf")
    assert result.status_code == 200
    return {"Origin": "http://127.0.0.1:8770", "X-CSRF-Token": result.json()["csrf_token"]}


async def test_api_write_only_flow_csrf_and_sanitized_schema_errors(service):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(service), client=("127.0.0.1", 5000)),
                                 base_url="http://127.0.0.1:8770") as client:
        assert (await client.get("/api/v1/providers")).status_code == 200
        assert (await client.post("/api/v1/providers", json=config())).status_code == 403
        headers = await csrf_headers(client)
        response = await client.post("/api/v1/providers", json=config(), headers=headers)
        assert response.status_code == 200 and response.json()["version"] == 1
        state = (await client.get("/api/v1/providers")).json()["central_env"]
        payload = {"version": 1, "secret": secret_fixture(), "expected_env_version": state["version"],
                   "acknowledge_shared": True}
        response = await client.post("/api/v1/providers/deepseek/credential", json=payload, headers=headers)
        assert response.status_code == 200 and response.json()["configured"]
        assert response.headers["cache-control"] == "no-store"
        assert secret_fixture() not in response.text
        response = await client.post("/api/v1/providers/deepseek/credential",
                                    json={**payload, "extra": secret_fixture()}, headers=headers)
        assert response.status_code == 422 and secret_fixture() not in response.text
        bad_origin = {**headers, "Origin": "https://malicious.example"}
        assert (await client.post("/api/v1/providers", json=config(), headers=bad_origin)).status_code == 403
        assert (await client.post("/api/v1/providers", json=config(), headers={**headers, "X-CSRF-Token": "invalid"})).status_code == 403
        assert (await client.post("/api/v1/providers/deepseek/check", json={"version": 1, "allow_paid": False}, headers=headers)).status_code == 403


@pytest.mark.parametrize("address,host", [("198.51.100.10", "127.0.0.1"), ("127.0.0.1", "rebound.example")])
async def test_remote_and_dns_rebinding_cannot_obtain_management_token(service, address, host):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(service), client=(address, 5000)),
                                 base_url=f"http://{host}:8770") as client:
        response = await client.get("/api/v1/providers/csrf")
        assert response.status_code == 403
        assert not response.cookies


async def test_native_client_requires_paid_opt_in_and_pins_config_model(service):
    configure(service)
    seen = []

    def transport(request):
        seen.append(request)
        return httpx.Response(200, json=completion_response())

    client = NativeCompatibleClient(service, provider_id="deepseek", version=1,
                                    transport=httpx.MockTransport(transport), dns_resolver=public_dns)
    with pytest.raises(ProviderError, match="paid_call_not_authorized"):
        await client.complete([{"role": "user", "content": "hi"}], [])
    assert not seen
    service.save(config(expected_version=1, model="new-model", base_url="https://new.example/v1"))
    client.allow_paid = True
    result = await client.complete([{"role": "user", "content": "hi"}], [])
    assert json.loads(seen[0].content)["model"] == "test-model"
    assert seen[0].headers["host"] == "api.deepseek.com:443"
    assert str(seen[0].url) == "https://93.184.216.34/chat/completions"
    assert seen[0].extensions["sni_hostname"] == "api.deepseek.com"
    assert result["usage"] == dict.fromkeys(parse_usage(None))


async def test_native_normalizes_tool_calls_usage_and_discards_hidden_reasoning(service):
    configure(service)
    hidden = "hidden-deliberation-marker"
    payload = {"choices": [{"message": {"role": "assistant", "content": "<think>" + hidden + "</think>Done " + secret_fixture(),
        "reasoning_content": hidden, "tool_calls": [{"id": "call-1", "type": "function", "function": {
            "name": "file.write", "arguments": json.dumps({"path": "goods.json", "content": "hello"})}}]}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18,
                  "completion_tokens_details": {"reasoning_tokens": 3},
                  "prompt_cache_hit_tokens": 4, "prompt_cache_miss_tokens": 6}}
    client = NativeCompatibleClient(service, provider_id="deepseek", version=1, allow_paid=True,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)), dns_resolver=public_dns)
    result = await client.complete([{"role": "user", "content": "write"}], [{"type": "function", "function": {"name": "file.write"}}])
    assert result["tool_calls"] == [{"id": "call-1", "name": "file.write", "arguments": {"path": "goods.json", "content": "hello"}}]
    assert result["usage"] == {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18,
                               "reasoning_tokens": 3, "cache_hit_tokens": 4, "cache_miss_tokens": 6}
    assert result["latency_ms"] >= 0
    assert hidden not in json.dumps(result) and secret_fixture() not in json.dumps(result)


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": True, "total_tokens": -1}, {"completion_tokens": "12"}])
def test_missing_or_invalid_usage_is_null_not_zero(usage):
    assert all(value is None for value in parse_usage(usage).values())
    assert parse_usage({"prompt_tokens": 0})["prompt_tokens"] == 0
    assert parse_usage({"prompt_tokens_details": {"cached_tokens": 7}})["cache_hit_tokens"] == 7
    assert parse_usage({"prompt_tokens": 10, "completion_tokens": 5})["total_tokens"] is None


@pytest.mark.parametrize("status,expected", [(401, "provider_authentication_denied"), (403, "provider_permission_denied"),
    (302, "provider_redirect_refused"), (429, "provider_rate_limited"), (503, "provider_backend_error")])
async def test_http_error_priority_redirects_and_remote_secret_bodies(service, status, expected):
    configure(service)
    seen = []

    def transport(request):
        seen.append(request)
        return httpx.Response(status, json={"error": secret_fixture()}, headers={"Location": "https://other.example"})

    service.transport = httpx.MockTransport(transport)
    service.dns_resolver = public_dns
    result = await service.check("deepseek", {"version": 1, "allow_paid": True})
    assert result["error_type"] == expected and len(seen) == 1
    assert secret_fixture() not in json.dumps(result)
    assert secret_fixture() not in json.dumps(service.list())


async def test_dns_is_validated_before_credentials_are_sent(service):
    configure(service)
    called = []

    async def malicious_dns(host, port):
        return ["93.184.216.34", "169.254.169.254"]

    client = NativeCompatibleClient(service, provider_id="deepseek", version=1, allow_paid=True,
        transport=httpx.MockTransport(lambda request: called.append(request)), dns_resolver=malicious_dns)
    with pytest.raises(ProviderError, match="provider_address_forbidden"):
        await client.complete([{"role": "user", "content": "hello"}])
    assert not called


async def test_bounded_timeout_and_concurrent_request_budget(service):
    configure(service)
    calls = []

    async def slow(request):
        calls.append(request)
        await asyncio.sleep(.1)
        return httpx.Response(200, json=completion_response())

    client = NativeCompatibleClient(service, provider_id="deepseek", version=1, allow_paid=True,
        transport=httpx.MockTransport(slow), dns_resolver=public_dns, timeout_seconds=.02, max_calls=1)
    results = await asyncio.gather(*[client.complete([{"role": "user", "content": "hello"}]) for _ in range(2)],
                                   return_exceptions=True)
    assert {result.code for result in results} == {"provider_timeout", "provider_call_budget_exhausted"}
    assert len(calls) == 1 and client.call_count == 1


async def test_explicit_tiny_check_succeeds_and_records_only_public_status(service):
    configure(service)
    seen = []

    def transport(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=completion_response())

    service.transport = httpx.MockTransport(transport)
    service.dns_resolver = public_dns
    result = await service.check("deepseek", {"version": 1, "allow_paid": True, "model": "manual-model"})
    assert result["status"] == "connected"
    assert seen[0]["max_tokens"] == 8 and seen[0]["model"] == "manual-model"
    assert len(seen) == 1
    assert service.list()["items"][0]["last_check"]["status"] == "connected"


async def test_native_client_sanitizes_ordinary_transport_exceptions(service):
    configure(service)

    def fail(request):
        raise RuntimeError(secret_fixture())

    client = NativeCompatibleClient(service, provider_id="deepseek", version=1, allow_paid=True,
        transport=httpx.MockTransport(fail), dns_resolver=public_dns)
    with pytest.raises(ProviderError, match="provider_disconnected") as error:
        await client.complete([{"role": "user", "content": "hello"}])
    assert secret_fixture() not in str(error.value)


def test_provider_migration_is_additive_and_registered(tmp_path):
    root = Path(__file__).resolve().parents[1]
    path = tmp_path / "migrated.db"
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    command.upgrade(cfg, "0002_onboarding")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS provider_checks")
        connection.exec_driver_sql("DROP TABLE IF EXISTS provider_config_versions")
        connection.exec_driver_sql("INSERT INTO projects(project_id,name,description,created_at) VALUES ('old','Old','Preserved','2026-01-01')")
    command.upgrade(cfg, "0004_provider_configs")
    assert {"provider_config_versions", "provider_checks"} <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT name FROM projects WHERE project_id='old'").scalar() == "Old"
    engine.dispose()


@pytest.mark.skipif(os.name != "nt", reason="Windows DACL preservation")
def test_windows_replacement_preserves_actual_dacl(service):
    import ctypes
    from ctypes import wintypes

    get_security = ctypes.WinDLL("advapi32", use_last_error=True).GetFileSecurityW
    get_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    get_security.restype = wintypes.BOOL
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    get_dacl = advapi.GetSecurityDescriptorDacl
    get_dacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    get_dacl.restype = wintypes.BOOL

    def dacl(path):
        size = wintypes.DWORD()
        get_security(str(path), 4, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        assert get_security(str(path), 4, buffer, size, ctypes.byref(size))
        present, defaulted, acl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        assert get_dacl(buffer, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted))
        assert present.value and acl.value
        header = ctypes.string_at(acl.value, 8)
        acl_size = int.from_bytes(header[2:4], "little")
        protected = bool(int.from_bytes(buffer.raw[2:4], "little") & 0x1000)
        return protected, ctypes.string_at(acl.value, acl_size)

    configure(service)
    store = service.credentials.store
    original = dacl(store.path)
    store.set_secret("DEEPSEEK_API_KEY", secret_fixture("new"), expected_version=store.status()["version"])
    assert dacl(store.path) == original


def test_unconfirmed_endpoint_cannot_receive_credentials_or_requests(service):
    service.save(config(endpoint_confirmed=False))
    with pytest.raises(ProviderError, match="provider_endpoint_not_confirmed"):
        service.set_credential("deepseek", {"version": 1, "secret": secret_fixture(),
            "expected_env_version": service.credentials.store.status()["version"], "acknowledge_shared": True})
    assert not service.credentials.store.path.exists()


async def test_explicit_synthetic_loopback_is_allowed_and_must_resolve_locally(service):
    service.save(config(provider_id="local-test", kind="custom", credential_env="SYNTHETIC_API_KEY",
                        base_url="http://127.0.0.1:8990/v1", allow_localhost=True))
    store = service.credentials.store
    store.set_secret("SYNTHETIC_API_KEY", secret_fixture(), expected_version=store.status()["version"])
    seen = []

    async def local_dns(host, port):
        return ["127.0.0.1"]

    def transport(request):
        seen.append(request)
        return httpx.Response(200, json=completion_response())

    client = NativeCompatibleClient(service, provider_id="local-test", version=1, allow_paid=True,
        transport=httpx.MockTransport(transport), dns_resolver=local_dns)
    assert (await client.complete([{"role": "user", "content": "test"}]))["content"] == "OK"
    client.dns_resolver = public_dns
    with pytest.raises(ProviderError, match="provider_address_forbidden"):
        await client.complete([{"role": "user", "content": "test"}])
    assert len(seen) == 1


@pytest.mark.parametrize("payload", [b'{"choices":[],"secret":"value"}', b'not-json',
    b'{"choices":[{"message":{"content":1}}]}',
    b'{"choices":[{"message":{"tool_calls":[{"id":"x","function":{"name":"file.write","arguments":"not json"}}]}}]}',
    b'{"choices":[{"message":{"content":"first","content":"second"}}]}'])
async def test_invalid_model_responses_are_bounded_public_failures(service, payload):
    configure(service)
    client = NativeCompatibleClient(service, provider_id="deepseek", version=1, allow_paid=True,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=payload)), dns_resolver=public_dns)
    with pytest.raises(ProviderError, match="provider_invalid_response"):
        await client.complete([{"role": "user", "content": "hello"}])


async def test_response_size_limits_and_csrf_expiration(service):
    from commerce_eval.providers.api import ProviderCSRF
    from starlette.requests import Request

    configure(service)
    client = NativeCompatibleClient(service, provider_id="deepseek", version=1, allow_paid=True,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"", headers={"Content-Length": str(3 * 1024 * 1024)})),
        dns_resolver=public_dns)
    with pytest.raises(ProviderError, match="provider_response_too_large"):
        await client.complete([{"role": "user", "content": "hello"}])
    now = [10000]
    csrf = ProviderCSRF(clock=lambda: now[0])
    scope = {"type": "http", "method": "GET", "path": "/api/v1/providers/csrf", "scheme": "http",
             "server": ("127.0.0.1", 8770), "client": ("127.0.0.1", 6000),
             "headers": [(b"host", b"127.0.0.1:8770")]}
    token = json.loads(csrf.issue(Request(scope)).body)["csrf_token"]
    scope["headers"] += [(b"origin", b"http://127.0.0.1:8770"), (b"x-csrf-token", token.encode()),
                         (b"cookie", ("commerce_provider_csrf=" + token).encode())]
    csrf.verify(Request(scope))
    now[0] += 1801
    with pytest.raises(ProviderError, match="provider_csrf_invalid"):
        csrf.verify(Request(scope))
