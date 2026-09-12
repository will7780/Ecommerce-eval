from __future__ import annotations

import asyncio
import json
import socket

import httpx
import pytest

from commerce_eval.contracts import TargetDefinitionV1
from commerce_eval.services.onboarding import OnboardingService
from commerce_eval.storage import Database, Repository


@pytest.fixture
def repository(tmp_path):
    database = Database(tmp_path / "capabilities.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("p", "Project")
    yield repository
    database.dispose()


def capabilities(**overrides):
    return {"protocol_version": "1.0", "operations": ["start", "resume", "reset"], "safe_for_eval": True, **overrides}


@pytest.mark.parametrize("payload,expected", [
    (capabilities(protocol_version=1), "target_connected"),
    (capabilities(protocol_version="1"), "target_connected"),
    (capabilities(protocol_version="1.1"), "target_connected"),
    (capabilities(protocol_version="2"), "target_protocol_unsupported"),
    (capabilities(protocol_version=True), "target_protocol_unsupported"),
    (capabilities(operations=["start"]), "target_operations_missing"),
    (capabilities(operations="start resume"), "target_operations_missing"),
    (capabilities(safe_for_eval=False), "target_not_safe_for_eval"),
    (capabilities(safe_for_eval="true"), "target_not_safe_for_eval"),
    ({}, "target_protocol_unsupported"),
    ([], "target_capabilities_invalid"),
])
def test_ready_requires_actual_supported_safe_capabilities(repository, monkeypatch, payload, expected):
    async def run():
        async def lookup(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 9000))]

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
        def handle(request):
            assert request.method == "GET"
            assert request.url.path == "/v1/capabilities"
            return httpx.Response(200, json=payload)

        service = OnboardingService(repository, transport=httpx.MockTransport(handle))
        definition = TargetDefinitionV1(target_id="t", version="1", name="Target", adapter_type="http", safe_for_eval=True,
                                         config={"base_url": "http://localhost:9000"})
        result = await service.check("p", definition=definition.model_dump())
        assert result["checks"][0]["code"] == expected
        assert result["status"] == ("ready" if expected == "target_connected" else "invalid")
        assert result["executed"] is False

    asyncio.run(run())


@pytest.mark.parametrize("content,headers,expected", [
    (b"<html>Welcome</html>", {"content-type": "text/html"}, "target_capabilities_invalid"),
    (b"not json", {"content-type": "application/json"}, "target_capabilities_invalid"),
    (b" " * (65536 + 1), {}, "target_capabilities_too_large"),
    (b'{}', {"content-length": "1000000"}, "target_capabilities_too_large"),
    (b'{}', {"content-encoding": "gzip"}, "target_capabilities_invalid"),
    (b'{"safe_for_eval":false,"safe_for_eval":true}', {}, "target_capabilities_invalid"),
], ids=["html", "invalid-json", "stream-limit", "length-limit", "compressed", "duplicate-key"])
def test_probe_body_is_bounded_json(repository, monkeypatch, content, headers, expected):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for offset in range(0, len(content), 1024):
                yield content[offset:offset + 1024]

    async def run():
        async def lookup(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 9000))]

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
        service = OnboardingService(repository, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers=headers, stream=Stream())
        ))
        result = await service.check("p", definition={"target_id": "t", "version": "1", "name": "Target",
                                                     "adapter_type": "http", "safe_for_eval": True,
                                                     "config": {"base_url": "http://localhost:9000"}})
        assert result["status"] == "invalid"
        assert result["checks"][0]["code"] == expected

    asyncio.run(run())


def test_registered_local_safety_is_checked_without_execution(repository, monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError("network must not run for a local target")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    for version, safe, mode in (("1", False, "dry_run"), ("2", True, "production"), ("3", True, "sandbox")):
        repository.save_target("p", TargetDefinitionV1(target_id="local", version=version, name="Local", adapter_type="python",
                               safe_for_eval=safe, config={"command": ["$PYTHON", "-m", "commerce_eval.demo_runtime"], "execution_mode": mode}))
        result = asyncio.run(OnboardingService(repository).check("p", "local", version))
        assert result["status"] == ("ready" if version == "3" else "invalid")
        assert result["executed"] is False
