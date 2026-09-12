"""SQLAlchemy persistence models for local-first operation."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class TargetVersionRow(Base):
    __tablename__ = "target_versions"
    __table_args__ = (UniqueConstraint("project_id", "target_id", "version"),)

    uid: Mapped[str] = mapped_column(String(320), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    target_id: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(240))
    adapter_type: Mapped[str] = mapped_column(String(20))
    safe_for_eval: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[dict] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ToolContractVersionRow(Base):
    __tablename__ = "tool_contract_versions"
    __table_args__ = (UniqueConstraint("project_id", "set_id", "version"),)

    uid: Mapped[str] = mapped_column(String(320), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    set_id: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[str] = mapped_column(String(80))
    payload_json: Mapped[dict] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DatasetVersionRow(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("project_id", "dataset_id", "version"),)

    uid: Mapped[str] = mapped_column(String(320), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    dataset_id: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EvalCaseRow(Base):
    __tablename__ = "eval_cases"
    __table_args__ = (UniqueConstraint("dataset_uid", "case_id"),)

    uid: Mapped[str] = mapped_column(String(500), primary_key=True)
    dataset_uid: Mapped[str] = mapped_column(ForeignKey("dataset_versions.uid"), index=True)
    case_id: Mapped[str] = mapped_column(String(160), index=True)
    name: Mapped[str] = mapped_column(String(240))
    payload_json: Mapped[dict] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))


class EvaluatorSetVersionRow(Base):
    __tablename__ = "evaluator_set_versions"
    __table_args__ = (UniqueConstraint("project_id", "set_id", "version"),)

    uid: Mapped[str] = mapped_column(String(320), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    set_id: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[str] = mapped_column(String(80))
    payload_json: Mapped[dict] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExperimentRow(Base):
    __tablename__ = "experiments"

    experiment_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(40), index=True)
    spec_json: Mapped[dict] = mapped_column(JSON)
    completed_runs: Mapped[int] = mapped_column(Integer, default=0)
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(160), nullable=True)


class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("experiment_id", "case_id", "repetition"),)

    trace_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.experiment_id"), index=True, nullable=True)
    case_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    repetition: Mapped[int] = mapped_column(Integer, default=1)
    target_id: Mapped[str] = mapped_column(String(160), index=True)
    target_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_json: Mapped[dict] = mapped_column(JSON)
    output_json: Mapped[dict] = mapped_column(JSON)
    resource_json: Mapped[dict] = mapped_column(JSON)
    tags_json: Mapped[dict] = mapped_column(JSON)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    versions_json: Mapped[dict] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    overall_pass: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)


class TraceEventRow(Base):
    __tablename__ = "trace_events"
    __table_args__ = (UniqueConstraint("trace_id", "event_id"), UniqueConstraint("trace_id", "sequence"))

    uid: Mapped[str] = mapped_column(String(360), primary_key=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("runs.trace_id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(160))
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON)


class MetricResultRow(Base):
    __tablename__ = "metric_results"
    __table_args__ = (UniqueConstraint("trace_id", "metric_id"),)

    uid: Mapped[str] = mapped_column(String(360), primary_key=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("runs.trace_id", ondelete="CASCADE"), index=True)
    evaluation_id: Mapped[str | None] = mapped_column(ForeignKey("evaluations.evaluation_id"), nullable=True, index=True)
    metric_id: Mapped[str] = mapped_column(String(160), index=True)
    group_name: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON)


class GateResultRow(Base):
    __tablename__ = "gate_results"

    uid: Mapped[str] = mapped_column(String(360), primary_key=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("runs.trace_id", ondelete="CASCADE"), index=True)
    evaluation_id: Mapped[str | None] = mapped_column(ForeignKey("evaluations.evaluation_id"), nullable=True, index=True)
    metric_id: Mapped[str] = mapped_column(String(160), index=True)
    passed: Mapped[bool] = mapped_column(Boolean, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON)


class AnnotationRow(Base):
    __tablename__ = "annotations"

    annotation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("runs.trace_id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    value_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EvaluationRow(Base):
    __tablename__ = "evaluations"

    evaluation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("runs.trace_id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    binding_json: Mapped[dict] = mapped_column(JSON)
    payload_json: Mapped[dict] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EvaluationMetricRow(Base):
    __tablename__ = "evaluation_metrics"
    __table_args__ = (UniqueConstraint("evaluation_id", "metric_id"),)

    uid: Mapped[str] = mapped_column(String(360), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.evaluation_id"), index=True)
    metric_id: Mapped[str] = mapped_column(String(160))
    payload_json: Mapped[dict] = mapped_column(JSON)


class EvaluationGateRow(Base):
    __tablename__ = "evaluation_gates"

    uid: Mapped[str] = mapped_column(String(360), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.evaluation_id"), index=True)
    metric_id: Mapped[str] = mapped_column(String(160))
    payload_json: Mapped[dict] = mapped_column(JSON)


class ImportDraftRow(Base):
    __tablename__ = "import_drafts"

    import_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload_json: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AssetVersionRow(Base):
    __tablename__ = "asset_versions"
    __table_args__ = (UniqueConstraint("project_id", "kind", "asset_id", "version"),)

    uid: Mapped[str] = mapped_column(String(400), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    asset_id: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(80))
    payload_json: Mapped[dict] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
