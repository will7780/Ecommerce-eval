"""Prepare isolated, synthetic README evidence using the existing grader.

No model/Target is executed. The fixtures test grading behavior; they do not
authenticate any external agent, collector or production outcome.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
from pathlib import Path


def build_media(destination: Path) -> dict:
    destination = destination.expanduser().resolve()
    # mkdir without exist_ok also rejects an existing directory or symlink.
    destination.mkdir(parents=True, exist_ok=False)
    os.environ["COMMERCE_EVAL_DISABLE_CENTRAL_ENV"] = "1"
    from commerce_eval.business.bank import VERSION, load_business_cases
    from commerce_eval.business.fixtures import negative_business_variants, positive_business_evidence
    from commerce_eval.contracts import ExperimentSpecV1, TargetDefinitionV1, TraceEnvelopeV1, TraceEventV1
    from commerce_eval.core import EvaluationEngine
    from commerce_eval.storage import Database, Repository
    from commerce_eval.storage.business_evidence import save_collected_business_evidence

    project = "readme-synthetic"
    cases = load_business_cases()
    case = next(item for item in cases if item.scenario_id == "A04")
    positive = positive_business_evidence(case)
    negative = next(item["evidence"] for item in negative_business_variants(case)
                    if item["name"] == "tampered_content_executed")
    missing = positive.model_copy(deep=True)
    missing.complete = False
    missing.effects = []
    missing.final_state.pop("journal", None)
    missing.omission_reasons = ["effect_journal_not_collected"]
    versions = [("blocked", positive, "pass"), ("violation", negative, "fail"),
                ("missing-evidence", missing, "error")]
    database = Database(destination / "media.db")
    try:
        database.initialize()
        repo = Repository(database)
        repo.create_project(project, "README / Synthetic grader fixtures",
                            "Offline conformance examples. No Agent or model was executed.")
        repo.save_dataset(project, "commerce-standard-bank", VERSION,
                          "Commerce Business Acceptance", cases,
                          "32 synthetic starter cases; README results are grader fixtures only.")
        repo.save_tool_contract_set(project, "none", VERSION, [])
        repo.save_evaluator_set(project, "business", VERSION, ["business_acceptance_pass"])
        repo.save_target(project, TargetDefinitionV1(
            contract_version="1.2", target_id="grader-fixture", version="1",
            name="Grader fixture / no Agent", adapter_type="reference_fixture",
            safe_for_eval=False, config={},
            tags={"actor": "reference_fixture", "candidate_evaluation": "false"}))
        links = {}
        verdicts = {}
        for label, evidence, expected in versions:
            trace_id = "readme-a04-" + label
            evidence = evidence.model_copy(update={
                "project_id": project, "run_id": trace_id,
                "collector_id": "offline-fixture-not-live"})
            spec = ExperimentSpecV1(
                contract_version="1.2", experiment_id=trace_id, project_id=project,
                name="Synthetic grader check / " + label, dataset_id="commerce-standard-bank",
                dataset_version=VERSION, target_id="grader-fixture", target_version="1",
                tool_contract_set_id="none", tool_contract_version=VERSION,
                evaluator_set_id="business", evaluator_set_version=VERSION,
                tags={"actor": "reference_fixture", "candidate_evaluation": "false"})
            repo.create_experiment(spec)
            rows = []
            kinds = {"artifacts": "artifact.snapshot", "checks": "artifact.check",
                     "reviews": "artifact.review", "interactions": "interaction",
                     "effects": "side_effect.receipt", "observations": "observation"}
            for collection, kind in kinds.items():
                for row in getattr(evidence, collection):
                    if row.get("kind") == "diagnostic":
                        continue
                    name = kind + (" / v" + str(row["version"]) if row.get("version") else "")
                    rows.append(TraceEventV1(
                        contract_version="1.2", event_id=row["evidence_id"],
                        sequence=row["sequence"], kind=kind, name=name,
                        started_at=row.get("at"), attributes=row,
                        evidence_refs=[row["evidence_id"]]))
            trace = TraceEnvelopeV1(
                contract_version="1.2", trace_id=trace_id, project_id=project,
                target_id="grader-fixture", target_version="1",
                experiment_id=spec.experiment_id, case_id=case.case_id,
                dataset_version=VERSION, evaluator_set_version=VERSION,
                tool_contract_set_id="none", tool_contract_version=VERSION,
                started_at=evidence.started_at, ended_at=evidence.ended_at,
                input={"message": case.input.get("message", ""),
                       "source": "Synthetic grader fixture; no model input was captured."},
                output={"source": "Fixture report, not an Agent answer",
                        "report": json.loads(evidence.report["content"])},
                tags={"actor": "reference_fixture", "execution": "simulated",
                      "candidate_evaluation": "false", "live_side_effect": "false"},
                metadata={"purpose": "README grader demonstration", "model_executed": False,
                          "reference_fixture": True},
                events=sorted(rows, key=lambda item: item.sequence))
            repo.save_trace(trace)
            safe = save_collected_business_evidence(
                repo, trace_id, evidence.model_dump(mode="json"), session_id=trace_id,
                project_id=project, collector_id=evidence.collector_id)
            result = EvaluationEngine([]).evaluate(case, trace, business_evidence=safe)
            metric = next(item for item in result.metric_results
                          if item.metric_id == "business_acceptance_pass")
            if metric.status.value != expected:
                raise AssertionError(f"unexpected_fixture_verdict:{label}:{metric.status.value}")
            repo.save_evaluation(result, binding={"source": "offline_grader_conformance"})
            repo.update_experiment(spec.experiment_id, status="completed", completed_runs=1)
            artifact_dir = destination / trace_id
            artifact_dir.mkdir()
            for artifact in safe.artifacts:
                (artifact_dir / ("catalog-v" + artifact["version"] + ".json")).write_text(
                    json.dumps(artifact["rows"], indent=2, ensure_ascii=False), encoding="utf-8")
            (artifact_dir / "evidence.json").write_text(
                safe.model_dump_json(indent=2), encoding="utf-8")
            (artifact_dir / "evaluation.json").write_text(
                result.model_dump_json(indent=2), encoding="utf-8")
            links[label] = "/traces/" + trace_id
            verdicts[label] = metric.status.value
        manifest = {"source": "offline_grader_conformance", "model_executed": False,
                    "project_id": project, "bank_version": VERSION,
                    "database": "media.db", "routes": links, "verdicts": verdicts}
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
    finally:
        database.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="A NEW directory; existing paths are rejected")
    args = parser.parse_args()

    def no_network(*args, **kwargs):
        raise RuntimeError("README media preparation is offline")

    socket.create_connection = no_network
    socket.socket.connect = no_network
    print(json.dumps(build_media(args.destination), indent=2))


if __name__ == "__main__":
    main()
