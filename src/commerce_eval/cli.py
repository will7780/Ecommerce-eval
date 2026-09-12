"""Command-line entry point for local platform operation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import uvicorn

from commerce_eval.api import create_app
from commerce_eval.contracts import EvalCaseV1, ExperimentSpecV1, TargetDefinitionV1, ToolContractV1, TraceEnvelopeV1
from commerce_eval.demo import seed_demo
from commerce_eval.experiments import ExperimentRunner
from commerce_eval.storage import Database, Repository, default_database_path
from commerce_eval.services.imports import ImportService, MAX_FILE_BYTES
from commerce_eval.services.evaluations import EvaluationService


def _database(path: str | None) -> tuple[Database, Repository]:
    database = Database(Path(path) if path else default_database_path())
    database.initialize()
    return database, Repository(database)


def _read_json_rows(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    return payload if isinstance(payload, list) else [payload]

def _required(args: argparse.Namespace, name: str) -> str:
    value = str(getattr(args, name, "") or "").strip()
    if not value:
        raise SystemExit(f"--{name.replace('_', '-')} is required for {args.kind} imports")
    return value


def _ensure_project(repository: Repository, project_id: str, description: str) -> None:
    try:
        repository.get_project(project_id)
    except KeyError:
        repository.create_project(project_id, project_id.replace("-", " ").title(), description)



def command_init(args: argparse.Namespace) -> int:
    database, _ = _database(args.database)
    print(json.dumps({"status": "initialized", "database": str(database.path)}, ensure_ascii=False))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    rows = _read_json_rows(Path(args.path))
    model = {"trace": TraceEnvelopeV1, "case": EvalCaseV1, "tool": ToolContractV1, "target": TargetDefinitionV1, "experiment": ExperimentSpecV1}[args.kind]
    count = 0
    for row in rows:
        if args.kind == "tool" and isinstance(row, dict) and isinstance(row.get("tools"), list):
            for item in row["tools"]:
                model.model_validate(item)
                count += 1
        else:
            model.model_validate(row)
            count += 1
    print(json.dumps({"status": "valid", "kind": args.kind, "count": count}))
    return 0


def command_import(args: argparse.Namespace) -> int:
    _database_obj, repository = _database(args.database)
    path = Path(args.path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("file_size_limit")
    content = path.read_text(encoding="utf-8")
    project_id = args.project
    if not project_id and args.kind == "trace":
        rows = _read_json_rows(path)
        projects = {row.get("project_id") for row in rows if isinstance(row, dict)}
        if len(projects) == 1:
            project_id = projects.pop()
    if not project_id:
        raise ValueError("project_required")
    evaluation_options = {}
    if args.evaluate:
        if args.kind != "trace":
            raise ValueError("evaluation_requires_trace_import")
        for key in ("dataset_id", "dataset_version", "case_id", "tool_contract_set_id",
                    "tool_contract_version", "evaluator_set_id", "evaluator_set_version"):
            value = getattr(args, key)
            if not value:
                raise ValueError("explicit_evaluation_binding_required")
            evaluation_options[key] = value
    mapping = json.loads(args.column_mapping) if args.column_mapping else {}
    service = ImportService(repository, allow_local_registration=args.kind == "target")
    preview = service.preview(project_id, args.kind, [{"name": path.name, "content": content}],
                              {"id": args.identifier, "version": args.version, "name": args.name,
                               "column_mapping": mapping})
    if preview["status"] != "ready":
        print(json.dumps(preview, ensure_ascii=False))
        return 1
    result = service.commit(preview["import_id"])
    if args.evaluate:
        result["evaluations"] = [EvaluationService(repository).evaluate(
            item["trace_id"], project_id=project_id, **evaluation_options
        )["evaluation_id"] for item in result["resources"]]
    print(json.dumps({**result, "status": "imported"}, ensure_ascii=False))
    return 0


def command_demo(args: argparse.Namespace) -> int:
    database, repository = _database(args.database)
    result = seed_demo(repository)
    url = f"http://{args.host}:{args.port}"
    result.update({"status": "ready", "database": str(database.path), "url": url})
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not args.seed_only:
        if args.host not in {"127.0.0.1", "localhost", "::1"}:
            raise SystemExit("The demo command is loopback-only; use serve explicitly for remote binding")
        database.dispose()
        uvicorn.run(create_app(database_path=database.path), host=args.host, port=args.port, log_level=args.log_level)
    return 0


def command_run(args: argparse.Namespace) -> int:
    _database_obj, repository = _database(args.database)
    spec = ExperimentSpecV1(
        contract_version="1.2" if getattr(args, "provider", None) else "1.0",
        provider_id=getattr(args, "provider", None),
        provider_version=getattr(args, "provider_version", None),
        model=getattr(args, "model", None),
        allow_paid=getattr(args, "allow_paid", False),
        experiment_id=args.experiment_id,
        project_id=args.project,
        name=args.name,
        dataset_id=args.dataset,
        dataset_version=args.dataset_version,
        target_id=args.target,
        target_version=args.target_version,
        tool_contract_set_id=args.tool_contract_set,
        tool_contract_version=args.tool_contract_version,
        evaluator_set_id=args.evaluator_set,
        evaluator_set_version=args.evaluator_set_version,
        repetitions=args.repetitions,
        concurrency=args.concurrency,
        execution_mode=args.mode,
        timeout_ms=args.timeout_ms,
    )
    repository.create_experiment(spec)
    result = asyncio.run(ExperimentRunner(repository).run(spec))
    print(json.dumps(result, ensure_ascii=False))
    return 0


def command_serve(args: argparse.Namespace) -> int:
    loopback = args.host in {"127.0.0.1", "localhost", "::1"}
    if not loopback and not os.environ.get("COMMERCE_EVAL_API_TOKEN") and not args.allow_unsafe_remote:
        raise SystemExit("Non-loopback serving requires COMMERCE_EVAL_API_TOKEN or --allow-unsafe-remote")
    app = create_app(database_path=args.database)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="commerce-eval", description="Framework-neutral agent evaluation platform")
    parser.add_argument("--database", help="SQLite database path; defaults to ~/.commerce-agent-eval/platform.db")
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="Initialize local storage")
    init_parser.set_defaults(func=command_init)

    validate = sub.add_parser("validate", help="Validate JSON or JSONL contracts")
    validate.add_argument("path")
    validate.add_argument("--kind", choices=("trace", "case", "tool", "target", "experiment"), required=True)
    validate.set_defaults(func=command_validate)

    import_parser = sub.add_parser("import", help="Import versioned traces, datasets, contracts, targets, or evaluators")
    import_parser.add_argument("path")
    import_parser.add_argument("--kind", choices=("trace", "dataset", "tool-contracts", "products", "rules", "target", "evaluator-set"), default="trace")
    import_parser.add_argument("--project")
    import_parser.add_argument("--id", dest="identifier")
    import_parser.add_argument("--version")
    import_parser.add_argument("--name")
    import_parser.add_argument("--column-mapping", help="JSON destination-field to source-column mapping")
    import_parser.add_argument("--eval", dest="evaluate", action="store_true")
    import_parser.add_argument("--dataset-id", "--dataset", dest="dataset_id")
    import_parser.add_argument("--dataset-version")
    import_parser.add_argument("--case-id")
    import_parser.add_argument("--tool-contract-set-id", "--tool-contract-set", dest="tool_contract_set_id")
    import_parser.add_argument("--tool-contract-version")
    import_parser.add_argument("--evaluator-set-id", "--evaluator-set", dest="evaluator_set_id")
    import_parser.add_argument("--evaluator-set-version")
    import_parser.set_defaults(func=command_import)

    demo = sub.add_parser("demo", help="Seed and serve an offline anonymized demo")
    demo.add_argument("--seed-only", action="store_true", help="Create demo data without starting the server")
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8770)
    demo.add_argument("--log-level", default="info")
    demo.set_defaults(func=command_demo)

    run = sub.add_parser("run", help="Run a version-pinned dataset experiment")
    run.add_argument("--experiment-id", required=True)
    run.add_argument("--name", default="CLI experiment")
    run.add_argument("--project", required=True)
    run.add_argument("--dataset", required=True)
    run.add_argument("--dataset-version", required=True)
    run.add_argument("--target", required=True)
    run.add_argument("--target-version", required=True)
    run.add_argument("--tool-contract-set", default="default")
    run.add_argument("--tool-contract-version")
    run.add_argument("--evaluator-set", default="default")
    run.add_argument("--evaluator-set-version", default="1.0.0")
    run.add_argument("--repetitions", type=int, default=1)
    run.add_argument("--concurrency", type=int, default=1)
    run.add_argument("--mode", choices=("dry_run", "sandbox"), default="dry_run")
    run.add_argument("--timeout-ms", type=int, default=30000)
    run.add_argument("--provider")
    run.add_argument("--provider-version")
    run.add_argument("--model")
    run.add_argument("--allow-paid", action="store_true", help="Explicitly authorize model requests for a built-in candidate")
    run.set_defaults(func=command_run)

    serve = sub.add_parser("serve", help="Start the local API and dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8770)
    serve.add_argument("--log-level", default="info")
    serve.add_argument("--allow-unsafe-remote", action="store_true")
    serve.set_defaults(func=command_serve)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except Exception:
        print(json.dumps({"status": "invalid", "detail": "command_failed"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

