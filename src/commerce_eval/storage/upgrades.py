"""Idempotent SQLite upgrade shared by packaged startup and Alembic."""

from sqlalchemy import inspect, select

from commerce_eval.core import content_checksum, redact_recursive

from .models import Base, EvaluationRow, EvaluationMetricRow, EvaluationGateRow


def upgrade_onboarding(connection) -> None:
    Base.metadata.create_all(connection)
    for table in ("metric_results", "gate_results"):
        columns = {column["name"] for column in inspect(connection).get_columns(table)}
        if "evaluation_id" not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN evaluation_id VARCHAR(160) REFERENCES evaluations(evaluation_id)"
            )
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_evaluation_id ON {table} (evaluation_id)"
        )
    runs = Base.metadata.tables["runs"]
    metrics = Base.metadata.tables["metric_results"]
    gates = Base.metadata.tables["gate_results"]
    for run in connection.execute(select(runs)).mappings():
        old_metrics = list(connection.execute(select(metrics).where(
            metrics.c.trace_id == run["trace_id"], metrics.c.evaluation_id.is_(None)
        )).mappings())
        old_gates = list(connection.execute(select(gates).where(
            gates.c.trace_id == run["trace_id"], gates.c.evaluation_id.is_(None)
        )).mappings())
        if not old_metrics and not old_gates:
            continue
        evaluation_id = "legacy_" + content_checksum(run["trace_id"])[:40]
        if not connection.execute(select(EvaluationRow.evaluation_id).where(
            EvaluationRow.evaluation_id == evaluation_id
        )).first():
            payload = {
                "trace_id": run["trace_id"], "case_id": run["case_id"],
                "metric_results": [redact_recursive(row["payload_json"]) for row in old_metrics],
                "gate_results": [redact_recursive(row["payload_json"]) for row in old_gates],
                "overall_pass": run["overall_pass"],
                "gate_failures": [row["metric_id"] for row in old_gates if not row["passed"]],
            }
            connection.execute(EvaluationRow.__table__.insert().values(
                evaluation_id=evaluation_id, trace_id=run["trace_id"], project_id=run["project_id"],
                binding_json={"source": "legacy_backfill", **run["versions_json"]},
                payload_json=payload, checksum=content_checksum(payload),
            ))
            for model, rows in ((EvaluationMetricRow, old_metrics), (EvaluationGateRow, old_gates)):
                for index, row in enumerate(rows):
                    connection.execute(model.__table__.insert().values(
                        uid=f"{evaluation_id}::{index}", evaluation_id=evaluation_id,
                        metric_id=row["metric_id"], payload_json=redact_recursive(row["payload_json"]),
                    ))
        for table in (metrics, gates):
            connection.execute(table.update().where(
                table.c.trace_id == run["trace_id"], table.c.evaluation_id.is_(None)
            ).values(evaluation_id=evaluation_id))
