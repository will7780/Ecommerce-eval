from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from commerce_eval.storage import Database


ROOT = Path(__file__).resolve().parents[1]


def test_alembic_initial_migration_creates_platform_schema(tmp_path) -> None:
    path = tmp_path / "migrated.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert {
        "alembic_version",
        "projects",
        "dataset_versions",
        "target_versions",
        "tool_contract_versions",
        "evaluator_set_versions",
        "experiments",
        "runs",
        "trace_events",
        "metric_results",
        "gate_results",
        "annotations",
        "provider_config_versions",
        "business_evidence",
    } <= tables


def test_database_enables_wal_and_foreign_keys(tmp_path) -> None:
    database = Database(tmp_path / "wal.db")
    database.initialize()
    with database.engine.connect() as connection:
        assert str(connection.exec_driver_sql("PRAGMA journal_mode").scalar()).lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    database.dispose()
