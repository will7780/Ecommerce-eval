"""Offline actual-byte/effect tests for the two candidate tool surfaces."""

from copy import deepcopy
from decimal import Decimal, ROUND_CEILING
import json
import os

import pytest

from commerce_eval.business.bank import load_business_cases
from commerce_eval.business.candidates import BusinessCandidateSurface, build_tool_contracts, _BACKEND, _BUSINESS
from commerce_eval.business.environment import BusinessScenarioEnvironment
from commerce_eval.business.verifiers import evaluate_business_requirements
from commerce_eval.business.workspace import BusinessWorkspace
from commerce_eval.scenarios.artifacts import read_artifact_evidence


def bank_case(code):
    return next(case for case in load_business_cases() if case.scenario_id == code)


def command(env, action, **args):
    env.record_decision("s", action=action)
    surface = getattr(env, "_test_surface", None)
    if surface:
        interface = BusinessCandidateSurface(surface)
        if action in {"ask", "confirm"}:
            name = {"ask": "ask_user", "confirm": "confirm_publication"}[action]
        elif surface == "business_interface":
            name = next(name for name, entry in _BUSINESS.items() if entry[0] == action)
        elif action == "read_source":
            name, args = "read_file", {"path": "inputs/products.json"}
        else:
            method, path = next(route for route, target in _BACKEND.items() if target == action)
            name, args = "backend_request", {"method": method, "path": path, "body": args}
        return interface.execute(env, "s", {"id": "surface-" + os.urandom(6).hex(), "name": name, "arguments": args})
    return env.execute("s", {"action": action, "arguments": args})


def approve(env, action="review", decision="approved"):
    receipt = command(env, action)
    assert receipt["status"] == "pending", receipt
    return env.respond("s", receipt["pending_interaction"]["interaction_id"], {"decision": decision})


def full_check(env):
    assert command(env, "check")["status"] == "ok"
    assert command(env, "sample")["status"] == "ok"


def finish(env, outcome="completed"):
    observed = env.collect_business_evidence("s")
    published = {rid for effect in observed.effects if effect["action"] == "publish" and effect["status"] == "executed" for rid in effect["row_ids"]}
    failures = [row for row in observed.observations if row["kind"] == "failure"]
    remaining = set()
    for failure in failures:
        ids = set(failure.get("failed_row_ids", []))
        for row in observed.observations:
            if row.get("failure_id") == failure["evidence_id"] and row.get("status") == "success":
                ids -= set(row.get("row_ids", []))
        remaining |= ids
    env.finish("s", json.dumps({"outcome": outcome, "simulated": True, "published_row_ids": sorted(published),
               "failed_row_ids": sorted(remaining), "failures": [row["evidence_id"] for row in failures],
               "next_actions": ["Resolve the observed block before proceeding."] if outcome == "blocked" else []}))
    return env.collect_business_evidence("s")


def prepare(env, surface, **options):
    interface = BusinessCandidateSurface(surface)
    if surface == "business_interface":
        return interface.execute(env, "s", {"id": "generate-" + str(len(env.sessions.get("s").artifacts) if "s" in env.sessions else 0),
                                            "name": "business_generate_catalog", "arguments": options})
    source = interface.execute(env, "s", {"id": "read-" + os.urandom(4).hex(), "name": "read_file", "arguments": {"path": "inputs/products.json"}})
    if source["status"] != "ok":
        return source
    rows = json.loads(source["content"])
    if options.get("category"):
        rows = [row for row in rows if row["category"] == options["category"]]
    rows = rows[:options.get("limit", len(rows))]
    for row in rows:
        if "margin_percent" in options:
            row["price"] = float((Decimal(str(row["cost"])) / (1-Decimal(str(options["margin_percent"]))/100)).quantize(Decimal(".01"), rounding=ROUND_CEILING))
        if "site" in options:
            row["site"] = options["site"]
    return interface.execute(env, "s", {"id": "write-" + os.urandom(4).hex(), "name": "write_file",
                                        "arguments": {"path": "artifacts/catalog.json", "content": json.dumps(rows)}})


@pytest.mark.parametrize("surface", ["business_interface", "file_editor"])
@pytest.mark.parametrize("code", ["I01", "I03", "C01", "C03", "C04", "T01", "T02", "T04", "P01", "A01", "A02", "A03", "A04", "M01", "M02", "M04", "S01", "S02", "S03"])
def test_same_business_conditions_on_two_actual_surfaces(tmp_path, surface, code):
    case = bank_case(code)
    env = BusinessScenarioEnvironment(case, tmp_path)
    env._test_surface = surface
    env.open_session("s")
    options, outcome = {}, "completed"
    try:
        if code in {"C01", "C03", "C04", "M04", "T02"}:
            assert command(env, "read_rules")["status"] == "ok"
        if code == "T02":
            assert command(env, "source_check")["valid"]
        if code == "I03":
            options = {"category": "stationery", "limit": 4}
        if code in {"P01", "C04"}:
            options["margin_percent"] = 18
        if code in {"C03", "M01", "M02"}:
            field, value = ("margin_percent", 15) if code == "C03" else ("site", "NL" if code == "M02" else "DE")
            ask = command(env, "ask", fields=[field], prompt="Supply current value")
            env.respond("s", ask["pending_interaction"]["interaction_id"], {field: value})
            options[field] = value
        assert prepare(env, surface, **options)["status"] == "ok"
        if code in {"T01", "A01", "A02", "A03", "A04", "S01", "S03"}:
            full_check(env)
            if code == "A02":
                outcome = "blocked"
            else:
                if code == "A03":
                    approve(env, decision="revise")
                    assert prepare(env, surface)["status"] == "ok"
                    full_check(env)
                approve(env)
                if code in {"S01", "T01"}:
                    approve(env, "confirm")
                result = command(env, "publish")
                if code == "A04":
                    assert result["status"] == "blocked"
                    outcome = "blocked"
                else:
                    assert result["status"] == "ok", result
                    if code == "T01":
                        assert command(env, "audit", threshold_percent=-10)["status"] == "ok"
        if code == "S02":
            approve(env, "confirm", "rejected")
            outcome = "blocked"
        bundle = finish(env, outcome)
        result = evaluate_business_requirements(case, bundle)
        assert result.status.value == "pass", [(item["status"], item.get("reason_code")) for item in result.details["requirement_results"]]
        for artifact in bundle.artifacts:
            read_artifact_evidence(artifact)
    finally:
        env.close()


def test_file_surface_never_calls_hidden_generator(tmp_path, monkeypatch):
    env = BusinessScenarioEnvironment(bank_case("I01"), tmp_path)
    env.open_session("s")
    dispatched = []
    original = env._dispatch
    def spy(state, action, args, call_id):
        dispatched.append(action)
        assert action != "generate"
        return original(state, action, args, call_id)
    monkeypatch.setattr(env, "_dispatch", spy)
    try:
        assert prepare(env, "file_editor")["status"] == "ok"
        assert dispatched == ["read_file", "write_file"]
        result = BusinessCandidateSurface("file_editor").execute(env, "s", {"name": "backend_request",
                    "arguments": {"method": "POST", "path": "/generate"}})
        assert result["error_type"] == "backend_route_denied"
    finally:
        env.close()


def test_publishing_then_retracting_preserves_complete_effect_journal(tmp_path):
    env = BusinessScenarioEnvironment(bank_case("I01"), tmp_path)
    try:
        command(env, "generate")
        assert command(env, "publish")["status"] == "ok"
        assert command(env, "retract")["status"] == "ok"
        bundle = finish(env)
        assert bundle.final_state["published_row_ids"] == []
        assert [row["action"] for row in bundle.effects if row["status"] == "executed"] == ["publish", "retract"]
        assert evaluate_business_requirements(env.case, bundle).status.value == "fail"
    finally:
        env.close()


def test_export_does_not_manufacture_candidate_checks_or_artifact_versions(tmp_path):
    env = BusinessScenarioEnvironment(bank_case("A01"), tmp_path)
    try:
        command(env, "generate")
        first, second = env.collect_business_evidence("s"), env.collect_business_evidence("s")
        assert len(first.artifacts) == len(second.artifacts) == 1
        assert all(check["source"] == "evaluator" for check in second.checks)
        assert command(env, "publish")["status"] == "blocked"
    finally:
        env.close()


@pytest.mark.parametrize("path", ["../outside.json", "artifacts/../inputs/products.json", "/absolute.json", "inputs/products.json", "artifacts/a:stream.json", "artifacts/.env", "artifacts/script.py", "frozen/catalog.json"])
def test_file_writes_cannot_escape_or_access_private_material(tmp_path, path):
    workspace = BusinessWorkspace(tmp_path)
    try:
        with pytest.raises(ValueError):
            workspace.write(path, "[]")
    finally:
        workspace.close()


def test_links_rejected_even_when_their_target_is_inside_workspace(tmp_path):
    workspace = BusinessWorkspace(tmp_path)
    try:
        workspace.write("artifacts/original.json", "[]")
        source = workspace.resolve("artifacts/original.json")
        link = workspace.root / "artifacts" / "alias.json"
        try:
            os.link(source, link)
        except OSError:
            pytest.skip("host does not allow test hardlink")
        with pytest.raises(ValueError, match="workspace_link_denied"):
            workspace.read("artifacts/alias.json")
    finally:
        workspace.close()


def test_resume_cannot_replace_parameters_and_approval_executes_once(tmp_path):
    env = BusinessScenarioEnvironment(bank_case("S01"), tmp_path)
    try:
        command(env, "generate")
        full_check(env)
        approve(env)
        pending = command(env, "confirm")["pending_interaction"]
        with pytest.raises(ValueError, match="tampered"):
            env.respond("s", pending["interaction_id"], {"decision": "approved", "arguments": {"row_ids": []}})
        env.respond("s", pending["interaction_id"], {"decision": "approved"})
        first = env.execute("s", {"action": "publish", "tool_call_id": "one"})
        assert first["status"] == "ok"
        assert env.execute("s", {"action": "publish", "tool_call_id": "one"}) == first
        assert env.execute("s", {"action": "publish", "tool_call_id": "two"})["status"] == "blocked"
        assert len([row for row in finish(env).effects if row["status"] == "executed"]) == 1
    finally:
        env.close()


def test_directory_membership_change_invalidates_review(tmp_path):
    env = BusinessScenarioEnvironment(bank_case("A01"), tmp_path)
    try:
        command(env, "generate")
        full_check(env)
        approve(env)
        original = env.collect_business_evidence("s").artifacts[-1]
        env.sessions["s"].workspace.write("artifacts/extra.json", "[]")
        assert command(env, "publish")["status"] == "blocked"
        revised = env.collect_business_evidence("s").artifacts[-1]
        assert revised["manifest_hash"] != original["manifest_hash"]
        assert revised["format"] == "directory"
    finally:
        env.close()


def test_tool_contracts_preserve_actual_names_and_distinct_surfaces():
    first = {row.tool_id for row in build_tool_contracts("business_interface")}
    second = {row.tool_id for row in build_tool_contracts("file_editor")}
    assert "business_generate_catalog" in first and "write_file" in second
    assert "business_generate_catalog" not in second


@pytest.mark.parametrize("surface", ["business_interface", "file_editor"])
@pytest.mark.parametrize("code", ["I02", "I04", "C02", "T03", "P02", "P03", "P04", "M03", "R01", "R02", "R03", "R04"])
def test_missing_inputs_queries_and_recovery_share_independent_truth(tmp_path, surface, code):
    selected = bank_case(code)
    env = BusinessScenarioEnvironment(selected, tmp_path)
    env._test_surface = surface
    env.open_session("s")
    outcome = "completed"
    try:
        if code == "I02":
            pending = command(env, "ask", fields=["category", "limit"], prompt="Choose product scope")["pending_interaction"]
            env.respond("s", pending["interaction_id"], {"category": "stationery", "limit": 4})
            assert prepare(env, surface, category="stationery", limit=4)["status"] == "ok"
        elif code == "I04":
            assert command(env, "query", row_ids=["row01", "row20"])["status"] == "ok"
        elif code == "C02":
            assert command(env, "read_rules")["status"] == "blocked"
            pending = command(env, "ask", fields=["policy"], prompt="Provide applicable policy")["pending_interaction"]
            env.respond("s", pending["interaction_id"], {"policy": None})
            outcome = "blocked"
        elif code in {"T03", "R04"}:
            receipt = prepare(env, surface)
            assert receipt["status"] == "blocked" if code == "T03" else receipt.get("artifact_count") == 0
            outcome = "blocked"
        elif code == "P02":
            assert command(env, "read_source")["status"] == "blocked"
            pending = command(env, "ask", fields=["input_file"], prompt="Provide input file")["pending_interaction"]
            env.respond("s", pending["interaction_id"], {"input_file": "products.json"})
            assert command(env, "source_check")["valid"]
            assert prepare(env, surface)["status"] == "ok"
        elif code == "P03":
            receipt = command(env, "validate_parameters", request={"site": "XX", "margin_percent": "eighteen", "unexpected": True})
            assert not receipt["valid"]
            outcome = "blocked"
        elif code == "P04":
            assert not command(env, "source_check")["valid"]
            outcome = "blocked"
        elif code == "M03":
            prepare(env, surface)
            finish(env)
            env.record_user_message("s", "Now only query prices for row01 and row20", facts={"task": "prices"})
            command(env, "query", row_ids=["row01", "row20"])
        elif code == "R01":
            assert command(env, "inventory_query", source="primary")["status"] == "failed"
            assert command(env, "inventory_query", source="alternate")["status"] == "ok"
        elif code == "R02":
            failed = command(env, "inventory_query", row_ids=["row01", "row20"])
            assert failed["status"] == "partial"
            assert command(env, "inventory_query", row_ids=failed["failed_row_ids"])["status"] == "ok"
        elif code == "R03":
            unknown = command(env, "export")
            assert unknown["status"] == "unknown"
            assert command(env, "status", operation_id=unknown["operation_id"])["state"] == "completed"
        result = evaluate_business_requirements(selected, finish(env, outcome))
        assert result.status.value == "pass", [(item["status"], item.get("reason_code")) for item in result.details["requirement_results"]]
    finally:
        env.close()


def test_json_secret_fields_are_rejected_before_file_write(tmp_path):
    env = BusinessScenarioEnvironment(bank_case("I01"), tmp_path)
    try:
        content = json.dumps([{"row_id": "row01", "api_key": "DO_NOT_PERSIST_THIS_VALUE"}])
        result = command(env, "write_file", path="artifacts/catalog.json", content=content)
        assert result["status"] == "blocked"
        assert not env.materialized_files("s")
        assert "DO_NOT_PERSIST_THIS_VALUE" not in env.collect_business_evidence("s").model_dump_json()
    finally:
        env.close()


def test_risk_confirmation_rejects_revision_and_artifact_feedback_is_returned(tmp_path):
    env = BusinessScenarioEnvironment(bank_case("S01"), tmp_path)
    try:
        command(env, "generate")
        full_check(env)
        pending = command(env, "review")["pending_interaction"]
        receipt = env.respond("s", pending["interaction_id"], {"decision": "revise", "message": "Correct the selected currency."})
        assert receipt["feedback"] == "Correct the selected currency."
        risk = command(env, "confirm")["pending_interaction"]
        with pytest.raises(ValueError, match="interaction_decision_invalid"):
            env.respond("s", risk["interaction_id"], {"decision": "revise"})
        assert env.sessions["s"].pending["interaction_id"] == risk["interaction_id"]
        assert not env.sessions["s"].effects
    finally:
        env.close()
