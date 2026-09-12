from __future__ import annotations

import json
from pathlib import Path

from commerce_eval.cli import main
from commerce_eval.contracts import MetricResultV1
from commerce_eval.packs import available_evaluators
from commerce_eval.packs.base import FunctionalMetricEvaluator
from commerce_eval.storage import Database, Repository


ROOT = Path(__file__).resolve().parents[1]


def test_demo_seed_only_creates_complete_offline_project(tmp_path, capsys) -> None:
    database_path = tmp_path / "demo.db"
    assert main(["--database", str(database_path), "demo", "--seed-only"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready"
    assert payload["url"] == "http://127.0.0.1:8770"
    repository = Repository(Database(database_path))
    assert repository.get_project("commerce-demo")["project_id"] == "commerce-demo"
    traces = [repository.get_trace(item["trace_id"])["trace"] for item in repository.list_traces(project_id="commerce-demo")]
    assert len(traces) >= 2
    assert all(trace["tool_contract_set_id"] == "default" for trace in traces)
    events = [event for trace in traces for event in trace["events"]]
    assert any(event["kind"] == "interaction.request" for event in events)
    failed_calls = [event for event in events if event["kind"] == "tool.call" and event["status"] == "error"]
    assert failed_calls
    assert any(
        event["kind"] == "model.call" and event["sequence"] > failed_calls[0]["sequence"]
        for event in next(trace["events"] for trace in traces if failed_calls[0] in trace["events"])
    )


def test_cli_imports_versioned_dataset_and_tool_contracts(tmp_path, capsys) -> None:
    database_path = tmp_path / "imports.db"
    dataset_path = ROOT / "examples" / "dataset.jsonl"
    tool_path = ROOT / "examples" / "tool-contracts.json"
    assert main(
        [
            "--database",
            str(database_path),
            "import",
            str(dataset_path),
            "--kind",
            "dataset",
            "--project",
            "imported",
            "--id",
            "cases",
            "--version",
            "1.0.0",
        ]
    ) == 0
    assert main(
        [
            "--database",
            str(database_path),
            "import",
            str(tool_path),
            "--kind",
            "tool-contracts",
            "--project",
            "imported",
        ]
    ) == 0
    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["kind"] for row in outputs] == ["dataset", "tool-contracts"]
    repository = Repository(Database(database_path))
    assert repository.get_dataset("imported", "cases", "1.0.0")["case_count"] == 3
    assert len(repository.get_tool_contracts("imported", "commerce-demo-tools", "1.0.0")) == 4


def test_cli_validate_supports_target_contract(tmp_path, capsys) -> None:
    path = tmp_path / "target.json"
    path.write_text(
        json.dumps(
            {
                "target_id": "agent",
                "version": "1",
                "name": "Agent",
                "adapter_type": "http",
                "safe_for_eval": True,
                "config": {"base_url": "http://127.0.0.1:9000"},
            }
        ),
        encoding="utf-8",
    )
    assert main(["validate", str(path), "--kind", "target"]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1


def test_metric_pack_entry_point_is_discovered(monkeypatch) -> None:
    evaluator = FunctionalMetricEvaluator(
        "third_party_metric",
        "extension",
        lambda _context: MetricResultV1(metric_id="third_party_metric", group="extension", status="pass", value=True),
    )

    class Point:
        name = "test-pack"

        @staticmethod
        def load():
            return lambda: [evaluator]

    class Points(list):
        def select(self, *, group):
            return [Point()] if group == "commerce_eval.metric_packs" else []

    monkeypatch.setattr("commerce_eval.core.registry.metadata.entry_points", lambda: Points())
    assert "third_party_metric" in {item.metric_id for item in available_evaluators()}
