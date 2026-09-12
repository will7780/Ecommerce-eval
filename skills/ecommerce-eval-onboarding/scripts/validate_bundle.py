"""Offline handoff validation, not Agent evaluation or collector authentication."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

SKILL_VERSION = "0.1.0"
BASELINE = "0.3.0rc2"
BANK_VERSION = "0.3.1"
MAX_FILE = 10 * 1024 * 1024
MAX_BUNDLE = 50 * 1024 * 1024
DIRECTIONS = set("ICTPAMRS")
EVIDENCE_FIELDS = {"object_scope", "company_scope", "source", "collector", "locator",
                   "version_or_hash", "time_range", "completeness", "missing_impact"}
PRIVATE_FIELDS = {"expected_answer", "reference_answer", "reference_answers", "answer_key",
                  "gates", "business_requirements", "defect_labels", "fault_script",
                  "interaction_script", "future_answers", "references", "mutants"}
FORBIDDEN_FIELDS = {"api_key", "apikey", "password", "secret", "token", "access_token",
                    "authorization", "chain_of_thought", "hidden_reasoning", "reasoning_content",
                    "scratchpad", "cot", "thoughts", "trusted"}
SECRET = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b|\b(?i:Bearer)\s+\S{10,}|"
                    r"(?i:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+")


class BundleError(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise BundleError(code)


def _json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    def constant(_):
        raise BundleError("non_finite_number")

    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError):
        raise BundleError("json_invalid") from None


def _walk(value, forbidden, depth=0):
    _require(depth < 64, "nesting_limit")
    if isinstance(value, dict):
        for key, child in value.items():
            _require(key.lower().replace("-", "_") not in forbidden, "forbidden_field")
            _walk(child, forbidden, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _walk(child, forbidden, depth + 1)
    elif isinstance(value, str):
        _require(not SECRET.search(value), "sensitive_content")


def _strings(value):
    return isinstance(value, list) and bool(value) and all(isinstance(x, str) and x.strip() for x in value)


def _ref(value):
    _require(isinstance(value, dict), "case_reference_invalid")
    keys = ("dataset_id", "dataset_version", "case_id")
    _require(all(isinstance(value.get(k), str) and value[k] for k in keys), "case_reference_invalid")
    return tuple(value[k] for k in keys)


def _read(root, relative):
    _require(isinstance(relative, str) and "\\" not in relative and ":" not in relative,
             "path_not_relative")
    parts = PurePosixPath(relative).parts
    _require(parts and not PurePosixPath(relative).is_absolute() and ".." not in parts,
             "path_not_relative")
    current = root
    for part in parts:
        current = current / part
        info = current.lstat()
        _require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                 "linked_path_forbidden")
    _require(current.resolve().is_relative_to(root), "path_escape")
    _require(current.is_file() and current.stat().st_size <= MAX_FILE, "file_size_or_type")
    # Bound the actual read as well as the prior stat; never follow extra references.
    with current.open("rb") as stream:
        raw = stream.read(MAX_FILE + 1)
    _require(len(raw) <= MAX_FILE, "file_size_or_type")
    text = raw.decode("utf-8-sig")
    _require(not SECRET.search(text), "sensitive_content")
    return raw, text


def inspect_platform_capabilities():
    """Read installed built-ins. No entry points, credentials, targets or network."""
    result = {"skill_version": SKILL_VERSION, "status": "not_checked", "platform_version": None,
              "supported_baseline": BASELINE, "reason_codes": []}
    try:
        import commerce_eval
        result["platform_version"] = commerce_eval.__version__
        try:
            result["distribution_version"] = importlib.metadata.version("commerce-agent-eval")
            direct = importlib.metadata.distribution("commerce-agent-eval").read_text("direct_url.json")
            result["editable_source"] = bool(json.loads(direct or "{}").get("dir_info", {}).get("editable"))
        except importlib.metadata.PackageNotFoundError:
            result["distribution_version"] = None
        if result["platform_version"] != BASELINE or (result["distribution_version"] not in (None, BASELINE)
                                                     and not result.get("editable_source")):
            result["reason_codes"] = ["platform_version_unverified"]
            return result
        if result["distribution_version"] not in (None, BASELINE):
            result["reason_codes"] = ["editable_distribution_metadata_stale_using_inspected_runtime"]
        from commerce_eval.business.bank import VERSION, load_business_cases
        from commerce_eval.business.verifiers import VERIFIERS, VERIFIERS_V11
        from commerce_eval.contracts import EvalCaseV1, ToolContractV1, TraceEnvelopeV1
        from commerce_eval.packs import all_evaluators
        from commerce_eval.services.imports import KINDS
        result.update(status="valid", contract_versions=["1.0", "1.1", "1.2"], bank_version=VERSION,
                      import_kinds=sorted(KINDS), evaluator_route="builtin_offline",
                      external_collector_upload=False, plugins_loaded=False)
        result["metrics"] = [{"metric_id": item.metric_id, "group": getattr(item, "group", None),
                              "version": getattr(item, "metric_version", None)} for item in all_evaluators()]
        result["verifiers"] = {"1.0": sorted(VERIFIERS), "1.1": sorted(VERIFIERS_V11)}
        result["cases"] = [{"case_id": c.case_id, "scenario_id": c.scenario_id, "direction": c.direction,
                            "verifiers": [r.model_dump(mode="json") for r in c.business_requirements]}
                           for c in load_business_cases()]
        result["contracts"] = {model.__name__: model.model_json_schema()
                               for model in (EvalCaseV1, ToolContractV1, TraceEnvelopeV1)}
        if VERSION != BANK_VERSION:
            result.update(status="not_checked", reason_codes=["bank_version_unverified"])
    except Exception:
        result["status"] = "not_checked"
        result["reason_codes"] = ["platform_unavailable_or_incompatible"]
    return result


def _load_bundle(root):
    manifest_raw, manifest_text = _read(root, "manifest.json")
    matrix_raw, matrix_text = _read(root, "applicability.json")
    manifest, matrix = _json(manifest_text), _json(matrix_text)
    _walk(manifest, FORBIDDEN_FIELDS)
    _walk(matrix, FORBIDDEN_FIELDS)
    _require(isinstance(manifest, dict) and manifest.get("bundle_version") == SKILL_VERSION,
             "bundle_version_unsupported")
    _require(isinstance(manifest.get("project_id"), str) and bool(manifest["project_id"]), "project_required")
    workflow = manifest.get("main_workflow", {})
    _require(isinstance(workflow, dict) and isinstance(workflow.get("id"), str) and bool(workflow["id"]),
             "workflow_required")
    _require(type(workflow.get("confirmed")) is bool and _strings(workflow.get("source_refs")),
             "workflow_confirmation_source_required")
    resources = manifest.get("resources")
    _require(isinstance(resources, list) and len(resources) <= 1000, "resource_inventory_invalid")
    paths, orders, loaded, total = set(), set(), [], len(manifest_raw) + len(matrix_raw)
    for name in ("assessment.md", "evidence-gaps.md", "cases-draft.md", "next-steps.md"):
        if (root / name).exists():
            raw, _ = _read(root, name)
            total += len(raw)
    _require(total <= MAX_BUNDLE, "bundle_size_limit")
    for item in resources:
        _require(isinstance(item, dict), "resource_invalid")
        path, order = item.get("path"), item.get("order")
        _require(isinstance(path, str) and path.startswith("importable/"), "resource_not_importable_path")
        _require(path not in paths and type(order) is int and order >= 0 and order not in orders,
                 "resource_order_or_path_duplicate")
        _require(all(isinstance(item.get(k), str) and bool(item[k]) for k in ("id", "version", "kind")),
                 "resource_identity_required")
        _require(isinstance(item.get("depends_on", []), list), "dependencies_invalid")
        raw, text = _read(root, path)
        total += len(raw)
        _require(total <= MAX_BUNDLE, "bundle_size_limit")
        _require(hashlib.sha256(raw).hexdigest() == item.get("sha256"), "file_hash_mismatch")
        suffix = PurePosixPath(path).suffix.lower()
        payload = None
        if suffix == ".json":
            payload = _json(text)
            _walk(payload, FORBIDDEN_FIELDS)
        elif suffix == ".jsonl":
            payload = [_json(line) for line in text.splitlines() if line.strip()]
            _walk(payload, FORBIDDEN_FIELDS)
        elif suffix == ".csv":
            reader = csv.DictReader(io.StringIO(text))
            _require(bool(reader.fieldnames) and len(set(reader.fieldnames)) == len(reader.fieldnames),
                     "csv_header_invalid")
            _require(all(isinstance(key, str) and key.lower().replace("-", "_") not in FORBIDDEN_FIELDS
                         for key in reader.fieldnames), "forbidden_field")
            for row in reader:
                _require(None not in row, "csv_row_invalid")
                _walk(row, FORBIDDEN_FIELDS)
        _require(suffix in {".json", ".jsonl", ".csv", ".md", ".txt"}, "file_type_forbidden")
        paths.add(path)
        orders.add(order)
        loaded.append((item, text, payload))
    # Unlisted importable files must not look validated to the recipient.
    importable = root / "importable"
    if importable.exists():
        for path in importable.rglob("*"):
            info = path.lstat()
            _require(not path.is_symlink() and not getattr(info, "st_file_attributes", 0) & 0x400,
                     "linked_path_forbidden")
            if path.is_file():
                _require(path.relative_to(root).as_posix() in paths, "unlisted_importable_file")
    seen = set()
    for item, _, _ in sorted(loaded, key=lambda x: x[0]["order"]):
        _require(all(isinstance(p, str) and p in seen for p in item.get("depends_on", [])),
                 "dependency_missing_or_out_of_order")
        seen.add(item["path"])
    return manifest, matrix, sorted(loaded, key=lambda x: x[0]["order"])


def _coverage(matrix, cases):
    _require(isinstance(matrix, dict), "applicability_invalid")
    directions = matrix.get("directions", [])
    _require(isinstance(directions, list) and len(directions) == 8 and
             all(isinstance(d, dict) and isinstance(d.get("reason"), str) and d["reason"] for d in directions),
             "eight_direction_review_required")
    _require({d.get("id") for d in directions} == DIRECTIONS, "eight_direction_review_required")
    conditions = matrix.get("conditions")
    _require(isinstance(conditions, list) and conditions, "conditions_required")
    counters = dict(total=len(conditions), applicable=0, covered=0, pending_confirmation=0,
                    evidence_required=0, extension_required=0, uncovered=0, not_applicable=0)
    seen, rows = set(), []
    for condition in conditions:
        _require(isinstance(condition, dict), "condition_invalid")
        cid = condition.get("id")
        _require(isinstance(cid, str) and bool(cid) and cid not in seen, "condition_id_invalid")
        seen.add(cid)
        _require(condition.get("direction") in DIRECTIONS, "condition_direction_invalid")
        _require(condition.get("applicability") in {"applies", "not_applicable", "needs_confirmation"},
                 "condition_applicability_invalid")
        _require(condition.get("support") in {"existing", "configuration_needed", "extension_needed"},
                 "condition_support_invalid")
        _require(condition.get("evidence") in {"sufficient", "partial", "missing", "untrusted"},
                 "condition_evidence_invalid")
        _require(condition.get("use") in {"business_gate", "explicit_gate", "diagnostic"}, "condition_use_invalid")
        _require(isinstance(condition.get("reason"), str) and bool(condition["reason"]) and
                 _strings(condition.get("source_refs")), "condition_source_required")
        refs = condition.get("case_refs", [])
        _require(isinstance(refs, list), "case_reference_invalid")
        _require(all(_ref(r) in cases for r in refs), "case_reference_missing")
        if condition["applicability"] == "needs_confirmation":
            _require(not refs, "unconfirmed_rule_must_remain_draft")
        if condition["use"] == "business_gate" and condition["applicability"] == "applies":
            _require(all(isinstance(condition.get(k), str) and condition[k]
                         for k in ("verifier_id", "verifier_version")), "condition_verifier_required")
            for ref in refs:
                _require(_strings(ref.get("requirement_ids")), "condition_requirement_reference_required")
                actual = {r.requirement_id: r for r in cases[_ref(ref)].business_requirements}
                _require(all(r in actual and actual[r].applicable and
                             actual[r].verifier_id == condition["verifier_id"] and
                             actual[r].verifier_version == condition["verifier_version"]
                             for r in ref["requirement_ids"]), "condition_verifier_reference_mismatch")
        evidence = condition.get("evidence_requirements", [])
        _require(isinstance(evidence, list) and all(isinstance(e, dict) and EVIDENCE_FIELDS <= e.keys()
                 and all(isinstance(e[k], str) and e[k] for k in EVIDENCE_FIELDS) for e in evidence),
                 "evidence_matrix_incomplete")
        reasons = []
        if condition["applicability"] == "not_applicable":
            counters["not_applicable"] += 1
            status, reasons = "not_checked", ["declared_not_applicable_requires_review"]
        else:
            counters["applicable"] += 1
            _require(bool(evidence), "evidence_requirements_missing")
            counters["covered"] += bool(refs)
            counters["uncovered"] += not bool(refs)
            if not refs:
                reasons.append("question_not_yet_covered")
            counters["extension_required"] += condition["support"] == "extension_needed"
            counters["pending_confirmation"] += condition["applicability"] == "needs_confirmation"
            counters["evidence_required"] += condition["evidence"] != "sufficient"
            if condition["support"] == "extension_needed":
                status, reasons = "unsupported", reasons + ["verifier_extension_required"]
            elif condition["applicability"] == "needs_confirmation":
                status, reasons = "not_checked", reasons + ["business_rule_confirmation_required"]
            elif condition["evidence"] != "sufficient":
                status, reasons = "evidence_required", reasons + ["evidence_missing_or_untrusted"]
            else:
                status, reasons = "integration_required", reasons + ["collector_not_authenticated_by_bundle"]
        rows.append({"condition_id": cid, "status": status, "reason_codes": reasons,
                     "applicability": condition["applicability"],
                     "source_refs": condition["source_refs"], "evidence_requirements": evidence})
    represented = {(*_ref(ref), requirement_id) for condition in conditions
                   if condition["applicability"] == "applies" and condition["use"] == "business_gate"
                   for ref in condition.get("case_refs", []) for requirement_id in ref.get("requirement_ids", [])}
    required = {(*key, requirement.requirement_id) for key, case in cases.items()
                for requirement in case.business_requirements if requirement.applicable}
    _require(required <= represented, "case_requirement_not_in_matrix")
    return {"counts": counters, "conditions": rows, "counts_overlap": True,
            "scope": "declared_conditions_only_not_independent_product_coverage"}


def _case_signature(case):
    data = case.model_dump(mode="json")
    # Metadata/diagnostic tool spelling can vary; task, environment and gates cannot.
    for key in ("case_id", "name", "version", "tags", "capability_bindings", "expected_tools", "allowed_tools"):
        data.pop(key, None)
    for requirement in data.get("business_requirements", []):
        requirement.pop("requirement_id", None)
    return data


def _rules(cases, manifest, capabilities):
    from commerce_eval.business.bank import load_business_cases
    from commerce_eval.business.fixtures import positive_business_evidence, negative_business_variants
    from commerce_eval.business.verifiers import evaluate_business_requirements
    profiles = {c.scenario_id: c for c in load_business_cases(BANK_VERSION)}
    checks = manifest.get("rule_checks", [])
    _require(isinstance(checks, list), "rule_checks_invalid")
    selected = {}
    for check in checks:
        key = _ref(check)
        _require(key in cases and key not in selected, "rule_case_reference_invalid")
        selected[key] = check
    results = []
    for key, case in cases.items():
        result = dict(zip(("dataset_id", "dataset_version", "case_id"), key))
        result.update(status="not_checked", reason_codes=["reviewed_conformance_profile_required"])
        requirements = case.business_requirements
        if any(r.verifier_id not in capabilities["verifiers"].get(r.verifier_version, []) for r in requirements):
            result.update(status="invalid", reason_codes=["business_verifier_unavailable"])
        elif requirements and any(not r.applicable for r in requirements):
            result["reason_codes"] = ["inapplicability_requires_business_review"]
        elif key in selected:
            check = selected[key]
            profile = profiles.get(check.get("profile_case_id"))
            if check.get("profile_bank_version") != BANK_VERSION or profile is None:
                result["reason_codes"] = ["conformance_profile_unavailable"]
            elif _case_signature(case) != _case_signature(profile):
                result["reason_codes"] = ["custom_configuration_requires_reviewed_fixtures"]
            else:
                outcomes = []
                for surface in ("business_interface", "file_editor"):
                    positive = evaluate_business_requirements(case, positive_business_evidence(profile, surface))
                    negatives = [evaluate_business_requirements(case, v["evidence"])
                                 for v in negative_business_variants(profile, surface)]
                    missing = evaluate_business_requirements(case, None)
                    ok = (positive.status.value == "pass" and len(negatives) >= 3 and
                          all(r.status.value in {"fail", "error"} for r in negatives) and
                          missing.status.value == "error")
                    outcomes.append({"surface": surface, "valid": ok, "positive": positive.status.value,
                                     "negative_statuses": [r.status.value for r in negatives],
                                     "missing_evidence": missing.status.value})
                result.update(status="valid" if all(r["valid"] for r in outcomes) else "invalid",
                              reason_codes=["builtin_oracle_conformance_only"], checks=outcomes)
        results.append(result)
    status = ("invalid" if any(r["status"] == "invalid" for r in results) else
              "valid" if results and all(r["status"] == "valid" for r in results) else "not_checked")
    return {"status": status, "cases": results, "scope": "grader_fixtures_not_agent_performance"}


def validate_bundle(bundle_dir):
    """Read a local handoff and import only into a disposable database; never connect."""
    report = {"skill_version": SKILL_VERSION, "import_status": "not_checked",
              "business_readiness": {"status": "not_checked", "reason_codes": ["validation_incomplete"]},
              "checks": {k: {"status": "not_checked"} for k in ("structure", "references", "import", "rules")},
              "errors": [], "resources": [], "execution_performed": False,
              "credentials_accessed": False, "temporary_environment_cleaned": False}
    stage = "structure"
    try:
        root = Path(bundle_dir).resolve(strict=True)
        manifest, matrix, loaded = _load_bundle(root)
        report["checks"]["structure"]["status"] = "valid"
        catalog = inspect_platform_capabilities()
        report["platform"] = {k: v for k, v in catalog.items() if k not in {"contracts", "cases", "metrics"}}
        if catalog["status"] != "valid":
            report["business_readiness"]["reason_codes"] = catalog["reason_codes"]
            return report
        from commerce_eval.contracts import EvalCaseV1, TargetDefinitionV1
        from commerce_eval.core.redaction import contains_secret, redact_recursive
        from commerce_eval.services.imports import ImportService
        from commerce_eval.storage import Database, Repository
        stage = "references"
        cases, known_metrics = {}, {m["metric_id"] for m in catalog["metrics"]}
        for item, text, payload in loaded:
            _require(item["kind"] in catalog["import_kinds"], "import_kind_invalid")
            _require(not contains_secret(payload if payload is not None else text), "sensitive_content")
            _require(not contains_secret(item), "sensitive_manifest")
            if item["kind"] == "target":
                review = item.get("safety_review", {})
                _require(review.get("confirmed") is True and _strings(review.get("source_refs")), "target_review_required")
                target = TargetDefinitionV1.model_validate(payload)
                _require(target.safe_for_eval and review.get("execution_mode") in {"dry_run", "sandbox"}, "unsafe_target")
                _require(target.adapter_type == "http", "registered_python_target_handoff_only")
                _require(target.target_id == item["id"] and target.version == item["version"], "resource_identity_mismatch")
            if item["kind"] == "trace":
                _require(item.get("provenance") == "user_recorded" and _strings(item.get("source_refs")),
                         "genuine_trace_source_required")
            if isinstance(payload, dict):
                for field in ("dataset_id", "set_id", "asset_id"):
                    if field in payload:
                        _require(payload[field] == item["id"], "resource_identity_mismatch")
                if "version" in payload:
                    _require(payload["version"] == item["version"], "resource_version_mismatch")
            if item["kind"] == "dataset":
                data = payload.get("cases") if isinstance(payload, dict) else payload
                _require(isinstance(data, list) and bool(data), "dataset_cases_required")
                for raw in data:
                    case = EvalCaseV1.model_validate(raw)
                    _walk(case.input, PRIVATE_FIELDS)
                    for turn in case.conversation:
                        if turn.type == "user_message":
                            _walk(turn.model_dump(mode="json"), PRIVATE_FIELDS)
                    _require(all(g.metric_id in known_metrics for g in case.gates), "metric_reference_missing")
                    key = (item["id"], item["version"], case.case_id)
                    if key in cases:
                        _require(cases[key] == case, "case_version_conflict")
                    cases[key] = case
        report["coverage"] = _coverage(matrix, cases)
        report["checks"]["references"]["status"] = "valid"
        if not manifest["main_workflow"]["confirmed"]:
            report["business_readiness"]["reason_codes"] = ["main_workflow_confirmation_required"]
            return redact_recursive(report, max_depth=32, max_items=10000, max_chars=MAX_FILE)
        stage = "import"
        temporary_path = None
        try:
            with tempfile.TemporaryDirectory(prefix="commerce-onboarding-") as temporary:
                temporary_path = Path(temporary)
                database = Database(temporary_path / "validation.db")
                try:
                    database.initialize()
                    service = ImportService(Repository(database))
                    for item, text, _ in loaded:
                        options = dict(item.get("options", {}))
                        _require(not set(options) - {"column_mapping"}, "import_options_invalid")
                        options.update(id=item["id"], version=item["version"])
                        preview = service.preview(manifest["project_id"], item["kind"],
                            [{"name": PurePosixPath(item["path"]).name, "content": text}], options)
                        if preview["status"] != "ready":
                            report["resources"].append({"path": item["path"], "status": "invalid",
                                                        "errors": preview["errors"]})
                            raise BundleError("platform_preview_rejected")
                        service.commit(preview["import_id"])
                        report["resources"].append({"path": item["path"], "status": "valid"})
                finally:
                    database.dispose()
        finally:
            report["temporary_environment_cleaned"] = temporary_path is not None and not temporary_path.exists()
        report["checks"]["import"]["status"] = "valid" if loaded else "not_checked"
        report["import_status"] = report["checks"]["import"]["status"]
        stage = "rules"
        report["checks"]["rules"] = _rules(cases, manifest, catalog)
        statuses = {c["status"] for c in report["coverage"]["conditions"] if c["applicability"] != "not_applicable"}
        rules = report["checks"]["rules"]
        if "unsupported" in statuses or rules["status"] == "invalid":
            state, reason = "unsupported", "unavailable_or_invalid_rule_configuration"
        elif "not_checked" in statuses or rules["status"] != "valid":
            state, reason = "not_checked", "business_rules_or_fixtures_need_review"
        elif "evidence_required" in statuses:
            state, reason = "evidence_required", "evidence_missing_or_untrusted"
        else:
            state, reason = "integration_required", "collector_not_authenticated_by_bundle"
        report["business_readiness"] = {"status": state, "reason_codes": [reason],
                                         "source": "offline_bundle_audit_not_collector_registration"}
        return redact_recursive(report, max_depth=32, max_items=10000, max_chars=MAX_FILE)
    except Exception as exc:
        # Never echo parser inputs, paths, model validation dumps or exception text.
        code = str(exc) if isinstance(exc, BundleError) else "bundle_or_platform_validation_error"
        report["errors"].append({"stage": stage, "code": code})
        report["checks"][stage]["status"] = "invalid"
        if stage != "rules":
            report["import_status"] = "invalid"
        report["business_readiness"] = {"status": "not_checked", "reason_codes": [code]}
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir", nargs="?")
    parser.add_argument("--inspect", action="store_true", help="Inspect installed built-ins without executing a target")
    args = parser.parse_args(argv)
    if args.inspect and not args.bundle_dir:
        report = inspect_platform_capabilities()
        code = 0 if report["status"] == "valid" else 2
    elif args.bundle_dir and not args.inspect:
        report = validate_bundle(args.bundle_dir)
        code = 1 if report["import_status"] == "invalid" or report["checks"]["rules"]["status"] == "invalid" else (
            0 if report["import_status"] == "valid" else 2)
    else:
        parser.error("Provide BUNDLE_DIR or --inspect, not both")
    print(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
