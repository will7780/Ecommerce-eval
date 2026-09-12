"""Materialize a synthetic handoff from the installed bank, without running it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from validate_bundle import BASELINE, BANK_VERSION, SKILL_VERSION, inspect_platform_capabilities, validate_bundle


def build_example(destination):
    capabilities = inspect_platform_capabilities()
    if capabilities["status"] != "valid":
        raise ValueError("compatible_platform_required_no_automatic_install")
    from commerce_eval.business.bank import load_business_cases
    from commerce_eval.contracts import ToolContractV1

    root = Path(destination)
    if root.exists() and any(p.is_file() or p.is_symlink() or getattr(p.lstat(), "st_file_attributes", 0) & 0x400
                             for p in root.rglob("*")):
        raise ValueError("example_destination_must_be_empty")
    root.mkdir(parents=True, exist_ok=True)
    (root / "importable").mkdir(exist_ok=True)
    resources = []

    def save(path, value):
        content = json.dumps(value, indent=2, ensure_ascii=True) + "\n" if not isinstance(value, str) else value
        raw = content.encode("utf-8")
        (root / path).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def resource(path, kind, identifier, version, payload, dependencies=()):
        digest = save(path, payload)
        resources.append(dict(path=path, kind=kind, id=identifier, version=version, sha256=digest,
                              order=len(resources) + 1, depends_on=list(dependencies)))

    # This example adopts one unchanged bank task, not a customer's business rules.
    case = next(c for c in load_business_cases(BANK_VERSION) if c.scenario_id == "I01")
    case = case.model_copy(update={"case_id": "preview-normal", "version": "1", "tags": ["synthetic-onboarding-example"]})
    tool = ToolContractV1(contract_version="1.2", tool_id="prepare_preview", version="1",
        title="Prepare an isolated preview", description="Synthetic API documented in assessment.md, not a real connector.",
        input_schema={"type": "object", "properties": {"row_ids": {"type": "array", "items": {"type": "string"}}},
                      "required": ["row_ids"], "additionalProperties": False},
        output_schema={"type": "object", "properties": {"artifact_id": {"type": "string"}}, "required": ["artifact_id"]},
        side_effect_class="local_write", risk_level="L1", confirmation_required=False,
        idempotent=True, success_evidence=["readable artifact rows"])
    resource("importable/tool-contracts.json", "tool-contracts", "preview-tools", "1",
             {"set_id": "preview-tools", "version": "1", "tools": [tool.model_dump(mode="json")]})
    resource("importable/evaluator-set.json", "evaluator-set", "business-only", "1",
             {"set_id": "business-only", "version": "1", "metric_ids": ["business_acceptance_pass"]})
    resource("importable/dataset.json", "dataset", "preview-exam", "1",
             {"dataset_id": "preview-exam", "version": "1", "name": "Synthetic preview adoption example", "cases": [case.model_dump(mode="json")]},
             ("importable/tool-contracts.json", "importable/evaluator-set.json"))
    source = "assessment.md#synthetic-scenario"
    conditions = []
    for index, requirement in enumerate(case.business_requirements):
        direction = {"artifact_scope": "I", "artifact_rules": "C", "no_effects": "S", "result_report": "R"}.get(requirement.verifier_id, "P")
        conditions.append(dict(id=f"condition-{index + 1}", direction=direction, applicability="applies",
            reason="Adopted unchanged synthetic preview condition; no customer evidence has been supplied.",
            source_refs=[source], support="existing", evidence="missing", use="business_gate",
            verifier_id=requirement.verifier_id, verifier_version=requirement.verifier_version,
            case_refs=[dict(dataset_id="preview-exam", dataset_version="1", case_id=case.case_id,
                            requirement_ids=[requirement.requirement_id])],
            evidence_requirements=[dict(object_scope="All 20 supplied product row IDs", company_scope="harbor (fictional)",
                source="Actual files and independent effect journal", collector="Not connected", locator="Not supplied",
                version_or_hash="Required: produced content and whole file manifest", time_range="Whole future run",
                completeness="Unknown", missing_impact="Cannot verify absence of effects or actual output content")]))
    conditions.append(dict(id="recovery-extension", direction="R", applicability="needs_confirmation",
        reason="No product failure behavior was supplied; retain the branch until the user confirms it.",
        source_refs=[source], support="configuration_needed", evidence="missing", use="business_gate", case_refs=[],
        evidence_requirements=[dict(object_scope="Failed preview operation", company_scope="harbor (fictional)",
            source="Future user-confirmed failure contract", collector="Unknown", locator="Not supplied",
            version_or_hash="Unknown", time_range="Failed operation and recovery", completeness="Unknown",
            missing_impact="No reliable recovery question or oracle yet")]))
    reasons = {"I": "Preview scope is applicable.", "C": "Synthetic mandatory product policy applies.",
               "T": "No fixed tool path; investigate business prerequisites before expansion.",
               "P": "Output price and units matter; new parameter scenarios need confirmation.",
               "A": "Readable output is required; publication review is not required by this preview-only task.",
               "M": "Future followups remain a product question, not an assumed feature.",
               "R": "Result honesty applies; failure recovery branch remains pending.",
               "S": "No publication or remote writes; no invented token/cost budget."}
    save("applicability.json", {"directions": [{"id": k, "reason": v} for k, v in reasons.items()], "conditions": conditions})
    save("manifest.json", {"bundle_version": SKILL_VERSION, "project_id": "synthetic-onboarding",
        "main_workflow": {"id": "preview-only", "confirmed": True, "source_refs": [source]}, "resources": resources,
        "rule_checks": [{"dataset_id": "preview-exam", "dataset_version": "1", "case_id": case.case_id,
                          "profile_case_id": "I01", "profile_bank_version": BANK_VERSION}]})
    save("assessment.md", "# Synthetic scenario\n\nThis is fictional teaching material, not an investigated customer.\n"
        "The example author adopts bank I01 unchanged: preview 20 supplied rows, no publication or price/inventory writes.\n"
        "Main workflow confirmation in the manifest belongs only to this fictional scenario. Obtain your own user's confirmation.\n"
        "Other global tasks to investigate: publishing, price changes, promotion, failed-job recovery. None is assumed implemented.\n"
        "The fictional prepare_preview(row_ids) interface is idempotent, writes local artifacts only, and returns artifact_id.\n"
        "Its output rows and complete side-effect journal have NOT been supplied. No target or actual trace is provided.\n"
        "Policy: the synthetic bank rules, including EUR and the declared margin formula, are adopted for this example only.\n")
    save("evidence-gaps.md", "# Evidence gaps\n\nNo customer runtime, authenticated collector, output files or complete effect journal exists here.\n"
        "A success message cannot prove product correctness or no publication. Reference evidence is used only inside grader validation.\n"
        "Add collector/adapter work to a separately approved integration task. The Skill does not implement it.\n")
    save("cases-draft.md", "# Question scope\n\npreview-normal is a normal synthetic preview task adopted from I01.\n"
        "Its embedded environment/references stay evaluator-only; only CandidateInput may reach an Agent later.\n"
        "A missing-input/failure recovery branch remains pending user confirmation and has no importable case.\n"
        "This small example is not complete product coverage or a replacement for the full 32-case bank.\n")
    save("next-steps.md", "# Handoff\n\nRead validation-report.json: valid import is not Agent acceptance.\n"
        "The helper exercised real imports only in a temporary database; nothing was added to your live platform.\n"
        "After separate user approval, import each resource in manifest order using the web wizard or commerce-eval import PATH --kind KIND --project PROJECT.\n"
        "Keep each wrapper ID/version; select the Dataset, actual tool contracts and built-in Evaluator Set for later explicit evaluation.\n"
        "Do not import reference fixtures as real traces. Do not upload the whole folder as a ZIP.\n"
        "Resolve pending business rules and evidence collection before declaring readiness. Ordinary web re-scoring runs built-in offline evaluators only.\n")
    report = validate_bundle(root)
    save("validation-report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="A new or empty directory; existing files are never replaced")
    args = parser.parse_args()
    try:
        result = build_example(args.destination)
        print(json.dumps({"import_status": result["import_status"], "business_readiness": result["business_readiness"]}))
        raise SystemExit(0 if result["import_status"] == "valid" else 1)
    except (OSError, ValueError):
        print(json.dumps({"error": "example_not_created_check_empty_directory_and_compatible_platform"}))
        raise SystemExit(1)
