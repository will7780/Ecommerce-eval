"""Offline regression contract for the Skill, never an Agent/provider evaluation."""

from __future__ import annotations

import builtins
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import pytest


SCRIPT = (Path(__file__).resolve().parents[1] / "skills" / "ecommerce-eval-onboarding"
          / "scripts" / "validate_bundle.py")
BANK_VERSION = "0.3.1"
BASELINE = "0.3.0rc2"
SURFACES = ("business_interface", "file_editor")
DIRECTIONS = "ICTPAMRS"
SOURCE_REFS = ["fixture:confirmed-main-workflow"]
EVIDENCE = {
    "object_scope": "synthetic catalog rows",
    "company_scope": "synthetic tenant",
    "source": "complete independent journal and artifact bytes",
    "collector": "separately reviewed collector required",
    "locator": "fixture:run-scoped-evidence",
    "version_or_hash": "pinned content and policy versions",
    "time_range": "whole task including consumption",
    "completeness": "not established by this offline bundle",
    "missing_impact": "applicable business condition remains unevaluable",
}


@pytest.fixture(autouse=True)
def offline_guard(tmp_path, monkeypatch, isolated_machine_credentials):
    """Fail loudly on forbidden access; do not trust report self-declarations."""
    monkeypatch.setenv("COMMERCE_EVAL_DISABLE_CENTRAL_ENV", "1")
    monkeypatch.setenv("AGENT_API_ENV_FILE", str(tmp_path / "absent-fixture.env"))
    monkeypatch.setenv("COMMERCE_EVAL_HOME", str(tmp_path / "unused-home"))
    for name in tuple(os.environ):
        if name.endswith(("_API_KEY", "_API_TOKEN", "_ACCESS_TOKEN")):
            monkeypatch.delenv(name, raising=False)

    def denied(*args, **kwargs):
        raise AssertionError("offline Skill validation attempted forbidden access")

    from commerce_eval.providers.credentials import CentralEnvStore, CredentialResolver
    from commerce_eval.services.onboarding import OnboardingService
    from commerce_eval.storage import Database, Repository
    from commerce_eval.storage import database as database_module

    for name in ("_read", "_get_secret", "set_secret"):
        monkeypatch.setattr(CentralEnvStore, name, denied)
    monkeypatch.setattr(CredentialResolver, "resolve", denied)
    for name in ("check", "_probe", "_check_target"):
        monkeypatch.setattr(OnboardingService, name, denied)
    for name in ("create_experiment", "save_evaluation"):
        monkeypatch.setattr(Repository, name, denied)
    monkeypatch.setattr(database_module, "default_home", denied)
    monkeypatch.setattr(database_module, "default_database_path", denied)
    monkeypatch.setattr(importlib.metadata, "entry_points", denied)
    monkeypatch.setattr(importlib.metadata.EntryPoint, "load", denied)
    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, denied)
    monkeypatch.setattr(subprocess, "Popen", denied)

    real_import = builtins.__import__
    blocked_modules = (
        "commerce_eval.experiments.runner", "commerce_eval.providers.client",
        "commerce_eval.targets.business_candidate", "commerce_eval.targets.python_target",
        "commerce_eval.targets.http_target", "commerce_eval.demo_runtime",
    )

    def guarded_import(name, *args, **kwargs):
        if any(name == item or name.startswith(item + ".") for item in blocked_modules):
            denied()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    for owner, name in ((builtins, "open"), (io, "open"), (os, "open")):
        original = getattr(owner, name)

        def guarded_open(path, *args, _original=original, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)):
                leaf = Path(os.fsdecode(path)).name.lower()
                if leaf == ".env" or leaf.endswith(".env"):
                    denied()
            return _original(path, *args, **kwargs)

        monkeypatch.setattr(owner, name, guarded_open)

    scratch = tmp_path / "disposable-databases"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    paths, disposed = [], []
    real_init, real_dispose = Database.__init__, Database.dispose

    def init(database, path=None):
        assert path is not None, "helper must pass an explicit database path"
        resolved = Path(path).resolve()
        assert resolved.is_relative_to(scratch.resolve())
        assert not resolved.exists(), "each check needs a fresh database"
        real_init(database, path)
        paths.append(resolved)

    def dispose(database):
        real_dispose(database)
        disposed.append(database.path)

    monkeypatch.setattr(Database, "__init__", init)
    monkeypatch.setattr(Database, "dispose", dispose)
    state = SimpleNamespace(paths=paths, disposed=disposed)
    yield state
    assert disposed == paths
    assert all(not path.parent.exists() for path in paths)
    assert not list(scratch.iterdir())
    assert not (tmp_path / "unused-home").exists()


@pytest.fixture
def helper(offline_guard):
    spec = importlib.util.spec_from_file_location("onboarding_skill_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def example_builder(helper, monkeypatch):
    monkeypatch.setitem(sys.modules, "validate_bundle", helper)
    spec = importlib.util.spec_from_file_location("onboarding_example_under_test", SCRIPT.with_name("build_example.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def canonical(offline_guard):
    from commerce_eval.business.bank import load_business_cases

    return load_business_cases(BANK_VERSION)


class Bundle:
    """Small mutable, real-file bundle; mutations always get fresh inventory hashes."""

    def __init__(self, root, cases):
        self.root = root
        self.files = {}
        self.dataset = {
            "dataset_id": "fixture-catalog", "version": "1", "name": "Synthetic handoff",
            "cases": [case.model_dump(mode="json") for case in cases],
        }
        self.manifest = {
            "bundle_version": "0.1.0", "project_id": "offline-skill-regression",
            "main_workflow": {"id": "catalog-preview", "confirmed": True,
                              "source_refs": list(SOURCE_REFS)},
            "resources": [], "rule_checks": [],
        }
        self.matrix = {
            "directions": [{"id": d, "reason": "Reviewed for the synthetic main workflow"}
                           for d in DIRECTIONS],
            "conditions": [],
        }
        self.add("dataset", "dataset.json", self.dataset, "fixture-catalog")
        for case in self.dataset["cases"]:
            ref = self.case_ref(case)
            self.manifest["rule_checks"].append({
                **ref, "profile_bank_version": BANK_VERSION,
                "profile_case_id": case.get("scenario_id"),
            })
            for requirement in case.get("business_requirements", []):
                self.matrix["conditions"].append({
                    "id": case["case_id"] + ":" + requirement["requirement_id"],
                    "direction": case["scenario_id"][0], "applicability": "applies",
                    "support": "existing", "evidence": "missing", "use": "business_gate",
                    "reason": "Applicable independently observable business requirement",
                    "source_refs": list(SOURCE_REFS),
                    "verifier_id": requirement["verifier_id"],
                    "verifier_version": requirement["verifier_version"],
                    "case_refs": [{**ref, "requirement_ids": [requirement["requirement_id"]]}],
                    "evidence_requirements": [deepcopy(EVIDENCE)],
                })

    @staticmethod
    def case_ref(case, version="1"):
        return {"dataset_id": "fixture-catalog", "dataset_version": version,
                "case_id": case["case_id"]}

    def add(self, kind, name, payload, identifier, version="1", **extra):
        path = "importable/" + name
        item = {"path": path, "kind": kind, "id": identifier, "version": version,
                "order": len(self.manifest["resources"]), "depends_on": [], **extra}
        self.manifest["resources"].append(item)
        self.files[path] = payload
        return item

    def write(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for relative, payload in self.files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=True)
            raw = text.encode("utf-8")
            path.write_bytes(raw)
            for item in self.manifest["resources"]:
                if item["path"] == relative:
                    item["sha256"] = hashlib.sha256(raw).hexdigest()
        (self.root / "applicability.json").write_text(json.dumps(self.matrix), encoding="utf-8")
        self.write_manifest()
        return self.root

    def write_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")


@pytest.fixture
def bundle(tmp_path, canonical):
    return Bundle(tmp_path / "bundle", canonical[:1])


@pytest.fixture
def import_spy(monkeypatch, offline_guard):
    from commerce_eval.services.imports import ImportService

    preview_impl, commit_impl = ImportService.preview, ImportService.commit
    state = SimpleNamespace(previews=[], commits=[], datasets=[])

    def preview(service, project_id, kind, files, options=None):
        result = preview_impl(service, project_id, kind, files, options)
        state.previews.append({"kind": kind, "result": result,
                               "database": service.repository.database.path})
        return result

    def commit(service, import_id):
        result = commit_impl(service, import_id)
        state.commits.append(result)
        assert service.repository.list_experiments() == []
        for ref in result["resources"]:
            if ref["kind"] == "dataset":
                state.datasets.append(service.repository.get_dataset(
                    ref["project_id"], ref["dataset_id"], ref["version"]))
        return result

    monkeypatch.setattr(ImportService, "preview", preview)
    monkeypatch.setattr(ImportService, "commit", commit)
    return state


def assert_rejected(report, stage, code):
    assert report["import_status"] == "invalid", report
    assert report["checks"][stage]["status"] == "invalid"
    assert {"stage": stage, "code": code} in report["errors"]
    assert report["business_readiness"]["status"] != "ready"
    assert report["execution_performed"] is False
    assert report["credentials_accessed"] is False


def test_canonical_all_32_real_import_and_two_surface_conformance(
    helper, canonical, tmp_path, import_spy, offline_guard, monkeypatch,
):
    from commerce_eval.business import fixtures, verifiers

    assert len(canonical) == 32
    assert Counter(case.scenario_id[0] for case in canonical) == dict.fromkeys(DIRECTIONS, 4)
    cases = [case.model_copy(deep=True) for case in canonical]
    for case in cases:
        case.case_id = "adapted-" + case.scenario_id
        case.name = "Renamed synthetic case " + case.scenario_id
        case.version = "handoff-1"
        for index, requirement in enumerate(case.business_requirements):
            requirement.requirement_id = "adapted-condition-" + str(index)
    bundle = Bundle(tmp_path / "all-cases", cases)
    evaluated, generated = [], {}
    evaluate_impl = verifiers.evaluate_business_requirements
    negative_impl = fixtures.negative_business_variants

    def evaluate(case, evidence):
        result = evaluate_impl(case, evidence)
        evaluated.append((case.scenario_id, evidence is None, result.status.value))
        return result

    def negatives(profile, surface):
        variants = negative_impl(profile, surface)
        recipes = profile.scenario_data["references"]["mutants"]
        assert [(v["name"], v["requirement_id"]) for v in variants] == [
            (r["name"], r["requirement_id"]) for r in recipes]
        generated[(profile.scenario_id, surface)] = len(variants)
        return variants

    monkeypatch.setattr(verifiers, "evaluate_business_requirements", evaluate)
    monkeypatch.setattr(fixtures, "negative_business_variants", negatives)
    report = helper.validate_bundle(bundle.write())
    assert report["errors"] == []
    assert report["import_status"] == "valid", report
    assert [p["result"]["status"] for p in import_spy.previews] == ["ready"]
    assert [c["status"] for c in import_spy.commits] == ["committed"]
    assert len(import_spy.datasets[0]["cases"]) == 32
    assert {c["case_id"] for c in import_spy.datasets[0]["cases"]} == {c.case_id for c in cases}
    assert report["temporary_environment_cleaned"] is True
    assert len(offline_guard.paths) == 1
    assert report["execution_performed"] is report["credentials_accessed"] is False
    assert report["business_readiness"]["status"] == "evidence_required"
    rules = report["checks"]["rules"]
    assert rules["status"] == "valid"
    assert len(rules["cases"]) == 32
    by_id = {row["case_id"]: row for row in rules["cases"]}
    assert len(generated) == 32 * len(SURFACES)
    for case in cases:
        row = by_id[case.case_id]
        assert row["status"] == "valid"
        assert {check["surface"] for check in row["checks"]} == set(SURFACES)
        for check in row["checks"]:
            assert check["valid"] is True
            assert check["positive"] == "pass"
            assert check["missing_evidence"] == "error"
            statuses = check["negative_statuses"]
            assert len(statuses) == generated[(case.scenario_id, check["surface"])] >= 3
            assert set(statuses) <= {"fail", "error"}
        actual_calls = [v for v in evaluated if v[0] == case.scenario_id]
        assert len(actual_calls) == sum(generated[(case.scenario_id, s)] + 2 for s in SURFACES)
        assert sum(missing for _, missing, _ in actual_calls) == 2
        assert sum(status == "pass" for _, _, status in actual_calls) == 2
    assert report["coverage"]["counts"]["applicable"] == sum(len(c.business_requirements) for c in cases)
    assert report["coverage"]["counts"]["covered"] == report["coverage"]["counts"]["applicable"]


@pytest.mark.parametrize("mutation", ["expected", "task", "environment", "gate"])
def test_changed_scoring_signature_imports_but_is_not_verified(helper, bundle, mutation):
    case = bundle.dataset["cases"][0]
    if mutation == "expected":
        case["business_requirements"][0]["expected"]["company_id"] = "another-tenant"
    elif mutation == "task":
        case["input"]["message"] = "Publish immediately instead of preparing a preview."
    elif mutation == "environment":
        case["scenario_data"]["environment"]["company_id"] = "another-tenant"
    else:
        case["gates"][0]["expected"] = False
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == "valid"
    assert report["checks"]["rules"]["status"] == "not_checked"
    assert report["checks"]["rules"]["cases"][0]["reason_codes"] == [
        "custom_configuration_requires_reviewed_fixtures"]
    assert report["business_readiness"]["status"] == "not_checked"


@pytest.mark.parametrize("location", ["expected", "rule-check"])
def test_uploaded_expression_cannot_execute_or_certify_changed_rule(helper, bundle, tmp_path, location):
    marker = tmp_path / "expression-must-not-execute.txt"
    expression = "__import__('pathlib').Path(" + repr(marker.as_posix()) + ").write_text('executed') or True"
    requirement = bundle.dataset["cases"][0]["business_requirements"][0]
    requirement["expected"]["company_id"] = "different-synthetic-company"
    if location == "expected":
        requirement["expected"]["expression"] = expression
    else:
        bundle.manifest["rule_checks"][0]["expression"] = expression
    root = bundle.write()
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    report = helper.validate_bundle(root)
    assert not marker.exists()
    assert report["import_status"] == "valid"
    assert report["checks"]["rules"]["status"] == "not_checked"
    assert report["checks"]["rules"]["cases"][0]["reason_codes"] == [
        "custom_configuration_requires_reviewed_fixtures"]
    assert report["business_readiness"]["status"] == "not_checked"
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("field,value", [("verifier_id", "fixture_unknown_verifier"),
                                         ("verifier_version", "999.0")])
def test_unknown_business_verifier_is_importable_but_unsupported(helper, bundle, field, value):
    bundle.dataset["cases"][0]["business_requirements"][0][field] = value
    bundle.matrix["conditions"][0][field] = value
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == "valid"
    assert report["checks"]["rules"]["status"] == "invalid"
    assert report["checks"]["rules"]["cases"][0]["reason_codes"] == ["business_verifier_unavailable"]
    assert report["business_readiness"]["status"] == "unsupported"


@pytest.mark.parametrize("where", ["gate", "evaluator-set"])
def test_unknown_metric_rejected_by_references_or_real_import(helper, bundle, import_spy, where):
    if where == "gate":
        bundle.dataset["cases"][0]["gates"][0]["metric_id"] = "fixture_unknown_metric"
    else:
        bundle.add("evaluator-set", "evaluators.json", {
            "set_id": "fixture-evaluators", "version": "1", "metric_ids": ["fixture_unknown_metric"],
        }, "fixture-evaluators")
    report = helper.validate_bundle(bundle.write())
    if where == "gate":
        assert_rejected(report, "references", "metric_reference_missing")
        assert import_spy.previews == []
    else:
        assert_rejected(report, "import", "platform_preview_rejected")
        assert [p["result"]["status"] for p in import_spy.previews] == ["ready", "invalid"]
        assert len(import_spy.commits) == 1
        assert report["temporary_environment_cleaned"] is True


@pytest.mark.parametrize("failure", ["preview", "commit", "initialize"])
def test_disposable_database_removed_even_when_import_fails(
    helper, bundle, monkeypatch, offline_guard, failure,
):
    from commerce_eval.services.imports import ImportService
    from commerce_eval.storage import Database

    if failure == "preview":
        bundle.add("products", "invalid.csv", "sku,price,currency\nITEM-1,-1,EUR\n", "fixture-products")
    else:
        def fail(*args, **kwargs):
            raise ValueError("fixture failure must not leak internal details")

        monkeypatch.setattr(ImportService if failure == "commit" else Database, failure, fail)
    report = helper.validate_bundle(bundle.write())
    assert_rejected(report, "import", "platform_preview_rejected" if failure == "preview"
                    else "bundle_or_platform_validation_error")
    assert report["temporary_environment_cleaned"] is True
    assert len(offline_guard.paths) == len(offline_guard.disposed) == 1
    assert not offline_guard.paths[0].parent.exists()


@pytest.mark.parametrize("dependency", ["missing", "forward", "self"])
def test_dependency_inventory_rejects_missing_forward_and_self_refs(helper, bundle, import_spy, dependency):
    second = bundle.add("rules", "rules.md", "Synthetic policy only.", "fixture-policy")
    first = bundle.manifest["resources"][0]
    first["depends_on"] = [{"missing": "importable/absent.json", "forward": second["path"],
                            "self": first["path"]}[dependency]]
    report = helper.validate_bundle(bundle.write())
    assert_rejected(report, "structure", "dependency_missing_or_out_of_order")
    assert import_spy.previews == []


def test_valid_dependencies_import_in_declared_order_not_inventory_order(helper, bundle, import_spy):
    second = bundle.add("evaluator-set", "evaluators.json", {
        "set_id": "fixture-evaluators", "version": "1", "metric_ids": ["business_acceptance_pass"],
    }, "fixture-evaluators", depends_on=["importable/dataset.json"])
    bundle.manifest["resources"].reverse()
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == "valid"
    assert [p["kind"] for p in import_spy.previews] == ["dataset", "evaluator-set"]
    assert report["resources"][-1] == {"path": second["path"], "status": "valid"}


@pytest.mark.parametrize("conflict", ["case", "dataset", "independent-version"])
def test_duplicate_version_identity_cannot_overwrite_previous_import(helper, bundle, import_spy, conflict):
    duplicate = deepcopy(bundle.dataset)
    if conflict == "case":
        duplicate["cases"][0]["input"]["message"] = "Changed task under the same case version"
    else:
        duplicate["name"] = "Changed dataset metadata"
    if conflict == "independent-version":
        duplicate["version"] = "2"
        second_version_conditions = deepcopy(bundle.matrix["conditions"])
        for condition in second_version_conditions:
            condition["id"] += "-version-2"
            for ref in condition["case_refs"]:
                ref["dataset_version"] = "2"
        bundle.matrix["conditions"].extend(second_version_conditions)
    bundle.add("dataset", "second-dataset.json", duplicate, "fixture-catalog", duplicate["version"])
    report = helper.validate_bundle(bundle.write())
    if conflict == "case":
        assert_rejected(report, "references", "case_version_conflict")
        assert import_spy.previews == []
    elif conflict == "dataset":
        assert_rejected(report, "import", "platform_preview_rejected")
        assert len(import_spy.commits) == 1
        assert report["temporary_environment_cleaned"] is True
        assert any(e["code"] == "version_immutable_conflict"
                   for e in import_spy.previews[-1]["result"]["errors"])
    else:
        assert report["import_status"] == "valid"
        assert [d["version"] for d in import_spy.datasets] == ["1", "2"]
        assert {r["dataset_version"] for r in report["checks"]["rules"]["cases"]} == {"1", "2"}


@pytest.mark.parametrize("location", ["inventory", "bytes"])
def test_hash_mismatch_stops_before_import(helper, bundle, import_spy, location):
    root = bundle.write()
    if location == "inventory":
        bundle.manifest["resources"][0]["sha256"] = "0" * 64
        bundle.write_manifest()
    else:
        with (root / "importable/dataset.json").open("ab") as stream:
            stream.write(b" ")
    assert_rejected(helper.validate_bundle(root), "structure", "file_hash_mismatch")
    assert import_spy.previews == []


@pytest.mark.parametrize("path", ["importable/../../outside.json", "importable/../outside.json",
                                 "importable/C:/outside.json", "importable/..\\outside.json",
                                 "/outside.json"])
def test_nonconfined_paths_rejected_without_reading_them(helper, bundle, import_spy, path):
    root = bundle.write()
    bundle.manifest["resources"][0]["path"] = path
    bundle.write_manifest()
    code = "path_not_relative" if path.startswith("importable/") else "resource_not_importable_path"
    assert_rejected(helper.validate_bundle(root), "structure", code)
    assert import_spy.previews == []


@pytest.mark.parametrize("link_kind", ["file", "directory", "junction"])
def test_symlink_escape_never_reads_external_target(helper, bundle, tmp_path, monkeypatch, link_kind):
    root = bundle.write()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "data.json"
    target.write_text("{}", encoding="utf-8")
    link = root / "importable" / ("linked.json" if link_kind == "file" else "linked-dir")
    try:
        if link_kind == "junction":
            if os.name != "nt":
                pytest.skip("Windows junction regression")
            import _winapi

            _winapi.CreateJunction(str(outside), str(link))
        else:
            link.symlink_to(target if link_kind == "file" else outside,
                            target_is_directory=link_kind == "directory")
    except OSError as error:
        pytest.skip("OS does not permit temporary symlinks: " + type(error).__name__)
    bundle.manifest["resources"][0]["path"] = (
        "importable/linked.json" if link_kind == "file" else "importable/linked-dir/data.json")
    bundle.write_manifest()
    real_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert not path.resolve().is_relative_to(outside.resolve()), "escaped bytes were read"
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    assert_rejected(helper.validate_bundle(root), "structure", "linked_path_forbidden")


@pytest.mark.parametrize("mutation,code", [
    ("duplicate-key", "duplicate_json_key"), ("non-finite", "non_finite_number"),
    ("unlisted", "unlisted_importable_file"), ("oversized-file", "file_size_or_type"),
    ("oversized-bundle", "bundle_size_limit"), ("duplicate-order", "resource_order_or_path_duplicate"),
])
def test_bounded_inventory_and_parser_fail_before_import(helper, bundle, import_spy, monkeypatch, mutation, code):
    if mutation == "duplicate-key":
        bundle.files["importable/dataset.json"] = '{"cases":[],"cases":[]}'
    elif mutation == "non-finite":
        bundle.files["importable/dataset.json"] = '{"cases":[],"extra":NaN}'
    elif mutation == "duplicate-order":
        bundle.add("rules", "rules.md", "Synthetic policy.", "fixture-policy", order=0)
    root = bundle.write()
    if mutation == "unlisted":
        (root / "importable/not-in-inventory.json").write_text("{}", encoding="utf-8")
    elif mutation == "oversized-file":
        monkeypatch.setattr(helper, "MAX_FILE", (root / "importable/dataset.json").stat().st_size - 1)
    elif mutation == "oversized-bundle":
        total = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        monkeypatch.setattr(helper, "MAX_BUNDLE", total - 1)
    assert_rejected(helper.validate_bundle(root), "structure", code)
    assert import_spy.previews == []


@pytest.mark.parametrize("mutation", ["false-positive", "missing-positive", "too-few-negatives"])
def test_weak_conformance_fixtures_do_not_verify_rules(helper, bundle, monkeypatch, mutation):
    from commerce_eval.business import fixtures

    positive_impl = fixtures.positive_business_evidence
    negative_impl = fixtures.negative_business_variants

    if mutation == "missing-positive":
        monkeypatch.setattr(fixtures, "positive_business_evidence", lambda *args: None)
        # Preserve independent genuine negatives while removing only the positive evidence.
        profile = bundle.dataset["cases"][0]["scenario_id"]
        from commerce_eval.business.bank import load_business_cases

        canonical = next(c for c in load_business_cases(BANK_VERSION) if c.scenario_id == profile)
        with monkeypatch.context() as local:
            local.setattr(fixtures, "positive_business_evidence", positive_impl)
            negatives = {s: negative_impl(canonical, s) for s in SURFACES}
        monkeypatch.setattr(fixtures, "negative_business_variants", lambda case, surface: negatives[surface])
    else:
        def negatives(case, surface):
            variants = negative_impl(case, surface)
            if mutation == "too-few-negatives":
                return variants[:2]
            variants[0]["evidence"] = positive_impl(case, surface)
            return variants

        monkeypatch.setattr(fixtures, "negative_business_variants", negatives)
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == "valid"
    assert report["checks"]["rules"]["status"] == "invalid"
    assert report["business_readiness"]["status"] == "unsupported"
    checks = report["checks"]["rules"]["cases"][0]["checks"]
    assert len(checks) == 2
    assert all(check["valid"] is False for check in checks)


@pytest.mark.parametrize("profile", ["unselected", "unknown-case", "unknown-version"])
def test_absent_conformance_profile_keeps_import_and_rule_status_separate(helper, bundle, profile):
    check = bundle.manifest["rule_checks"][0]
    if profile == "unselected":
        bundle.manifest["rule_checks"] = []
    elif profile == "unknown-case":
        check["profile_case_id"] = "absent-profile"
    else:
        check["profile_bank_version"] = "999.0"
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == "valid"
    assert report["checks"]["rules"]["status"] == "not_checked"
    assert report["business_readiness"]["status"] == "not_checked"


def test_repeat_validation_uses_new_database_each_time(helper, bundle, offline_guard, import_spy):
    root = bundle.write()
    first, second = helper.validate_bundle(root), helper.validate_bundle(root)
    assert first == second
    assert first["import_status"] == "valid"
    assert len(set(offline_guard.paths)) == 2
    assert len(import_spy.commits) == 2
    assert all(not path.parent.exists() for path in offline_guard.paths)


def test_example_builder_keeps_unresolved_recovery_visible(example_builder, tmp_path, import_spy):
    destination = tmp_path / "materialized-example"
    report = example_builder.build_example(destination)
    assert report["import_status"] == report["checks"]["rules"]["status"] == "valid"
    assert report["business_readiness"]["status"] == "not_checked"
    assert report["coverage"]["counts"]["pending_confirmation"] == 1
    assert report["coverage"]["counts"]["uncovered"] == 1
    assert report["coverage"]["counts"]["applicable"] == len(report["coverage"]["conditions"])
    assert [p["kind"] for p in import_spy.previews] == ["tool-contracts", "evaluator-set", "dataset"]
    matrix = json.loads((destination / "applicability.json").read_text(encoding="utf-8"))
    assert {d["id"] for d in matrix["directions"]} == set(DIRECTIONS)
    pending = [r for r in matrix["conditions"] if r["applicability"] == "needs_confirmation"]
    assert len(pending) == 1 and pending[0]["case_refs"] == []
    assert json.loads((destination / "validation-report.json").read_text(encoding="utf-8")) == report
    before = {p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        example_builder.build_example(destination)
    assert {p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()} == before


def test_example_builder_is_reproducible_in_new_and_empty_directories(example_builder, tmp_path, offline_guard):
    first, second = tmp_path / "new-example", tmp_path / "empty-example"
    second.mkdir()
    first_report = example_builder.build_example(first)
    second_report = example_builder.build_example(second)
    assert first_report == second_report
    assert first_report["import_status"] == "valid"
    files = lambda root: {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert files(first) == files(second)
    assert len(set(offline_guard.paths)) == 2


@pytest.mark.parametrize("existing", ["user-owned.txt", "nested/keep.txt"])
def test_example_builder_protects_preexisting_user_files(example_builder, tmp_path, import_spy, existing):
    destination = tmp_path / "protected-example"
    owned = destination / existing
    owned.parent.mkdir(parents=True)
    owned.write_bytes(b"preexisting synthetic user content")
    before = {p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
    with pytest.raises(ValueError) as error:
        example_builder.build_example(destination)
    assert error.value.args == ("example_destination_must_be_empty",)
    assert {p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()} == before
    assert not (destination / "importable").exists()
    assert import_spy.previews == import_spy.commits == []


@pytest.mark.parametrize("location", ["input", "conversation"])
@pytest.mark.parametrize("field", ["reference_answer", "future_answers", "defect_labels", "gates"])
def test_private_oracles_cannot_enter_candidate_visible_input(helper, bundle, location, field):
    case = bundle.dataset["cases"][0]
    leak = {"nested": [{field: "synthetic evaluator-only value"}]}
    if location == "input":
        case["input"]["extra"] = leak
    else:
        case["conversation"] = [{"type": "user_message", "content": "Inspect the catalog.",
                                 "supplied_facts": leak}]
    assert_rejected(helper.validate_bundle(bundle.write()), "references", "forbidden_field")


def test_public_user_conversation_imports_without_event_type_regression(helper, bundle, import_spy):
    bundle.dataset["cases"][0]["conversation"] = [
        {"type": "user_message", "content": "Use market DE.", "supplied_facts": {"site": "DE"}},
        {"type": "interaction_response", "interaction_id": "fixture-question", "response": {"site": "DE"}},
    ]
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == "valid", report
    assert len(import_spy.datasets[0]["cases"][0]["conversation"]) == 2
    assert report["checks"]["rules"]["status"] == "not_checked"


@pytest.mark.parametrize("field", ["api_key", "API-KEY", "password", "access_token",
                                  "trusted", "hidden_reasoning", "chain_of_thought"])
@pytest.mark.parametrize("location", ["manifest", "matrix", "dataset"])
def test_sensitive_json_fields_rejected_without_echo(helper, bundle, field, location):
    marker = "synthetic-sensitive-fixture-do-not-echo"
    owner = {"manifest": bundle.manifest, "matrix": bundle.matrix,
             "dataset": bundle.dataset["cases"][0]["input"]}[location]
    owner["extra"] = [{field: marker}]
    report = helper.validate_bundle(bundle.write())
    assert_rejected(report, "structure", "forbidden_field")
    assert marker not in json.dumps(report)


@pytest.mark.parametrize("format", ["json", "csv"])
def test_secret_shaped_text_rejected_without_echo(helper, bundle, format):
    marker = "sk-" + "synthetic-not-a-real-key-123456"
    if format == "json":
        bundle.dataset["cases"][0]["input"]["note"] = marker
    else:
        bundle.add("products", "products.csv", "sku,price,currency,note\nITEM,1,EUR," + marker + "\n",
                   "fixture-products")
    report = helper.validate_bundle(bundle.write())
    assert_rejected(report, "structure", "sensitive_content")
    assert marker not in json.dumps(report)


@pytest.mark.parametrize("field", ["api_key", "password", "access_token", "hidden_reasoning", "trusted"])
def test_sensitive_csv_columns_rejected_before_import(helper, bundle, import_spy, field):
    bundle.add("products", "products.csv", "sku,price,currency," + field
               + "\nITEM,1,EUR,synthetic-protected-value\n", "fixture-products")
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == "invalid", report
    assert report["business_readiness"]["status"] != "ready"
    assert not any(p["kind"] == "products" for p in import_spy.previews)
    assert "synthetic-protected-value" not in json.dumps(report)


@pytest.mark.parametrize("text,code", [
    ("sku,price,currency,price\nITEM,1,EUR,2\n", "csv_header_invalid"),
    ("sku,price,currency\nITEM,1,EUR,unlisted-cell\n", "csv_row_invalid"),
    ("sku,price,currency,API-KEY\nITEM,1,EUR,synthetic-only\n", "forbidden_field"),
])
def test_csv_shape_and_normalized_sensitive_headers_fail_closed(helper, bundle, import_spy, text, code):
    bundle.add("products", "products.csv", text, "fixture-products")
    assert_rejected(helper.validate_bundle(bundle.write()), "structure", code)
    assert import_spy.previews == []


@pytest.mark.parametrize("name", ["assessment.md", "evidence-gaps.md", "cases-draft.md", "next-steps.md"])
@pytest.mark.parametrize("content_kind", ["sensitive", "oversized"])
def test_optional_narratives_are_scanned_and_bounded(helper, bundle, monkeypatch, import_spy, name, content_kind):
    root = bundle.write()
    marker = "sk-" + "synthetic-narrative-fixture-123456"
    if content_kind == "sensitive":
        content, code = "Synthetic prose containing " + marker, "sensitive_content"
    else:
        maximum = max(p.stat().st_size for p in root.rglob("*") if p.is_file()) + 1
        monkeypatch.setattr(helper, "MAX_FILE", maximum)
        content, code = "x" * (maximum + 1), "file_size_or_type"
    (root / name).write_text(content, encoding="utf-8")
    report = helper.validate_bundle(root)
    assert_rejected(report, "structure", code)
    assert import_spy.previews == []
    assert marker not in json.dumps(report)


@pytest.mark.parametrize("execution_mode", ["dry_run", "sandbox"])
def test_reviewed_http_target_imports_without_probe(helper, bundle, import_spy, execution_mode):
    bundle.add("target", "target.json", {
        "target_id": "fixture-target", "version": "1", "name": "Synthetic HTTP target",
        "adapter_type": "http", "safe_for_eval": True,
        "config": {"base_url": "http://127.0.0.1:1"},
    }, "fixture-target", safety_review={"confirmed": True, "source_refs": list(SOURCE_REFS),
                                        "execution_mode": execution_mode})
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == "valid", report
    assert [p["kind"] for p in import_spy.previews] == ["dataset", "target"]
    assert report["execution_performed"] is False
    assert report["business_readiness"]["status"] == "evidence_required"


@pytest.mark.parametrize("mutation,code", [
    ("unreviewed", "target_review_required"), ("no-review-source", "target_review_required"),
    ("unsafe", "unsafe_target"), ("live-mode", "unsafe_target"), ("missing-mode", "unsafe_target"),
    ("python", "registered_python_target_handoff_only"),
])
def test_unsafe_target_is_rejected_before_import(helper, bundle, import_spy, mutation, code):
    payload = {"target_id": "fixture-target", "version": "1", "name": "Synthetic target",
               "adapter_type": "http", "safe_for_eval": True,
               "config": {"base_url": "http://127.0.0.1:1"}}
    review = {"confirmed": True, "source_refs": list(SOURCE_REFS), "execution_mode": "dry_run"}
    if mutation == "unreviewed":
        review["confirmed"] = False
    elif mutation == "no-review-source":
        review["source_refs"] = []
    elif mutation == "unsafe":
        payload["safe_for_eval"] = False
    elif mutation == "live-mode":
        review["execution_mode"] = "production"
    elif mutation == "missing-mode":
        review.pop("execution_mode")
    else:
        payload.update(adapter_type="python", config={"command": ["never-run-fixture"]})
    bundle.add("target", "target.json", payload, "fixture-target", safety_review=review)
    assert_rejected(helper.validate_bundle(bundle.write()), "references", code)
    assert import_spy.previews == []


def test_legacy_case_import_is_not_business_rule_verification(helper, bundle, import_spy):
    bundle.dataset["cases"] = [{"contract_version": "1.0", "case_id": "legacy-case",
                                "name": "Legacy read-only task", "input": {"message": "Inspect the catalog."}}]
    bundle.manifest["rule_checks"] = []
    condition = bundle.matrix["conditions"][0]
    condition.update(use="diagnostic", case_refs=[bundle.case_ref(bundle.dataset["cases"][0])])
    bundle.matrix["conditions"] = [condition]
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == "valid", report
    assert import_spy.datasets[0]["cases"][0]["contract_version"] == "1.0"
    assert report["checks"]["rules"]["status"] == "not_checked"
    assert report["checks"]["rules"]["cases"][0]["status"] == "not_checked"
    assert report["business_readiness"]["status"] == "not_checked"


def test_unconfirmed_main_workflow_never_creates_database(helper, bundle, import_spy, offline_guard):
    bundle.manifest["main_workflow"]["confirmed"] = False
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == report["checks"]["rules"]["status"] == "not_checked"
    assert report["checks"]["references"]["status"] == "valid"
    assert report["business_readiness"]["reason_codes"] == ["main_workflow_confirmation_required"]
    assert import_spy.previews == import_spy.commits == offline_guard.paths == []
    assert report["temporary_environment_cleaned"] is False


@pytest.mark.parametrize("evidence", ["missing", "partial", "untrusted", "sufficient"])
def test_evidence_readiness_is_not_na_or_self_certified_ready(helper, bundle, evidence):
    for condition in bundle.matrix["conditions"]:
        condition["evidence"] = evidence
    na = deepcopy(bundle.matrix["conditions"][0])
    na.update(id="legitimately-not-applicable", applicability="not_applicable",
              case_refs=[], evidence_requirements=[])
    bundle.matrix["conditions"].append(na)
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == report["checks"]["rules"]["status"] == "valid"
    expected = "integration_required" if evidence == "sufficient" else "evidence_required"
    assert report["business_readiness"]["status"] == expected
    rows = report["coverage"]["conditions"]
    assert all(r["status"] == expected and r["applicability"] == "applies" for r in rows[:-1])
    assert rows[-1]["applicability"] == "not_applicable"
    assert rows[-1]["status"] == "not_checked"
    counts = report["coverage"]["counts"]
    assert counts["not_applicable"] == 1
    assert counts["applicable"] == counts["covered"] == len(rows) - 1
    assert counts["evidence_required"] == (0 if evidence == "sufficient" else len(rows) - 1)


def test_all_eight_directions_and_blocked_conditions_remain_in_denominator(helper, bundle):
    canonical_rows = deepcopy(bundle.matrix["conditions"])
    baseline_count = len(canonical_rows)
    template = bundle.matrix["conditions"][0]
    rows = []
    for direction in DIRECTIONS:
        row = deepcopy(template)
        row.update(id="direction-" + direction, direction=direction, case_refs=[])
        if direction == "I":
            row["case_refs"] = deepcopy(template["case_refs"])
        elif direction in "CT":
            row["support"] = "extension_needed"
        elif direction == "P":
            row["applicability"] = "needs_confirmation"
        elif direction == "A":
            row.update(applicability="not_applicable", evidence_requirements=[])
        elif direction == "M":
            row["evidence"] = "sufficient"
        elif direction == "R":
            row["evidence"] = "untrusted"
        rows.append(row)
    bundle.matrix["conditions"] = canonical_rows + rows
    report = helper.validate_bundle(bundle.write())
    assert report["import_status"] == "valid"
    assert report["business_readiness"]["status"] == "unsupported"
    coverage = report["coverage"]
    assert coverage["counts"] == {
        "total": baseline_count + 8, "applicable": baseline_count + 7, "covered": baseline_count + 1,
        "pending_confirmation": 1, "evidence_required": baseline_count + 6,
        "extension_required": 2, "uncovered": 6, "not_applicable": 1,
    }
    assert coverage["counts_overlap"] is True
    assert {r["condition_id"] for r in coverage["conditions"]} == {r["id"] for r in canonical_rows + rows}
    assert [r["status"] for r in coverage["conditions"][:baseline_count]] == ["evidence_required"] * baseline_count
    assert [r["status"] for r in coverage["conditions"][baseline_count:]] == [
        "evidence_required", "unsupported", "unsupported", "not_checked", "not_checked",
        "integration_required", "evidence_required", "evidence_required",
    ]


@pytest.mark.parametrize("omission", ["row", "case-ref", "masked-as-na"])
def test_applicable_case_requirements_cannot_disappear_from_matrix(helper, bundle, import_spy, omission):
    row = bundle.matrix["conditions"][0]
    omitted = row["case_refs"][0]["requirement_ids"][0]
    case = bundle.dataset["cases"][0]
    assert any(r["requirement_id"] == omitted and r["applicable"] for r in case["business_requirements"])
    if omission == "row":
        bundle.matrix["conditions"].pop(0)
    elif omission == "case-ref":
        row["case_refs"] = []
    else:
        row["applicability"] = "not_applicable"
    report = helper.validate_bundle(bundle.write())
    assert_rejected(report, "references", "case_requirement_not_in_matrix")
    assert report["checks"]["import"]["status"] == report["checks"]["rules"]["status"] == "not_checked"
    assert import_spy.previews == import_spy.commits == []


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown"])
def test_eight_direction_review_cannot_be_shrunk_or_faked(helper, bundle, mutation):
    directions = bundle.matrix["directions"]
    if mutation == "missing":
        directions.pop()
    else:
        directions[-1]["id"] = "I" if mutation == "duplicate" else "X"
    assert_rejected(helper.validate_bundle(bundle.write()), "references", "eight_direction_review_required")


@pytest.mark.parametrize("mutation,code", [
    ("missing-verifier", "condition_verifier_required"),
    ("missing-version", "condition_verifier_required"),
    ("missing-requirements", "condition_requirement_reference_required"),
    ("empty-requirements", "condition_requirement_reference_required"),
    ("wrong-requirements-type", "condition_requirement_reference_required"),
    ("unknown-requirement", "condition_verifier_reference_mismatch"),
    ("unknown-verifier", "condition_verifier_reference_mismatch"),
    ("wrong-version", "condition_verifier_reference_mismatch"),
    ("inapplicable-requirement", "condition_verifier_reference_mismatch"),
    ("unknown-case", "case_reference_missing"),
    ("unknown-dataset-version", "case_reference_missing"),
    ("unconfirmed", "unconfirmed_rule_must_remain_draft"),
])
def test_matrix_binds_confirmed_conditions_to_applicable_versioned_requirements(
    helper, bundle, import_spy, mutation, code,
):
    row = bundle.matrix["conditions"][0]
    ref = row["case_refs"][0]
    if mutation == "missing-verifier":
        row.pop("verifier_id")
    elif mutation == "missing-version":
        row.pop("verifier_version")
    elif mutation == "missing-requirements":
        ref.pop("requirement_ids")
    elif mutation == "empty-requirements":
        ref["requirement_ids"] = []
    elif mutation == "wrong-requirements-type":
        ref["requirement_ids"] = ref["requirement_ids"][0]
    elif mutation == "unknown-requirement":
        ref["requirement_ids"] = ["absent-requirement"]
    elif mutation == "unknown-verifier":
        row["verifier_id"] = "absent-verifier"
    elif mutation == "wrong-version":
        row["verifier_version"] = "1.0"
    elif mutation == "inapplicable-requirement":
        bundle.dataset["cases"][0]["business_requirements"][0]["applicable"] = False
    elif mutation == "unknown-case":
        ref["case_id"] = "absent-case"
    elif mutation == "unknown-dataset-version":
        ref["dataset_version"] = "absent-version"
    else:
        row["applicability"] = "needs_confirmation"
    assert_rejected(helper.validate_bundle(bundle.write()), "references", code)
    assert import_spy.previews == []


def test_editable_stale_metadata_warns_and_inspects_actual_runtime(helper, monkeypatch):
    import commerce_eval

    monkeypatch.setattr(commerce_eval, "__version__", BASELINE)
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "0.1.0")
    monkeypatch.setattr(importlib.metadata, "distribution", lambda name: SimpleNamespace(
        read_text=lambda filename: json.dumps({"dir_info": {"editable": True}})))
    report = helper.inspect_platform_capabilities()
    assert report["status"] == "valid"
    assert report["platform_version"] == BASELINE
    assert report["distribution_version"] == "0.1.0"
    assert report["reason_codes"] == ["editable_distribution_metadata_stale_using_inspected_runtime"]
    assert report["bank_version"] == BANK_VERSION
    assert len(report["cases"]) == 32
    assert report["plugins_loaded"] is report["external_collector_upload"] is False
    assert "business_acceptance_pass" in {m["metric_id"] for m in report["metrics"]}


@pytest.mark.parametrize("platform", ["unknown-runtime", "missing-import", "noneditable-mismatch", "unknown-bank"])
def test_unavailable_platform_stays_draft_and_does_not_import(
    helper, bundle, monkeypatch, import_spy, offline_guard, platform,
):
    import commerce_eval
    from commerce_eval.business import bank

    if platform == "unknown-runtime":
        monkeypatch.setattr(commerce_eval, "__version__", "999.0")
    elif platform == "missing-import":
        monkeypatch.setitem(sys.modules, "commerce_eval", None)
    elif platform == "noneditable-mismatch":
        monkeypatch.setattr(importlib.metadata, "version", lambda name: "0.1.0")
        monkeypatch.setattr(importlib.metadata, "distribution", lambda name: SimpleNamespace(
            read_text=lambda filename: json.dumps({"dir_info": {"editable": False}})))
    else:
        monkeypatch.setattr(bank, "VERSION", "999.0")
    report = helper.validate_bundle(bundle.write())
    assert report["platform"]["status"] == "not_checked"
    assert report["import_status"] == report["business_readiness"]["status"] == "not_checked"
    assert report["checks"]["structure"]["status"] == "valid"
    assert all(report["checks"][stage]["status"] == "not_checked"
               for stage in ("references", "import", "rules"))
    assert import_spy.previews == import_spy.commits == offline_guard.paths == []


@pytest.mark.parametrize("mode,exit_code", [("inspect", 0), ("valid", 0), ("invalid", 1), ("draft", 2)])
def test_cli_emits_parseable_separate_status_report(helper, bundle, capsys, mode, exit_code):
    if mode == "invalid":
        bundle.dataset["cases"][0]["gates"][0]["metric_id"] = "absent-metric"
    elif mode == "draft":
        bundle.manifest["main_workflow"]["confirmed"] = False
    args = ["--inspect"] if mode == "inspect" else [str(bundle.write())]
    assert helper.main(args) == exit_code
    report = json.loads(capsys.readouterr().out)
    if mode == "inspect":
        assert report["status"] == "valid"
        assert len(report["cases"]) == 32
    else:
        assert report["import_status"] == {"valid": "valid", "invalid": "invalid", "draft": "not_checked"}[mode]
        assert report["business_readiness"]["status"] != "ready"
        assert report["execution_performed"] is False
