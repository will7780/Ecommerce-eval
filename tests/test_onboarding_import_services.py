from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from commerce_eval.contracts import EvalCaseV1, TargetDefinitionV1, ToolContractV1, TraceEnvelopeV1
from commerce_eval.services.imports import ImportService, ImportValidationError, import_template
from commerce_eval.services.onboarding import OnboardingService, validate_http_definition
from commerce_eval.services.evaluations import EvaluationService
from commerce_eval.storage import Database, Repository
from commerce_eval.storage.models import ImportDraftRow, EvaluationRow, EvaluationMetricRow, EvaluationGateRow


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_API_ENV_FILE", str(tmp_path / "absent-fixture.env"))
    monkeypatch.delenv("COMMERCE_EVAL_API_TOKEN", raising=False)
    database = Database(tmp_path / "test.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("p", "Project")
    yield repository
    database.dispose()


def trace(trace_id="trace", **kwargs):
    return TraceEnvelopeV1(trace_id=trace_id, project_id="p", target_id="external", target_version="1",
                           started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), **kwargs).model_dump(mode="json")


def preview(repository, kind, payload, *, name="upload.json", options=None):
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return ImportService(repository).preview("p", kind, [{"name": name, "content": content}], options)


def test_preview_only_normalized_draft_then_import_is_unscored(repository):
    marker = "private-" + "fixture-value"
    result = preview(repository, "trace", trace(input={"token": marker, "hidden_reasoning": marker}))
    assert result["status"] == "ready", result
    assert not repository.list_traces()
    with repository.database.sessions() as session:
        draft = session.get(ImportDraftRow, result["import_id"])
        assert marker not in json.dumps(draft.payload_json)
    assert marker not in json.dumps(result)
    committed = ImportService(repository).commit(result["import_id"])
    assert ImportService(repository).commit(result["import_id"]) == committed
    detail = repository.get_trace("trace")
    assert detail["metrics"] == detail["gates"] == detail["evaluation_history"] == []
    assert detail["overall_pass"] is None
    assert marker not in json.dumps(detail)
    with repository.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationRow)) == 0


def test_validate_every_row_and_no_invalid_draft(repository):
    result = preview(repository, "trace", [trace(), {"trace_id": "invalid"}, {"bad": "row"}])
    assert result["status"] == "invalid"
    assert {row["line"] for row in result["errors"]} == {2, 3}
    assert not repository.list_traces()
    with repository.database.sessions() as session:
        assert session.get(ImportDraftRow, result["import_id"]) is None


def test_commit_race_conflict_rolls_back_earlier_rows(repository):
    service = ImportService(repository)
    ready = preview(repository, "trace", [trace("first"), trace("second")])
    assert ready["status"] == "ready", ready
    repository.save_trace(trace("second", output={"changed": True}))
    with pytest.raises(ImportValidationError) as error:
        service.commit(ready["import_id"])
    assert error.value.errors[0]["code"] == "version_immutable_conflict"
    assert [item["trace_id"] for item in repository.list_traces()] == ["second"]
    with repository.database.sessions() as session:
        assert session.get(ImportDraftRow, ready["import_id"]).result_json is None


def test_preview_detects_all_conflicts_and_idempotent_resource(repository):
    repository.save_trace(trace("one"))
    repository.save_trace(trace("two"))
    same = preview(repository, "trace", trace("one"))
    assert same["status"] == "ready", same
    ImportService(repository).commit(same["import_id"])
    bad = preview(repository, "trace", [trace("one", output={"x": 1}), trace("two", output={"x": 2})])
    assert bad["status"] == "invalid"
    assert len(bad["errors"]) == 2


@pytest.mark.parametrize("name", ["bundle.zip", "rows.xlsx", "code.py", "code.exe", "code.ps1", "data.tar.gz"])
def test_disallowed_upload_formats(repository, name):
    assert preview(repository, "trace", "{}", name=name)["errors"][0]["code"] == "file_type_not_allowed"


def test_limits_apply_before_parsing(repository, monkeypatch):
    monkeypatch.setattr("commerce_eval.services.imports.MAX_FILE_BYTES", 20)
    monkeypatch.setattr("commerce_eval.services.imports.MAX_IMPORT_BYTES", 30)
    assert preview(repository, "trace", "x" * 21)["errors"][0]["code"] == "file_size_limit"
    files = [{"name": "a.json", "content": "x" * 16}, {"name": "b.json", "content": "x" * 16}]
    assert ImportService(repository).preview("p", "trace", files)["errors"][0]["code"] == "import_size_limit"
    monkeypatch.setattr("commerce_eval.services.imports.MAX_FILE_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr("commerce_eval.services.imports.MAX_IMPORT_BYTES", 50 * 1024 * 1024)
    many = [trace(str(i)) for i in range(1001)]
    assert preview(repository, "trace", many)["errors"][0]["code"] == "trace_count_limit"


def test_jsonl_validates_late_rows_without_partial_import(repository):
    lines = [json.dumps(trace(str(i))) for i in range(300)] + ["not-json"]
    result = preview(repository, "trace", "\n".join(lines), name="rows.jsonl")
    assert result["status"] == "invalid"
    assert any(error["line"] == 301 for error in result["errors"])
    assert not repository.list_traces()


def test_duplicate_keys_and_identifiers_rejected(repository):
    assert preview(repository, "trace", '{"trace_id":"a","trace_id":"b"}')["status"] == "invalid"
    assert preview(repository, "trace", [trace(), trace()])["errors"][0]["code"] == "duplicate_identifier"


def test_expired_draft_cannot_commit(repository):
    result = preview(repository, "trace", trace())
    with repository.database.sessions.begin() as session:
        session.get(ImportDraftRow, result["import_id"]).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(ValueError, match="import_expired"):
        ImportService(repository).commit(result["import_id"])
    assert not repository.list_traces()


def test_pinned_contract_redaction_and_missing_ref(repository):
    value = trace(tool_contract_set_id="tools", tool_contract_version="1", input={"merchant_id": "private-fixture"})
    assert preview(repository, "trace", value)["status"] == "invalid"
    repository.save_tool_contract_set("p", "tools", "1", [ToolContractV1(
        tool_id="catalog.inspect", version="1", title="Inspect", sensitive_fields=["merchant_id"]
    )])
    ready = preview(repository, "trace", value)
    assert ready["status"] == "ready", ready
    assert "private-fixture" not in json.dumps(ready)


def test_products_mapping_and_versioned_rules(repository):
    options = {"id": "catalog", "version": "1", "column_mapping": {"sku": "SKU", "price": "Cost", "currency": "Unit"}}
    ready = preview(repository, "products", "SKU,Cost,Unit\nITEM-1,9.5,USD\n", name="products.csv", options=options)
    assert ready["status"] == "ready", ready
    ref = ImportService(repository).commit(ready["import_id"])["resources"][0]
    assert ref["kind"] == "products" and ref["version"] == "1"
    assert repository.get_asset("p", "products", "catalog", "1")["rows"][0]["sku"] == "ITEM-1"
    conflict = preview(repository, "products", "SKU,Cost,Unit\nITEM-1,10,USD\n", name="products.csv", options=options)
    assert conflict["status"] == "invalid"
    for version in ("1", "2"):
        rules = preview(repository, "rules", "# Policy\nValidate everything.\n" + version,
                        name="policy.md", options={"id": "policy", "version": version})
        assert rules["status"] == "ready", rules
        ImportService(repository).commit(rules["import_id"])
    assert repository.get_asset("p", "rules", "policy", "1") != repository.get_asset("p", "rules", "policy", "2")


def http_target(base_url="http://127.0.0.1:9000", **config):
    return TargetDefinitionV1(target_id="http", version="1", name="HTTP", adapter_type="http",
                              safe_for_eval=True, config={"base_url": base_url, **config})


@pytest.mark.parametrize("url", ["http://user:pass@example.com", "http://169.254.169.254", "http://metadata.google.internal",
                                  "http://0.0.0.0", "http://[::]", "file:///tmp/file", "http://example.com?token=x",
                                  "http://[::ffff:169.254.169.254]"])
def test_unsafe_remote_target_urls_refused(url):
    with pytest.raises(ValueError):
        validate_http_definition(http_target(url))


def test_public_target_disallows_code_headers_and_local_registration(repository):
    definition = TargetDefinitionV1(target_id="local", version="1", name="Local", adapter_type="python",
                                    config={"command": ["$PYTHON", "-m", "commerce_eval.demo_runtime"]})
    assert preview(repository, "target", definition.model_dump(mode="json"))["status"] == "invalid"
    assert preview(repository, "target", http_target(command=["run"]).model_dump(mode="json"))["status"] == "invalid"
    assert preview(repository, "target", http_target(headers={"Authorization": "fixture"}).model_dump(mode="json"))["status"] == "invalid"
    local = ImportService(repository, allow_local_registration=True)
    ready = local.preview("p", "target", [{"name": "target.json", "content": definition.model_dump_json()}])
    assert ready["status"] == "ready", ready
    with pytest.raises(ValueError):
        ImportService(repository).commit(ready["import_id"])
    local.commit(ready["import_id"])
    result = asyncio.run(OnboardingService(repository).check("p", "local", "1"))
    assert result["executed"] is False and result["connection"] == "not_executed"


def test_http_check_is_explicit_bounded_and_credential_ref_only(repository, monkeypatch):
    service = OnboardingService(repository, timeout=0.01)
    called = []

    async def probe(definition):
        called.append(definition.target_id)
        await asyncio.sleep(1)

    monkeypatch.setattr(service, "_probe", probe)
    monkeypatch.delenv("TEST_ONBOARDING_CREDENTIAL", raising=False)
    result = asyncio.run(service.check("p", definition=http_target(token_env="TEST_ONBOARDING_CREDENTIAL").model_dump()))
    assert result["checks"][0]["code"] == "credential_reference_unavailable"
    assert not called
    result = asyncio.run(service.check("p", definition=http_target().model_dump()))
    assert result["checks"][0]["code"] == "target_connection_timeout"
    assert result["executed"] is False


def test_offline_evaluation_history_preserves_old_gates(repository):
    repository.save_trace(trace(output={"success": True}))
    repository.save_tool_contract_set("p", "tools", "1", [])
    repository.save_evaluator_set("p", "evaluators", "1", ["task_completion"])
    for version, expected in (("1", True), ("2", False)):
        repository.save_dataset("p", "dataset", version, "Dataset", [EvalCaseV1(
            case_id="case", name="Case", gates=[{"metric_id": "task_completion", "operator": "equals", "expected": expected}]
        )])
    service = EvaluationService(repository)
    binding = dict(dataset_id="dataset", dataset_version="1", case_id="case", tool_contract_set_id="tools",
                   tool_contract_version="1", evaluator_set_id="evaluators", evaluator_set_version="1")
    first = service.evaluate("trace", **binding)
    second = service.evaluate("trace", **{**binding, "dataset_version": "2"})
    assert first["evaluation_id"] != second["evaluation_id"]
    assert repository.get_evaluation(first["evaluation_id"]) == first
    detail = repository.get_trace("trace")
    assert len(detail["evaluation_history"]) == 2
    assert detail["evaluation_id"] == second["evaluation_id"]
    assert detail["gates"] == second["gate_results"]
    assert first["gate_results"][0]["passed"] != second["gate_results"][0]["passed"]
    with repository.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EvaluationMetricRow)) == 2
        assert session.scalar(select(func.count()).select_from(EvaluationGateRow)) == 2


@pytest.mark.parametrize("kind", ["trace", "dataset", "tool-contracts", "products", "rules", "target", "evaluator-set"])
def test_templates_can_preview_and_commit(repository, kind):
    name, content = import_template(kind)
    ready = preview(repository, kind, content, name=name, options={"id": "example", "version": "1"})
    assert ready["status"] == "ready", ready
    assert ImportService(repository).commit(ready["import_id"])["resources"]
