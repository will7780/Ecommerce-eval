"""Single persistence boundary for normalized, redacted platform data."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional
from uuid import uuid4

from sqlalchemy import delete, func, select, text

from commerce_eval.contracts import (
    EvalCaseV1,
    EvaluationResultV1,
    ExperimentSpecV1,
    TargetDefinitionV1,
    ToolContractV1,
    TraceEnvelopeV1,
)
from commerce_eval.core import ContractNormalizer, TraceNormalizer, content_checksum, redact_recursive

from .database import Database
from .models import (
    AssetVersionRow,
    EvaluationRow,
    EvaluationMetricRow,
    EvaluationGateRow,
    AnnotationRow,
    DatasetVersionRow,
    EvalCaseRow,
    EvaluatorSetVersionRow,
    ExperimentRow,
    GateResultRow,
    MetricResultRow,
    ProjectRow,
    RunRow,
    TargetVersionRow,
    ToolContractVersionRow,
    TraceEventRow,
)


class VersionConflictError(ValueError):
    pass


def _uid(*parts: str) -> str:
    return "::".join(str(part) for part in parts)


def _numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def transaction(self, *, dry_run: bool = False):
        from .transactions import BoundDatabase

        with self.database.sessions() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                yield Repository(BoundDatabase(self.database, session))
                session.flush()
                if dry_run:
                    session.rollback()
                else:
                    session.commit()
            except BaseException:
                session.rollback()
                raise

    def create_project(self, project_id: str, name: str, description: str = "") -> dict[str, Any]:
        project_id = str(project_id)[:120]
        safe = redact_recursive({"name": name, "description": description})
        with self.database.sessions.begin() as session:
            row = session.get(ProjectRow, project_id)
            if row is None:
                row = ProjectRow(project_id=project_id, name=safe["name"], description=safe["description"])
                session.add(row)
            elif row.name != safe["name"] or row.description != safe["description"]:
                raise VersionConflictError("project_immutable_conflict")
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.database.sessions() as session:
            row = session.get(ProjectRow, project_id)
            if row is None:
                raise KeyError("project_not_found")
            return {
                "project_id": row.project_id,
                "name": row.name,
                "description": row.description,
                "created_at": row.created_at.isoformat(),
            }

    def list_projects(self) -> list[dict[str, Any]]:
        with self.database.sessions() as session:
            rows = session.scalars(select(ProjectRow).order_by(ProjectRow.created_at)).all()
            return [
                {
                    "project_id": row.project_id,
                    "name": row.name,
                    "description": row.description,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    def save_target(self, project_id: str, definition: TargetDefinitionV1) -> dict[str, Any]:
        payload = redact_recursive(definition.model_dump(mode="json"))
        checksum = content_checksum(payload)
        uid = _uid(project_id, definition.target_id, definition.version)
        with self.database.sessions.begin() as session:
            existing = session.get(TargetVersionRow, uid)
            if existing and existing.checksum != checksum:
                raise VersionConflictError("target_version_immutable_conflict")
            if not existing:
                session.add(
                    TargetVersionRow(
                        uid=uid,
                        project_id=project_id,
                        target_id=definition.target_id,
                        version=definition.version,
                        name=definition.name,
                        adapter_type=definition.adapter_type,
                        safe_for_eval=definition.safe_for_eval,
                        payload_json=payload,
                        checksum=checksum,
                    )
                )
        return payload

    def get_target(self, project_id: str, target_id: str, version: str) -> TargetDefinitionV1:
        with self.database.sessions() as session:
            row = session.get(TargetVersionRow, _uid(project_id, target_id, version))
            if row is None:
                raise KeyError("target_version_not_found")
            return TargetDefinitionV1.model_validate(row.payload_json)

    def list_targets(self, project_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self.database.sessions() as session:
            query = select(TargetVersionRow).order_by(TargetVersionRow.created_at.desc())
            if project_id:
                query = query.where(TargetVersionRow.project_id == project_id)
            return [
                {
                    **dict(row.payload_json),
                    "project_id": row.project_id,
                    "created_at": row.created_at.isoformat(),
                }
                for row in session.scalars(query).all()
            ]

    def save_tool_contract_set(
        self,
        project_id: str,
        set_id: str,
        version: str,
        tools: Iterable[ToolContractV1 | Mapping[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "contract_version": "1.0",
            "set_id": set_id,
            "version": version,
            "tools": [ContractNormalizer.tool(tool).model_dump(mode="json") for tool in tools],
        }
        checksum = content_checksum(payload)
        uid = _uid(project_id, set_id, version)
        with self.database.sessions.begin() as session:
            existing = session.get(ToolContractVersionRow, uid)
            if existing and existing.checksum != checksum:
                raise VersionConflictError("tool_contract_version_immutable_conflict")
            if not existing:
                session.add(
                    ToolContractVersionRow(
                        uid=uid,
                        project_id=project_id,
                        set_id=set_id,
                        version=version,
                        payload_json=payload,
                        checksum=checksum,
                    )
                )
        return payload

    def get_tool_contracts(self, project_id: str, set_id: str, version: str) -> dict[str, ToolContractV1]:
        with self.database.sessions() as session:
            row = session.get(ToolContractVersionRow, _uid(project_id, set_id, version))
            if row is None:
                return {}
            return {
                item["tool_id"]: ToolContractV1.model_validate(item)
                for item in row.payload_json.get("tools", [])
            }

    def list_tool_contract_sets(self, project_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self.database.sessions() as session:
            query = select(ToolContractVersionRow).order_by(ToolContractVersionRow.created_at.desc())
            if project_id:
                query = query.where(ToolContractVersionRow.project_id == project_id)
            return [
                {
                    **dict(row.payload_json),
                    "project_id": row.project_id,
                    "tool_count": len(row.payload_json.get("tools") or []),
                    "created_at": row.created_at.isoformat(),
                }
                for row in session.scalars(query).all()
            ]

    def save_dataset(
        self,
        project_id: str,
        dataset_id: str,
        version: str,
        name: str,
        cases: Iterable[EvalCaseV1 | Mapping[str, Any]],
        description: str = "",
    ) -> dict[str, Any]:
        normalized = [ContractNormalizer.case(case) for case in cases]
        if len({case.case_id for case in normalized}) != len(normalized):
            raise ValueError("case_id_duplicate")
        manifest = {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "version": version,
            "name": redact_recursive(name),
            "description": redact_recursive(description),
            "case_checksums": {case.case_id: content_checksum(case.model_dump(mode="json")) for case in normalized},
        }
        checksum = content_checksum(manifest)
        uid = _uid(project_id, dataset_id, version)
        with self.database.sessions.begin() as session:
            existing = session.get(DatasetVersionRow, uid)
            if existing and existing.checksum != checksum:
                raise VersionConflictError("dataset_version_immutable_conflict")
            if not existing:
                session.add(
                    DatasetVersionRow(
                        uid=uid,
                        project_id=project_id,
                        dataset_id=dataset_id,
                        version=version,
                        name=manifest["name"],
                        description=manifest["description"],
                        checksum=checksum,
                    )
                )
                for case in normalized:
                    payload = case.model_dump(mode="json")
                    session.add(
                        EvalCaseRow(
                            uid=_uid(uid, case.case_id),
                            dataset_uid=uid,
                            case_id=case.case_id,
                            name=case.name,
                            payload_json=payload,
                            checksum=content_checksum(payload),
                        )
                    )
        return self.get_dataset(project_id, dataset_id, version)

    def get_dataset(self, project_id: str, dataset_id: str, version: str) -> dict[str, Any]:
        uid = _uid(project_id, dataset_id, version)
        with self.database.sessions() as session:
            row = session.get(DatasetVersionRow, uid)
            if row is None:
                raise KeyError("dataset_version_not_found")
            cases = session.scalars(select(EvalCaseRow).where(EvalCaseRow.dataset_uid == uid).order_by(EvalCaseRow.case_id)).all()
            return {
                "project_id": row.project_id,
                "dataset_id": row.dataset_id,
                "version": row.version,
                "name": row.name,
                "description": row.description,
                "case_count": len(cases),
                "cases": [item.payload_json for item in cases],
                "created_at": row.created_at.isoformat(),
            }

    def list_datasets(self, project_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self.database.sessions() as session:
            query = select(DatasetVersionRow).order_by(DatasetVersionRow.created_at.desc())
            if project_id:
                query = query.where(DatasetVersionRow.project_id == project_id)
            rows = session.scalars(query).all()
            return [
                {
                    "project_id": row.project_id,
                    "dataset_id": row.dataset_id,
                    "version": row.version,
                    "name": row.name,
                    "description": row.description,
                    "case_count": session.scalar(select(func.count()).select_from(EvalCaseRow).where(EvalCaseRow.dataset_uid == row.uid)) or 0,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    def save_evaluator_set(self, project_id: str, set_id: str, version: str, metric_ids: Iterable[str]) -> dict[str, Any]:
        payload = {"set_id": set_id, "version": version, "metric_ids": sorted(set(metric_ids))}
        checksum = content_checksum(payload)
        uid = _uid(project_id, set_id, version)
        with self.database.sessions.begin() as session:
            existing = session.get(EvaluatorSetVersionRow, uid)
            if existing and existing.checksum != checksum:
                raise VersionConflictError("evaluator_set_version_immutable_conflict")
            if not existing:
                session.add(EvaluatorSetVersionRow(uid=uid, project_id=project_id, set_id=set_id, version=version, payload_json=payload, checksum=checksum))
        return payload

    def get_evaluator_set(self, project_id: str, set_id: str, version: str) -> dict[str, Any]:
        with self.database.sessions() as session:
            row = session.get(EvaluatorSetVersionRow, _uid(project_id, set_id, version))
            if row is None:
                raise KeyError("evaluator_set_version_not_found")
            return dict(row.payload_json)

    def list_evaluator_sets(self, project_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self.database.sessions() as session:
            query = select(EvaluatorSetVersionRow).order_by(EvaluatorSetVersionRow.created_at.desc())
            if project_id:
                query = query.where(EvaluatorSetVersionRow.project_id == project_id)
            return [
                {
                    **dict(row.payload_json),
                    "project_id": row.project_id,
                    "created_at": row.created_at.isoformat(),
                }
                for row in session.scalars(query).all()
            ]

    def create_experiment(self, spec: ExperimentSpecV1) -> dict[str, Any]:
        payload = spec.model_dump(mode="json")
        total = self.get_dataset(spec.project_id, spec.dataset_id, spec.dataset_version)["case_count"] * spec.repetitions
        with self.database.sessions.begin() as session:
            existing = session.get(ExperimentRow, spec.experiment_id)
            if existing:
                if existing.spec_json != payload:
                    raise VersionConflictError("experiment_id_conflict")
            else:
                session.add(
                    ExperimentRow(
                        experiment_id=spec.experiment_id,
                        project_id=spec.project_id,
                        name=spec.name,
                        status="queued",
                        spec_json=payload,
                        total_runs=total,
                    )
                )
        return self.get_experiment(spec.experiment_id)

    def update_experiment(self, experiment_id: str, *, status: str, completed_runs: Optional[int] = None, error_type: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc)
        with self.database.sessions.begin() as session:
            row = session.get(ExperimentRow, experiment_id)
            if row is None:
                raise KeyError("experiment_not_found")
            row.status = status
            if status == "running" and row.started_at is None:
                row.started_at = now
            if status in {"completed", "failed", "cancelled", "interrupted"}:
                row.ended_at = now
            if completed_runs is not None:
                row.completed_runs = completed_runs
            row.error_type = error_type

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        with self.database.sessions() as session:
            row = session.get(ExperimentRow, experiment_id)
            if row is None:
                raise KeyError("experiment_not_found")
            passed = session.scalar(select(func.count()).select_from(RunRow).where(RunRow.experiment_id == experiment_id, RunRow.overall_pass.is_(True))) or 0
            failed = session.scalar(select(func.count()).select_from(RunRow).where(RunRow.experiment_id == experiment_id, RunRow.overall_pass.is_(False))) or 0
            return {
                "experiment_id": row.experiment_id,
                "project_id": row.project_id,
                "name": row.name,
                "status": row.status,
                "spec": row.spec_json,
                "completed_runs": row.completed_runs,
                "total_runs": row.total_runs,
                "passed_runs": passed,
                "failed_runs": failed,
                "created_at": row.created_at.isoformat(),
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "ended_at": row.ended_at.isoformat() if row.ended_at else None,
                "error_type": row.error_type,
            }

    def list_experiments(self, project_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self.database.sessions() as session:
            query = select(ExperimentRow).order_by(ExperimentRow.created_at.desc())
            if project_id:
                query = query.where(ExperimentRow.project_id == project_id)
            ids = [row.experiment_id for row in session.scalars(query).all()]
        return [self.get_experiment(item) for item in ids]

    def experiment_is_cancelled(self, experiment_id: str) -> bool:
        return self.get_experiment(experiment_id)["status"] == "cancelled"

    def run_exists(self, experiment_id: str, case_id: str, repetition: int) -> bool:
        with self.database.sessions() as session:
            return bool(session.scalar(select(func.count()).select_from(RunRow).where(RunRow.experiment_id == experiment_id, RunRow.case_id == case_id, RunRow.repetition == repetition)))

    def save_trace(
        self,
        trace: TraceEnvelopeV1 | Mapping[str, Any],
        *,
        tool_contracts: Optional[Mapping[str, ToolContractV1]] = None,
    ) -> TraceEnvelopeV1:
        raw = trace.model_dump(mode="json") if isinstance(trace, TraceEnvelopeV1) else dict(trace)
        if tool_contracts is None and raw.get("tool_contract_set_id") and raw.get("tool_contract_version"):
            tool_contracts = self.get_tool_contracts(
                str(raw["project_id"]), str(raw["tool_contract_set_id"]), str(raw["tool_contract_version"])
            )
        declared_sensitive_fields = {
            field for contract in (tool_contracts or {}).values() for field in contract.sensitive_fields
        }
        normalized = TraceNormalizer.normalize(raw, sensitive_fields=declared_sensitive_fields)
        payload = normalized.model_dump(mode="json")
        checksum = content_checksum(payload)
        with self.database.sessions.begin() as session:
            if session.get(ProjectRow, normalized.project_id) is None:
                raise KeyError("project_not_found")
            if normalized.experiment_id:
                experiment = session.get(ExperimentRow, normalized.experiment_id)
                if experiment is not None and experiment.project_id != normalized.project_id:
                    raise ValueError("experiment_project_mismatch")
            if normalized.experiment_id and session.get(ExperimentRow, normalized.experiment_id) is None:
                session.add(
                    ExperimentRow(
                        experiment_id=normalized.experiment_id,
                        project_id=normalized.project_id,
                        name="Imported experiment",
                        status="imported",
                        spec_json={
                            "contract_version": normalized.contract_version,
                            "source": "trace_import",
                            "target_id": normalized.target_id,
                            "target_version": normalized.target_version,
                        },
                        completed_runs=0,
                        total_runs=0,
                    )
                )
            existing = session.get(RunRow, normalized.trace_id)
            if existing and existing.checksum != checksum:
                raise VersionConflictError("trace_id_immutable_conflict")
            if existing:
                return normalized
            session.add(
                RunRow(
                    trace_id=normalized.trace_id,
                    project_id=normalized.project_id,
                    experiment_id=normalized.experiment_id,
                    case_id=normalized.case_id,
                    repetition=normalized.repetition,
                    target_id=normalized.target_id,
                    target_version=normalized.target_version,
                    status=normalized.status.value,
                    started_at=normalized.started_at,
                    ended_at=normalized.ended_at,
                    input_json=normalized.input,
                    output_json=normalized.output,
                    resource_json=normalized.resource_usage.model_dump(mode="json"),
                    tags_json=normalized.tags,
                    metadata_json=normalized.metadata,
                    versions_json={
                        "contract_version": normalized.contract_version,
                        "tool_contract_set_id": normalized.tool_contract_set_id,
                        "tool_contract_version": normalized.tool_contract_version,
                        "dataset_version": normalized.dataset_version,
                        "evaluator_set_version": normalized.evaluator_set_version,
                        "model_config_hash": normalized.model_config_hash,
                    },
                    checksum=checksum,
                )
            )
            for event in normalized.events:
                session.add(
                    TraceEventRow(
                        uid=_uid(normalized.trace_id, event.event_id),
                        trace_id=normalized.trace_id,
                        event_id=event.event_id,
                        sequence=event.sequence,
                        kind=event.kind,
                        status=event.status.value,
                        payload_json=event.model_dump(mode="json"),
                    )
                )
        return normalized

    def save_evaluation(self, result: EvaluationResultV1, *, binding: Mapping[str, Any] | None = None) -> str:
        evaluation_id = f"eval_{uuid4().hex}"
        with self.database.sessions.begin() as session:
            run = session.get(RunRow, result.trace_id)
            if run is None:
                raise KeyError("trace_not_found")
            pinned = {**run.versions_json, "case_id": result.case_id, "source": "runner"}
            if run.experiment_id:
                experiment = session.get(ExperimentRow, run.experiment_id)
                if experiment:
                    pinned.update({key: value for key, value in experiment.spec_json.items()
                                   if key in {"dataset_id", "dataset_version", "tool_contract_set_id",
                                              "tool_contract_version", "evaluator_set_id", "evaluator_set_version"}})
            pinned.update(binding or {})
            payload = redact_recursive(result.model_dump(mode="json"), max_items=10000, max_depth=32)
            session.add(EvaluationRow(
                evaluation_id=evaluation_id, trace_id=result.trace_id, project_id=run.project_id,
                binding_json=redact_recursive(pinned), payload_json=payload,
                checksum=content_checksum({"binding": pinned, "result": payload}),
            ))
            session.flush()
            session.execute(delete(MetricResultRow).where(MetricResultRow.trace_id == result.trace_id))
            session.execute(delete(GateResultRow).where(GateResultRow.trace_id == result.trace_id))
            for metric in result.metric_results:
                payload = redact_recursive(metric.model_dump(mode="json"))
                session.add(EvaluationMetricRow(
                    uid=_uid(evaluation_id, metric.metric_id), evaluation_id=evaluation_id,
                    metric_id=metric.metric_id, payload_json=payload,
                ))
                session.add(
                    MetricResultRow(
                        evaluation_id=evaluation_id,
                        uid=_uid(result.trace_id, metric.metric_id),
                        trace_id=result.trace_id,
                        metric_id=metric.metric_id,
                        group_name=metric.group,
                        status=metric.status.value,
                        numeric_value=_numeric(metric.value),
                        payload_json=payload,
                    )
                )
            for index, gate in enumerate(result.gate_results):
                session.add(EvaluationGateRow(
                    uid=_uid(evaluation_id, str(index)), evaluation_id=evaluation_id,
                    metric_id=gate.metric_id, payload_json=redact_recursive(gate.model_dump(mode="json")),
                ))
                session.add(
                    GateResultRow(
                        evaluation_id=evaluation_id,
                        uid=_uid(result.trace_id, str(index), gate.metric_id),
                        trace_id=result.trace_id,
                        metric_id=gate.metric_id,
                        passed=gate.passed,
                        payload_json=redact_recursive(gate.model_dump(mode="json")),
                    )
                )
            run.overall_pass = result.overall_pass
        return evaluation_id

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any]:
        with self.database.sessions() as session:
            row = session.get(EvaluationRow, evaluation_id)
            if row is None:
                raise KeyError("evaluation_not_found")
            return {**row.payload_json, "evaluation_id": row.evaluation_id,
                    "project_id": row.project_id, "binding": row.binding_json,
                    "created_at": row.created_at.isoformat()}

    def evaluation_history(self, trace_id: str) -> list[dict[str, Any]]:
        with self.database.sessions() as session:
            rows = session.scalars(select(EvaluationRow).where(EvaluationRow.trace_id == trace_id)
                                   .order_by(EvaluationRow.created_at, EvaluationRow.evaluation_id)).all()
            return [{**row.payload_json, "evaluation_id": row.evaluation_id,
                     "project_id": row.project_id, "binding": row.binding_json,
                     "created_at": row.created_at.isoformat()} for row in rows]

    def save_asset(self, project_id: str, kind: str, asset_id: str, version: str,
                   name: str, rows: list[dict]) -> dict[str, Any]:
        if kind not in {"products", "rules"}:
            raise ValueError("asset_kind_invalid")
        payload = {"project_id": project_id, "kind": kind, "asset_id": asset_id,
                   "version": version, "name": redact_recursive(name),
                   "rows": [redact_recursive(row, max_items=10000, max_chars=10 * 1024 * 1024) for row in rows]}
        checksum = content_checksum(payload)
        uid = _uid(project_id, kind, asset_id, version)
        with self.database.sessions.begin() as session:
            existing = session.get(AssetVersionRow, uid)
            if existing and existing.checksum != checksum:
                raise VersionConflictError("asset_version_immutable_conflict")
            if not existing:
                session.add(AssetVersionRow(uid=uid, project_id=project_id, kind=kind,
                                           asset_id=asset_id, version=version,
                                           payload_json=payload, checksum=checksum))
        return {"project_id": project_id, "kind": kind, "asset_id": asset_id,
                "version": version, "checksum": checksum, "row_count": len(rows)}

    def get_asset(self, project_id: str, kind: str, asset_id: str, version: str) -> dict[str, Any]:
        with self.database.sessions() as session:
            row = session.get(AssetVersionRow, _uid(project_id, kind, asset_id, version))
            if row is None:
                raise KeyError("asset_version_not_found")
            return {**row.payload_json, "checksum": row.checksum}

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        with self.database.sessions() as session:
            run = session.get(RunRow, trace_id)
            if run is None:
                raise KeyError("trace_not_found")
            event_rows = session.scalars(select(TraceEventRow).where(TraceEventRow.trace_id == trace_id).order_by(TraceEventRow.sequence)).all()
            metrics = session.scalars(select(MetricResultRow).where(MetricResultRow.trace_id == trace_id).order_by(MetricResultRow.group_name, MetricResultRow.metric_id)).all()
            gates = session.scalars(select(GateResultRow).where(GateResultRow.trace_id == trace_id).order_by(GateResultRow.metric_id)).all()
            annotations = session.scalars(select(AnnotationRow).where(AnnotationRow.trace_id == trace_id).order_by(AnnotationRow.created_at)).all()
            history = self.evaluation_history(trace_id)
            envelope = {
                "contract_version": "1.0",
                "trace_id": run.trace_id,
                "project_id": run.project_id,
                "target_id": run.target_id,
                "target_version": run.target_version,
                **run.versions_json,
                "experiment_id": run.experiment_id,
                "case_id": run.case_id,
                "repetition": run.repetition,
                "started_at": run.started_at.isoformat(),
                "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                "status": run.status,
                "input": run.input_json,
                "output": run.output_json,
                "resource_usage": run.resource_json,
                "tags": run.tags_json,
                "metadata": run.metadata_json,
                "events": [row.payload_json for row in event_rows],
            }
            return {
                "trace": envelope,
                "evaluation_history": history,
                "evaluation_id": metrics[0].evaluation_id if metrics else (history[-1]["evaluation_id"] if history else None),
                "metrics": [row.payload_json for row in metrics],
                "gates": [row.payload_json for row in gates],
                "overall_pass": run.overall_pass,
                "annotations": [
                    {
                        "annotation_id": row.annotation_id,
                        "label": row.label,
                        "value": row.value_json,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in annotations
                ],
            }

    def list_traces(
        self,
        *,
        project_id: Optional[str] = None,
        experiment_id: Optional[str] = None,
        status: Optional[str] = None,
        overall_pass: Optional[bool] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.database.sessions() as session:
            query = select(RunRow).order_by(RunRow.started_at.desc()).limit(min(max(limit, 1), 500))
            if project_id:
                query = query.where(RunRow.project_id == project_id)
            if experiment_id:
                query = query.where(RunRow.experiment_id == experiment_id)
            if status:
                query = query.where(RunRow.status == status)
            if overall_pass is not None:
                query = query.where(RunRow.overall_pass.is_(overall_pass))
            return [
                {
                    "trace_id": row.trace_id,
                    "project_id": row.project_id,
                    "experiment_id": row.experiment_id,
                    "case_id": row.case_id,
                    "target_id": row.target_id,
                    "target_version": row.target_version,
                    "status": row.status,
                    "overall_pass": row.overall_pass,
                    "started_at": row.started_at.isoformat(),
                    "active_runtime_ms": row.resource_json.get("active_runtime_ms"),
                    "estimated_cost": row.resource_json.get("estimated_cost"),
                    "tags": row.tags_json,
                }
                for row in session.scalars(query).all()
            ]

    def add_annotation(self, trace_id: str, label: str, value: Mapping[str, Any]) -> dict[str, Any]:
        annotation_id = f"ann_{uuid4().hex}"
        payload = redact_recursive(dict(value))
        with self.database.sessions.begin() as session:
            if session.get(RunRow, trace_id) is None:
                raise KeyError("trace_not_found")
            session.add(AnnotationRow(annotation_id=annotation_id, trace_id=trace_id, label=redact_recursive(label), value_json=payload))
        return {"annotation_id": annotation_id, "trace_id": trace_id, "label": label, "value": payload}


    def dashboard(self, project_id: Optional[str] = None) -> dict[str, Any]:
        traces = self.list_traces(project_id=project_id, limit=500)
        evaluated = [row for row in traces if row["overall_pass"] is not None]
        pass_rate = (sum(row["overall_pass"] is True for row in evaluated) / len(evaluated)) if evaluated else None
        latencies = sorted(float(row["active_runtime_ms"]) for row in traces if isinstance(row.get("active_runtime_ms"), (int, float)))
        p95 = latencies[min(len(latencies) - 1, max(0, int(len(latencies) * 0.95) - 1))] if latencies else None
        costs = [float(row["estimated_cost"]) for row in traces if isinstance(row.get("estimated_cost"), (int, float))]
        trend: dict[str, dict[str, Any]] = {}
        for row in reversed(traces):
            day = str(row["started_at"])[:10]
            bucket = trend.setdefault(day, {"date": day, "runs": 0, "evaluated": 0, "passed": 0})
            bucket["runs"] += 1
            if row["overall_pass"] is not None:
                bucket["evaluated"] += 1
                bucket["passed"] += int(row["overall_pass"] is True)
        trend_rows = []
        for bucket in trend.values():
            evaluated_count = bucket.pop("evaluated")
            bucket["pass_rate"] = bucket.pop("passed") / evaluated_count if evaluated_count else None
            trend_rows.append(bucket)

        with self.database.sessions() as session:
            metric_query = select(MetricResultRow).join(RunRow, RunRow.trace_id == MetricResultRow.trace_id)
            gate_query = select(GateResultRow).join(RunRow, RunRow.trace_id == GateResultRow.trace_id).where(GateResultRow.passed.is_(False))
            if project_id:
                metric_query = metric_query.where(RunRow.project_id == project_id)
                gate_query = gate_query.where(RunRow.project_id == project_id)
            metric_rows = session.scalars(metric_query).all()
            gate_rows = session.scalars(gate_query).all()
        metric_groups: dict[str, dict[str, Any]] = {}
        for row in metric_rows:
            bucket = metric_groups.setdefault(
                row.metric_id,
                {"metric_id": row.metric_id, "group": row.group_name, "applicable": 0, "passed": 0, "failed": 0, "values": []},
            )
            if row.status in {"pass", "fail"}:
                bucket["applicable"] += 1
                bucket["passed"] += int(row.status == "pass")
                bucket["failed"] += int(row.status == "fail")
            if row.numeric_value is not None:
                bucket["values"].append(float(row.numeric_value))
        metric_health = []
        for bucket in metric_groups.values():
            values = bucket.pop("values")
            bucket["pass_rate"] = bucket["passed"] / bucket["applicable"] if bucket["applicable"] else None
            bucket["average"] = sum(values) / len(values) if values else None
            metric_health.append(bucket)
        failures: dict[str, int] = {}
        for row in gate_rows:
            failures[row.metric_id] = failures.get(row.metric_id, 0) + 1
        return {
            "project_id": project_id,
            "trace_count": len(traces),
            "overall_pass_rate": pass_rate,
            "gate_failure_count": sum(row["overall_pass"] is False for row in evaluated),
            "p95_active_runtime_ms": p95,
            "average_known_cost": (sum(costs) / len(costs)) if costs else None,
            "trend": trend_rows[-14:],
            "metric_health": sorted(metric_health, key=lambda item: (-item["failed"], item["metric_id"])),
            "failure_reasons": [
                {"metric_id": key, "count": value}
                for key, value in sorted(failures.items(), key=lambda item: (-item[1], item[0]))
            ],
            "recent_traces": traces[:8],
            "recent_experiments": self.list_experiments(project_id)[:8],
        }

    def compare_experiments(self, left_id: str, right_id: str) -> dict[str, Any]:
        def summarize(experiment_id: str) -> dict[str, Any]:
            rows = self.list_traces(experiment_id=experiment_id, limit=500)
            evaluated = [row for row in rows if row["overall_pass"] is not None]
            with self.database.sessions() as session:
                metric_rows = session.scalars(
                    select(MetricResultRow)
                    .join(RunRow, RunRow.trace_id == MetricResultRow.trace_id)
                    .where(RunRow.experiment_id == experiment_id)
                ).all()
            grouped: dict[str, dict[str, Any]] = {}
            for metric in metric_rows:
                bucket = grouped.setdefault(metric.metric_id, {"values": [], "applicable": 0, "passed": 0})
                if metric.numeric_value is not None:
                    bucket["values"].append(float(metric.numeric_value))
                if metric.status in {"pass", "fail"}:
                    bucket["applicable"] += 1
                    bucket["passed"] += int(metric.status == "pass")
            metrics = {
                metric_id: {
                    "average": sum(bucket["values"]) / len(bucket["values"]) if bucket["values"] else None,
                    "pass_rate": bucket["passed"] / bucket["applicable"] if bucket["applicable"] else None,
                    "applicable_runs": bucket["applicable"],
                }
                for metric_id, bucket in grouped.items()
            }
            return {
                "experiment_id": experiment_id,
                "run_count": len(rows),
                "pass_rate": (sum(row["overall_pass"] is True for row in evaluated) / len(evaluated)) if evaluated else None,
                "average_active_runtime_ms": (
                    sum(float(row["active_runtime_ms"]) for row in rows if isinstance(row.get("active_runtime_ms"), (int, float)))
                    / max(1, sum(isinstance(row.get("active_runtime_ms"), (int, float)) for row in rows))
                ),
                "metrics": metrics,
            }

        return {"left": summarize(left_id), "right": summarize(right_id)}
