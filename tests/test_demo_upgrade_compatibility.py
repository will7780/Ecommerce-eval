"""The shipped 1.0 demo set must remain unchanged when 0.2 is seeded."""

from commerce_eval.demo import seed_demo
from commerce_eval.packs import all_evaluators
from commerce_eval.storage import Database, Repository


def test_seed_upgrade_keeps_original_evaluator_membership(tmp_path):
    database = Database(tmp_path / "legacy.db")
    database.initialize()
    repository = Repository(database)
    repository.create_project("commerce-demo", "Commerce Operations Demo", "Offline, anonymized evaluation data")
    additions = {
        "business_acceptance_pass",
        "artifact_preflight_compliance", "artifact_defect_detection_recall",
        "artifact_sampling_compliance", "artifact_review_compliance",
        "artifact_execution_binding_pass", "scenario_behavior_compliance",
        "business_tool_blocked_count", "business_tool_execution_count",
        "business_tool_success_count",
    }
    original = repository.save_evaluator_set(
        "commerce-demo", "default", "1.0.0",
        [item.metric_id for item in all_evaluators() if item.metric_id not in additions],
    )
    try:
        seed_demo(repository)
        seed_demo(repository)
        assert repository.get_evaluator_set("commerce-demo", "default", "1.0.0") == original
        upgraded = repository.get_evaluator_set("commerce-demo", "commerce-standard", "0.2.0")
        assert additions - {"business_acceptance_pass"} <= set(upgraded["metric_ids"])
        assert "business_acceptance_pass" not in upgraded["metric_ids"]
        assert repository.get_dataset("commerce-demo", "commerce-standard-bank", "0.2.0")["case_count"] == 32
    finally:
        database.dispose()
def test_reseeding_preserves_historical_experiment_end_times(tmp_path):
    from commerce_eval.demo import seed_demo
    from commerce_eval.storage import Database, Repository

    database = Database(tmp_path / "immutable-demo.db")
    database.initialize()
    repository = Repository(database)
    seeded = seed_demo(repository)
    before = {identifier: repository.get_experiment(identifier) for identifier in seeded["experiments"]}
    seed_demo(repository)
    after = {identifier: repository.get_experiment(identifier) for identifier in seeded["experiments"]}
    assert before == after
    database.dispose()
