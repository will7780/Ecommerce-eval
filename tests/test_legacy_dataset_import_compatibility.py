from __future__ import annotations

import json

from commerce_eval.contracts import EvalCaseV1
from commerce_eval.core import content_checksum
from commerce_eval.services.imports import ImportService
from commerce_eval.storage import Database, Repository
from commerce_eval.storage.models import DatasetVersionRow, EvalCaseRow


def test_raw_preupgrade_10_dataset_reimports_at_same_checksum(tmp_path):
    database = Database(tmp_path / "legacy-dataset.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("p", "Project")
    # Exact pre-upgrade shape, independent of the new model's default serializer.
    old_case = {
        "contract_version": "1.0", "case_id": "legacy", "version": "1", "name": "Legacy case",
        "input": {"message": "Inspect the catalog."}, "conversation": [], "expected_tools": [],
        "allowed_tools": [], "forbidden_tools": [], "required_sequence": [], "partial_order": [],
        "parameter_expectations": [], "outcome_assertions": {}, "fact_assertions": [], "intents": [],
        "reference_min_steps": None,
        "budgets": {"max_total_tokens": None, "max_agent_llm_calls": None,
                    "max_active_runtime_ms": None, "max_estimated_cost": None},
        "gates": [], "tags": [], "pack_id": "core",
    }
    old_case_checksum = content_checksum(old_case)
    manifest = {"project_id": "p", "dataset_id": "legacy", "version": "1", "name": "Legacy",
                "description": "Original dataset", "case_checksums": {"legacy": old_case_checksum}}
    old_checksum = content_checksum(manifest)
    with database.sessions.begin() as session:
        session.add(DatasetVersionRow(uid="p::legacy::1", project_id="p", dataset_id="legacy", version="1",
                                      name="Legacy", description="Original dataset", checksum=old_checksum))
        session.flush()
        session.add(EvalCaseRow(uid="p::legacy::1::legacy", dataset_uid="p::legacy::1", case_id="legacy",
                                name="Legacy case", payload_json=old_case, checksum=old_case_checksum))
    database.dispose()
    database = Database(database.path)
    database.initialize()
    repository = Repository(database)
    assert EvalCaseV1.model_validate(old_case).model_dump(mode="json") == old_case
    content = json.dumps({"dataset_id": "legacy", "version": "1", "name": "Legacy",
                          "description": "Original dataset", "cases": [old_case]})
    service = ImportService(repository)
    ready = service.preview("p", "dataset", [{"name": "legacy.json", "content": content}])
    assert ready["status"] == "ready", ready
    service.commit(ready["import_id"])
    with database.sessions() as session:
        assert session.get(DatasetVersionRow, "p::legacy::1").checksum == old_checksum
        assert session.get(EvalCaseRow, "p::legacy::1::legacy").payload_json == old_case
        assert session.get(EvalCaseRow, "p::legacy::1::legacy").checksum == old_case_checksum
    modern = EvalCaseV1.model_validate({**old_case, "contract_version": "1.1"}).model_dump(mode="json")
    assert {"scenario_id", "scenario_version", "scenario_data", "behavior_assertions"} <= modern.keys()
    database.dispose()
