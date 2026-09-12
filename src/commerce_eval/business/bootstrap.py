"""Install a new immutable bank and two opt-in candidates, without model calls."""

import hashlib

from commerce_eval.contracts import ExperimentSpecV1, TargetDefinitionV1, ToolContractV1
from commerce_eval.packs import all_evaluators
from .bank import VERSION, load_business_cases
from .candidates import BusinessCandidateSurface

SURFACES = ("business_interface", "file_editor")


def candidate_tool_contracts(surface, version=VERSION):
    items = []
    for schema in BusinessCandidateSurface(surface).schemas:
        function = schema["function"]
        items.append(ToolContractV1(
            contract_version="1.2", tool_id=function["name"], version=version,
            title=function["name"].replace("_", " ").title(), description=function["description"],
            input_schema=function["parameters"], tags=["synthetic", surface],
            preconditions=["Actual side-effect and review policy enforced by the shared scenario environment"],
        ))
    return items


def seed_business_bank(repository, project_id, template_ids=None, *, version=VERSION):
    repository.get_project(project_id)
    cases = load_business_cases(version)
    selected = sorted(template_ids) if template_ids is not None else sorted(case.scenario_id for case in cases)
    known = {case.scenario_id: case for case in cases}
    if not selected or len(selected) != len(set(selected)) or set(selected) - known.keys():
        raise ValueError("business_scenario_selection_invalid")
    cases = [known[identifier] for identifier in selected]
    suffix = "" if len(selected) == 32 else "-" + hashlib.sha256(",".join(selected).encode()).hexdigest()[:10]
    dataset_id = "commerce-standard-bank" + suffix
    evaluator_set = "commerce-business"
    repository.save_dataset(project_id, dataset_id, version, "Commerce Business Acceptance", cases,
        "One business standard, different tool sets. Synthetic data; candidate outcomes independently verified.")
    repository.save_evaluator_set(project_id, evaluator_set, version, [item.metric_id for item in all_evaluators()])
    limits = {"model_timeout_seconds": 120.0, "max_completion_tokens": 4096, "max_model_calls": 128} if version == VERSION else {}
    limit_tags = {"model_timeout_seconds": "120.0", "max_completion_tokens": "4096",
                  "total_model_request_limit": "128", "whole_case_timeout_ms": "300000"} if limits else {}
    targets = []
    specs = []
    for surface in SURFACES:
        set_id = "commerce-" + surface.replace("_", "-")
        repository.save_tool_contract_set(project_id, set_id, version, candidate_tool_contracts(surface, version))
        target = TargetDefinitionV1(
            contract_version="1.2", target_id=set_id, version=version,
            name="Business interface candidate" if surface == "business_interface" else "File editing candidate",
            adapter_type=surface, safe_for_eval=True,
            config={"project_id": project_id, "execution_mode": "sandbox", "max_rounds": 24,
                    **limits, "environment_version": "1.0", "tool_contract_set_id": set_id, "tool_contract_version": version},
            tags={"execution": "simulated", "actor": "real_model_candidate", "candidate_shape": surface},
        )
        repository.save_target(project_id, target)
        targets.append(target.model_dump(mode="json"))
        specs.append(ExperimentSpecV1(
            contract_version="1.2", experiment_id=f"business-{surface}-preview", project_id=project_id,
            name=target.name, dataset_id=dataset_id, dataset_version=version,
            target_id=target.target_id, target_version=version, tool_contract_set_id=set_id,
            tool_contract_version=version, evaluator_set_id=evaluator_set, evaluator_set_version=version,
            timeout_ms=300000, execution_mode="sandbox",
            tags={"environment_version": "1.0", "rule_version": "business-policy-1.0",
                  **limit_tags},
        ).model_dump(mode="json"))
    return {
        "project_id": project_id, "dataset_id": dataset_id, "dataset_version": version,
        "case_count": len(cases), "targets": targets, "candidate_evaluation": True,
        "target_id": targets[0]["target_id"], "target_version": version,
        "tool_contract_set_id": specs[0]["tool_contract_set_id"], "tool_contract_version": version,
        "evaluator_set_id": evaluator_set, "evaluator_set_version": version,
        "requires_explicit_model_configuration": True, "executed": False,
        "experiment_spec": specs[0], "candidate_experiment_specs": specs,
    }
