"""Immutable nonsecret configuration and bounded connection-test status."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from commerce_eval.storage.models import Base, utc_now


class ProviderConfigVersionRow(Base):
    __tablename__ = "provider_config_versions"

    provider_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProviderCheckRow(Base):
    __tablename__ = "provider_checks"

    provider_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)


def initialize_provider_schema(bind) -> None:
    """For startup integration and the additive Alembic migration."""
    for model in (ProviderConfigVersionRow, ProviderCheckRow):
        model.__table__.create(bind, checkfirst=True)
