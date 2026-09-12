from __future__ import annotations

import asyncio
import json
import socket

import httpx
import pytest

from commerce_eval.contracts import EvalCaseV1, TargetDefinitionV1, TraceEnvelopeV1
from commerce_eval.services.onboarding import OnboardingService
from commerce_eval.storage import Database, Repository


def test_connection_probe_pins_ip_refuses_redirect_without_reading_body(tmp_path, monkeypatch):
    database = Database(tmp_path / "probe.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("p", "Project")
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/"})

    async def run():
        loop = asyncio.get_running_loop()

        async def lookup(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 9010))]

        monkeypatch.setattr(loop, "getaddrinfo", lookup)
        service = OnboardingService(repository, transport=httpx.MockTransport(handle))
        target = TargetDefinitionV1(target_id="t", version="1", name="Target", adapter_type="http", safe_for_eval=True,
                                    config={"base_url": "http://localhost:9010"})
        response = await service.check("p", definition=target.model_dump())
        assert response["checks"][0]["code"] == "target_redirect_refused"
        assert (seen[0].url.host, seen[0].url.port) == ("127.0.0.1", 9010)
        assert seen[0].url.path == "/v1/capabilities" and seen[0].headers["host"] == "localhost:9010"
        assert len(seen) == 1
        seen.clear()
        target.config["base_url"] = "http://unexpected.example:9010"
        blocked = await service.check("p", definition=target.model_dump())
        assert blocked["checks"][0]["code"] == "target_address_forbidden"
        assert seen == []

    asyncio.run(run())
    database.dispose()


def test_cli_import_unscored_then_explicit_eval_and_local_registration(tmp_path, capsys, monkeypatch):
    from commerce_eval.cli import main

    monkeypatch.setenv("AGENT_API_ENV_FILE", str(tmp_path / "disabled.env"))
    path = tmp_path / "platform.db"
    database = Database(path)
    database.initialize()
    repository = Repository(database)
    repository.create_project("p", "Project")
    repository.save_dataset("p", "cases", "1", "Cases", [EvalCaseV1(case_id="case", name="Case")])
    repository.save_tool_contract_set("p", "tools", "1", [])
    repository.save_evaluator_set("p", "metrics", "1", ["task_completion"])
    source = tmp_path / "trace.json"
    source.write_text(TraceEnvelopeV1(trace_id="trace", project_id="p", target_id="external", target_version="1").model_dump_json(), encoding="utf-8")
    args = ["--database", str(path), "import", str(source)]
    assert main(args) == 0
    assert repository.get_trace("trace")["evaluation_history"] == []
    assert main([*args, "--eval", "--dataset", "cases", "--dataset-version", "1", "--case-id", "case",
                 "--tool-contract-set", "tools", "--tool-contract-version", "1",
                 "--evaluator-set", "metrics", "--evaluator-set-version", "1"]) == 0
    assert len(repository.get_trace("trace")["evaluation_history"]) == 1
    definition = TargetDefinitionV1(target_id="local", version="1", name="Local", adapter_type="python", safe_for_eval=True,
                                     config={"command": ["$PYTHON", "-m", "commerce_eval.demo_runtime"], "execution_mode": "dry_run"})
    source = tmp_path / "target.json"
    source.write_text(definition.model_dump_json(), encoding="utf-8")
    assert main(["--database", str(path), "import", str(source), "--kind", "target", "--project", "p"]) == 0
    assert repository.get_target("p", "local", "1").config["command"] == definition.config["command"]
    assert repository.list_experiments() == []
    database.dispose()


def test_cli_errors_do_not_print_untrusted_content(tmp_path, capsys):
    from commerce_eval.cli import main

    path = tmp_path / "broken.json"
    marker = "do-not-" + "echo-this"
    path.write_text(marker, encoding="utf-8")
    assert main(["--database", str(tmp_path / "p.db"), "import", str(path)]) == 1
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err
