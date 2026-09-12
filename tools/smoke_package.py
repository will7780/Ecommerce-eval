"""Installed-wheel smoke and non-destructive legacy database migration check."""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from commerce_eval import __version__
from commerce_eval.api import create_app
from commerce_eval.demo import seed_demo
from commerce_eval.scenarios import compile_scenario, load_scenario_templates
from commerce_eval.storage import Database, Repository


def immutable_rows(path):
    with sqlite3.connect(path) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for table in ("target_versions", "tool_contract_versions", "dataset_versions", "eval_cases", "evaluator_set_versions")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-source", type=Path)
    parser.add_argument("--migration-copy", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="commerce-wheel-") as temporary:
        database = Database(Path(temporary) / "new.db")
        database.initialize()
        repository = Repository(database)
        seeded = seed_demo(repository)
        cases = load_scenario_templates()
        assert len(cases) == 32
        assert all(compile_scenario(case).contract_version == "1.1" for case in cases)
        assert repository.get_dataset("commerce-demo", "commerce-standard-bank", "0.2.0")["case_count"] == 32
        app = create_app(database_path=Path(temporary) / "new.db")
        app.state.database.engine.dispose()
        assert repository.get_trace(seeded["trace_ids"][0])["evaluation_history"]
        database.engine.dispose()
    migration = None
    if args.legacy_source:
        if not args.migration_copy or args.migration_copy.exists():
            raise ValueError("fresh_migration_copy_path_required")
        args.migration_copy.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(f"file:{args.legacy_source.resolve().as_posix()}?mode=ro", uri=True)
        destination = sqlite3.connect(args.migration_copy)
        try:
            source.backup(destination)
        finally:
            source.close()
            destination.close()
        before = immutable_rows(args.migration_copy)
        database = Database(args.migration_copy)
        database.initialize()
        assert immutable_rows(args.migration_copy) == before
        repository = Repository(database)
        count = len(repository.list_traces(limit=100000))
        for trace in repository.list_traces():
            detail = repository.get_trace(trace["trace_id"])
            if detail["metrics"]:
                assert detail["evaluation_history"]
        original_traces = {item["trace_id"]: repository.get_trace(item["trace_id"])["trace"]
                           for item in repository.list_traces(limit=100000)}
        seed_demo(repository)
        after_seed = immutable_rows(args.migration_copy)
        for table, rows in before.items():
            current = {row[0]: row for row in after_seed[table]}
            assert all(current[row[0]] == row for row in rows)
        assert all(repository.get_trace(trace_id)["trace"] == trace
                   for trace_id, trace in original_traces.items())
        assert repository.get_dataset("commerce-demo", "commerce-standard-bank", "0.2.0")["case_count"] == 32
        migration = {"immutable_versions_preserved": True, "trace_count": count, "upgrade_seed": "pass"}
        database.engine.dispose()
    print(json.dumps({"version": __version__, "bank_cases": 32, "fresh_database": "pass", "migration": migration}))


if __name__ == "__main__":
    main()
