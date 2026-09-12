"""Idempotent, no-key demo project seeding."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from commerce_eval.contracts import ConversationEventV1, EvalCaseV1, ExperimentSpecV1, TargetDefinitionV1, ToolContractV1, TraceEnvelopeV1
from commerce_eval.core import EvaluationEngine
from commerce_eval.packs import all_evaluators
from commerce_eval.storage import Repository, VersionConflictError


def _root_examples():
    packaged = files("commerce_eval").joinpath("demo_data")
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[2] / "examples"


def _load_examples() -> tuple[list[ToolContractV1], list[EvalCaseV1], list[TraceEnvelopeV1]]:
    root = _root_examples()
    if not root.exists():
        raise RuntimeError("demo_examples_unavailable")
    tool_payload = json.loads((root / "tool-contracts.json").read_text(encoding="utf-8"))
    tools = [ToolContractV1.model_validate(item) for item in tool_payload["tools"]]
    cases = [EvalCaseV1.model_validate_json(line) for line in (root / "dataset.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = [
        case.model_copy(
            update={
                "conversation": [
                    ConversationEventV1(
                        type="user_message",
                        content=str(case.input.get("message") or "Start the workflow."),
                    ),
                    ConversationEventV1(
                        type="interaction_response",
                        interaction_id="demo-publication-confirm",
                        response={"decision": "approve"},
                    ),
                ]
            }
        )
        if case.case_id == "listing-launch" and not case.conversation
        else case
        for case in cases
    ]
    traces = [TraceEnvelopeV1.model_validate_json(line) for line in (root / "traces.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return tools, cases, traces


def seed_demo(repository: Repository) -> dict[str, Any]:
    tools, cases, source_traces = _load_examples()
    repository.create_project("commerce-demo", "Commerce Operations Demo", "Offline, anonymized evaluation data")
    repository.save_tool_contract_set("commerce-demo", "default", "1.0.0", tools)
    repository.save_dataset("commerce-demo", "commerce-operations", "1.0.0", "Commerce Operations", cases, "Deterministic launch, recovery and conversation cases")
    # The 1.0.0 demo is immutable: later diagnostic counters belong to the new set.
    newer_metrics = {
        "business_acceptance_pass",
        "scenario_behavior_compliance", "business_tool_blocked_count",
        "business_tool_execution_count", "business_tool_success_count",
    }
    legacy_metrics = [
        item for item in all_evaluators()
        if not item.metric_id.startswith("artifact_") and item.metric_id not in newer_metrics
    ]
    repository.save_evaluator_set("commerce-demo", "default", "1.0.0", [item.metric_id for item in legacy_metrics])
    repository.save_target(
        "commerce-demo",
        TargetDefinitionV1(
            target_id="fixture-agent",
            version="1.0.0",
            name="Offline fixture agent",
            adapter_type="python",
            safe_for_eval=True,
            config={
                "command": ["$PYTHON", "-m", "commerce_eval.demo_runtime"],
                "project_id": "commerce-demo",
                "execution_mode": "dry_run",
            },
            tags={"source": "demo"},
        ),
    )
    experiments = [
        ExperimentSpecV1(
            experiment_id="exp-demo-baseline",
            project_id="commerce-demo",
            name="Baseline workflow",
            dataset_id="commerce-operations",
            dataset_version="1.0.0",
            target_id="fixture-agent",
            target_version="1.0.0",
            tool_contract_version="1.0.0",
            evaluator_set_version="1.0.0",
            tags={"tool_contract_set_id": "default", "channel": "demo"},
        ),
        ExperimentSpecV1(
            experiment_id="exp-demo-recovery",
            project_id="commerce-demo",
            name="Recovery behavior",
            dataset_id="commerce-operations",
            dataset_version="1.0.0",
            target_id="fixture-agent",
            target_version="1.0.0",
            tool_contract_version="1.0.0",
            evaluator_set_version="1.0.0",
            tags={"tool_contract_set_id": "default", "channel": "demo"},
        ),
    ]
    new_experiment_ids = set()
    for spec in experiments:
        try:
            repository.get_experiment(spec.experiment_id)
        except KeyError:
            new_experiment_ids.add(spec.experiment_id)
        repository.create_experiment(spec)

    engine = EvaluationEngine(legacy_metrics)
    case_map = {case.case_id: case for case in cases}
    now = datetime.now(timezone.utc)
    seeded_ids: list[str] = []
    for index, source in enumerate(source_traces):
        experiment_id = "exp-demo-baseline" if index == 0 else "exp-demo-recovery"
        payload = source.model_dump(mode="json")
        payload["tool_contract_set_id"] = "default"
        payload["experiment_id"] = experiment_id
        payload["started_at"] = (now - timedelta(minutes=35 - index * 12)).isoformat()
        payload["ended_at"] = (now - timedelta(minutes=35 - index * 12) + timedelta(seconds=2)).isoformat()
        trace = TraceEnvelopeV1.model_validate(payload)
        try:
            repository.save_trace(trace, tool_contracts={tool.tool_id: tool for tool in tools})
        except VersionConflictError:
            trace = TraceEnvelopeV1.model_validate(repository.get_trace(trace.trace_id)["trace"])
        if not repository.get_trace(trace.trace_id).get("evaluation_history"):
            result = engine.evaluate(case_map[trace.case_id], trace, tool_contracts={tool.tool_id: tool for tool in tools})
            repository.save_evaluation(result)
        seeded_ids.append(trace.trace_id)
    for experiment_id in new_experiment_ids:
        repository.update_experiment(experiment_id, status="completed", completed_runs=1)
    seed_onboarding_demo(repository, "commerce-demo")
    from commerce_eval.business.bootstrap import seed_business_bank
    seed_business_bank(repository, "commerce-demo")
    return {"project_id": "commerce-demo", "trace_ids": seeded_ids, "experiments": [item.experiment_id for item in experiments]}


def seed_onboarding_demo(repository: Repository, project_id: str, template_ids=None) -> dict[str, Any]:
    """Install a versioned bank and an explicitly non-candidate reference target."""
    import hashlib
    from commerce_eval.scenarios import build_tool_contracts, compile_scenario, load_scenario_templates

    repository.get_project(project_id)
    templates = load_scenario_templates()
    selected = sorted(template_ids) if template_ids is not None else sorted(t.scenario_id for t in templates)
    known = {t.scenario_id: t for t in templates}
    if not selected or len(set(selected)) != len(selected) or set(selected) - known.keys():
        raise ValueError("scenario_selection_invalid")
    cases = [compile_scenario(known[identifier]) for identifier in selected]
    suffix = "" if len(selected) == 32 else "-" + hashlib.sha256(",".join(selected).encode()).hexdigest()[:10]
    dataset_id = "commerce-standard-bank" + suffix
    set_id = "commerce-standard" + suffix
    version = "0.2.0"
    repository.save_dataset(project_id, dataset_id, version, "Commerce Standard Bank", cases,
                            "Eight directions; synthetic scenario fixtures. Reference traces are not candidate scores.")
    contracts = {}
    for case in cases:
        for tool in build_tool_contracts(case):
            contracts[tool.tool_id] = tool
    repository.save_tool_contract_set(project_id, set_id, version, [contracts[k] for k in sorted(contracts)])
    repository.save_evaluator_set(project_id, set_id, version, [item.metric_id for item in all_evaluators() if item.metric_id != "business_acceptance_pass"])
    target = TargetDefinitionV1(contract_version="1.1", target_id="standard-reference-fixtures", version=version,
        name="Reference fixtures (not Agent scores)", adapter_type="reference_fixture", safe_for_eval=True,
        config={"execution_mode": "dry_run", "project_id": project_id},
        tags={"actor": "reference_fixture", "execution": "simulated", "candidate_evaluation": "false"})
    repository.save_target(project_id, target)
    policy_target = TargetDefinitionV1(contract_version="1.1", target_id="standard-reference-policy", version=version,
        name="Independent policy baseline (no LLM)", adapter_type="reference_policy", safe_for_eval=True,
        config={"execution_mode": "dry_run", "project_id": project_id, "max_steps": 32},
        tags={"actor": "reference_policy", "execution": "simulated", "model": "none"})
    repository.save_target(project_id, policy_target)
    spec = ExperimentSpecV1(contract_version="1.1", experiment_id="reference-preview", project_id=project_id,
        name="Standard bank reference traces", dataset_id=dataset_id, dataset_version=version,
        target_id=target.target_id, target_version=version, tool_contract_set_id=set_id,
        tool_contract_version=version, evaluator_set_id=set_id, evaluator_set_version=version,
        repetitions=1, concurrency=1, execution_mode="dry_run", timeout_ms=30000,
        tags={"actor": "reference_fixture", "candidate_evaluation": "false"})
    policy_spec = spec.model_copy(update={
        "experiment_id": "policy-preview", "name": "Standard bank policy evaluation",
        "target_id": policy_target.target_id, "target_version": version,
        "tags": {"actor": "reference_policy", "model": "none", "execution": "simulated"},
    })
    return {"project_id": project_id, "dataset_id": dataset_id, "dataset_version": version,
            "case_count": len(cases), "target_id": target.target_id, "target_version": version,
            "tool_contract_set_id": set_id, "tool_contract_version": version,
            "evaluator_set_id": set_id, "evaluator_set_version": version,
            "candidate_evaluation": False, "experiment_spec": spec.model_dump(mode="json"),
            "policy_experiment_spec": policy_spec.model_dump(mode="json")}

