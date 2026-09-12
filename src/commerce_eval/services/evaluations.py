"""Explicit offline evaluation with immutable version-pinned provenance."""

from commerce_eval.contracts import EvalCaseV1
from commerce_eval.core import EvaluationEngine
from commerce_eval.packs import all_evaluators
from commerce_eval.storage.business_evidence import load_business_evidence


class EvaluationService:
    def __init__(self, repository):
        self.repository = repository

    def evaluate(self, trace_id, *, project_id=None, dataset_id, dataset_version, case_id,
                 tool_contract_set_id, tool_contract_version, evaluator_set_id, evaluator_set_version):
        with self.repository.transaction() as repository:
            trace = repository.get_trace(trace_id)["trace"]
            project_id = project_id or trace["project_id"]
            if project_id != trace["project_id"]:
                raise ValueError("evaluation_project_mismatch")
            provenance = (trace.get("tags", {}), trace.get("metadata", {}))
            if any(item.get("actor") == "reference_fixture" or item.get("reference_fixture") is True
                   or item.get("candidate_evaluation") in (False, "false") for item in provenance):
                raise ValueError("reference_fixture_not_candidate")
            try:
                target = repository.get_target(project_id, trace["target_id"], trace["target_version"])
            except KeyError:
                target = None
            if target is not None and target.adapter_type == "reference_fixture":
                raise ValueError("reference_fixture_not_candidate")
            dataset = repository.get_dataset(project_id, dataset_id, dataset_version)
            case = next((EvalCaseV1.model_validate(row) for row in dataset["cases"] if row["case_id"] == case_id), None)
            if case is None:
                raise KeyError("case_not_found")
            contracts = repository.get_tool_contracts(project_id, tool_contract_set_id, tool_contract_version)
            if not any(row["set_id"] == tool_contract_set_id and row["version"] == tool_contract_version
                       for row in repository.list_tool_contract_sets(project_id)):
                raise KeyError("tool_contract_version_not_found")
            evaluator_set = repository.get_evaluator_set(project_id, evaluator_set_id, evaluator_set_version)
            # Explicit API evaluations never load external judges or entry-point code.
            available = {item.metric_id: item for item in all_evaluators()}
            metric_ids = evaluator_set["metric_ids"]
            if not metric_ids or any(metric_id not in available for metric_id in metric_ids):
                raise ValueError("evaluator_set_not_offline_available")
            evidence = load_business_evidence(repository, trace_id, project_id=project_id)
            result = EvaluationEngine([available[item] for item in metric_ids]).evaluate(
                case, trace, tool_contracts=contracts, business_evidence=evidence,
            )
            binding = {"source": "explicit", "dataset_id": dataset_id, "dataset_version": dataset_version,
                       "case_id": case_id, "tool_contract_set_id": tool_contract_set_id,
                       "tool_contract_version": tool_contract_version, "evaluator_set_id": evaluator_set_id,
                       "evaluator_set_version": evaluator_set_version,
                       "metric_versions": {item: available[item].metric_version for item in metric_ids}}
            evaluation_id = repository.save_evaluation(result, binding=binding)
            return repository.get_evaluation(evaluation_id)
