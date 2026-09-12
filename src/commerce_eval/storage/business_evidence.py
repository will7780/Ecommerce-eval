"""Evaluator-owned evidence, separate from candidate-controlled trace payloads."""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from commerce_eval.contracts import BusinessEvidenceBundleV1
from commerce_eval.core import content_checksum, redact_recursive
from .models import Base, RunRow


class BusinessEvidenceRow(Base):
    __tablename__ = "business_evidence"
    trace_id: Mapped[str] = mapped_column(String(160), ForeignKey("runs.trace_id"), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(120), nullable=False)
    session_id: Mapped[str] = mapped_column(String(240), nullable=False)
    collector_id: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def save_collected_business_evidence(repository, trace_id, evidence, *, session_id, project_id, collector_id):
    """Internal harness call only; deliberately absent from all ingestion APIs."""
    bundle = BusinessEvidenceBundleV1.model_validate(evidence)
    if bundle.run_id != session_id or bundle.project_id != project_id or bundle.collector_id != collector_id:
        raise ValueError("business_evidence_scope_mismatch")
    raw = bundle.model_dump(mode="json")
    safe = redact_recursive(raw, max_depth=32, max_items=20000, max_chars=200000)
    if safe != raw:
        safe["complete"] = False
        safe["omission_reasons"] = [*safe.get("omission_reasons", []), "evidence_redacted_or_truncated"]
    bundle = BusinessEvidenceBundleV1.model_validate(safe)
    checksum = content_checksum(safe)
    with repository.database.sessions.begin() as session:
        run = session.get(RunRow, trace_id)
        if run is None or run.project_id != project_id:
            raise ValueError("business_evidence_trace_mismatch")
        old = session.get(BusinessEvidenceRow, trace_id)
        if old is not None:
            if old.checksum != checksum or old.session_id != session_id:
                raise ValueError("business_evidence_immutable_conflict")
        else:
            session.add(BusinessEvidenceRow(
                trace_id=trace_id, project_id=project_id, session_id=session_id,
                collector_id=collector_id, payload=safe, checksum=checksum,
            ))
    return bundle


def load_business_evidence(repository, trace_id, *, project_id):
    with repository.database.sessions() as session:
        row = session.get(BusinessEvidenceRow, trace_id)
        if row is None:
            return None
        if row.project_id != project_id or content_checksum(row.payload) != row.checksum:
            raise ValueError("business_evidence_integrity_error")
        return BusinessEvidenceBundleV1.model_validate(row.payload)
