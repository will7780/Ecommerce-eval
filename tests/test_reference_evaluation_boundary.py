import pytest

from commerce_eval.contracts import TraceEnvelopeV1
from commerce_eval.services.evaluations import EvaluationService
from commerce_eval.storage import Database, Repository


@pytest.mark.parametrize("tags,metadata", [
    ({"actor": "reference_fixture"}, {"actor": "candidate", "candidate_evaluation": True}),
    ({"candidate_evaluation": "false"}, {"candidate_evaluation": True}),
    ({}, {"reference_fixture": True}),
])
def test_reference_provenance_cannot_be_overridden_for_scoring(tmp_path, tags, metadata):
    database = Database(tmp_path / "reference.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("p", "Project")
    repository.save_trace(TraceEnvelopeV1(trace_id="trace", project_id="p", target_id="external",
                                           target_version="1", tags=tags, metadata=metadata))
    with pytest.raises(ValueError, match="reference_fixture_not_candidate"):
        EvaluationService(repository).evaluate("trace", dataset_id="missing", dataset_version="1",
             case_id="case", tool_contract_set_id="tools", tool_contract_version="1",
             evaluator_set_id="set", evaluator_set_version="1")
    assert repository.evaluation_history("trace") == []
    database.dispose()
