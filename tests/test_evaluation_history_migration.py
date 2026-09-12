from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from commerce_eval.contracts import EvaluationResultV1, TraceEnvelopeV1
from commerce_eval.storage import Database, Repository
from commerce_eval.storage.models import Base, EvaluationRow, MetricResultRow, GateResultRow


def test_legacy_sqlite_backfill_preserves_metrics_gates_and_is_repeatable(tmp_path):
    database = Database(tmp_path / "legacy.db")
    with database.engine.begin() as connection:
        connection.exec_driver_sql("""CREATE TABLE metric_results (
            uid VARCHAR(360) PRIMARY KEY, trace_id VARCHAR(160) REFERENCES runs(trace_id),
            metric_id VARCHAR(160), group_name VARCHAR(80), status VARCHAR(20),
            numeric_value FLOAT, payload_json JSON, UNIQUE(trace_id, metric_id))""")
        connection.exec_driver_sql("""CREATE TABLE gate_results (
            uid VARCHAR(360) PRIMARY KEY, trace_id VARCHAR(160) REFERENCES runs(trace_id),
            metric_id VARCHAR(160), passed BOOLEAN, payload_json JSON)""")
        Base.metadata.create_all(connection)
    repository = Repository(database)
    repository.create_project("p", "Project")
    repository.save_trace(TraceEnvelopeV1(trace_id="old", project_id="p", target_id="t", target_version="1",
                                           started_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    old_metric = {"metric_id": "task_completion", "group": "core", "status": "fail", "value": False}
    old_gate = {"metric_id": "task_completion", "passed": False, "operator": "equals", "expected": True,
                "actual": False, "reason_code": "gate_failed"}
    with database.engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO metric_results VALUES (?, ?, ?, ?, ?, ?, ?)",
                                   ("old::metric", "old", "task_completion", "core", "fail", None, json.dumps(old_metric)))
        connection.exec_driver_sql("INSERT INTO gate_results VALUES (?, ?, ?, ?, ?)",
                                   ("old::gate", "old", "task_completion", False, json.dumps(old_gate)))
        connection.exec_driver_sql("UPDATE runs SET overall_pass=0 WHERE trace_id='old'")
    database.initialize()
    first = repository.get_trace("old")
    assert len(first["evaluation_history"]) == 1
    legacy = first["evaluation_history"][0]
    assert legacy["binding"]["source"] == "legacy_backfill"
    assert legacy["metric_results"] == [old_metric]
    assert legacy["gate_results"] == [old_gate]
    with database.sessions() as session:
        assert session.scalars(select(MetricResultRow)).one().evaluation_id == legacy["evaluation_id"]
        assert session.scalars(select(GateResultRow)).one().evaluation_id == legacy["evaluation_id"]
    result = EvaluationResultV1(trace_id="old", case_id="case", metric_results=[], gate_results=[], overall_pass=True)
    new_id = repository.save_evaluation(result)
    database.initialize()
    database.initialize()
    history = repository.get_trace("old")["evaluation_history"]
    assert len(history) == 2
    assert history[0] == legacy
    assert repository.get_evaluation(new_id)["overall_pass"] is True
    database.dispose()


def test_legacy_runner_save_evaluation_always_appends(tmp_path):
    database = Database(tmp_path / "history.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("p", "Project")
    repository.save_trace(TraceEnvelopeV1(trace_id="t", project_id="p", target_id="target", target_version="1"))
    result = EvaluationResultV1(trace_id="t", case_id="c", metric_results=[], gate_results=[], overall_pass=False)
    first = repository.save_evaluation(result)
    second = repository.save_evaluation(result.model_copy(update={"overall_pass": True}))
    assert first != second
    assert repository.get_evaluation(first)["overall_pass"] is False
    assert repository.get_trace("t")["overall_pass"] is True
    assert len(repository.evaluation_history("t")) == 2
    database.dispose()
