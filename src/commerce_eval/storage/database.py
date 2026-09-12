"""Database lifecycle and SQLite safety defaults."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, ExperimentRow


def default_home() -> Path:
    override = os.environ.get("COMMERCE_EVAL_HOME")
    return Path(override).expanduser().resolve() if override else (Path.home() / ".commerce-agent-eval")


def default_database_path() -> Path:
    return default_home() / "platform.db"


class Database:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or default_database_path()).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
            future=True,
        )
        self._configure_sqlite(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)

    @staticmethod
    def _configure_sqlite(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def set_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

    def initialize(self) -> None:
        from . import business_evidence
        from commerce_eval.providers import models as provider_models
        from .upgrades import upgrade_onboarding

        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            upgrade_onboarding(connection)
        with self.sessions.begin() as session:
            session.execute(
                update(ExperimentRow)
                .where(ExperimentRow.status.in_(["queued", "running"]))
                .values(status="interrupted", error_type="process_restarted")
            )

    def dispose(self) -> None:
        self.engine.dispose()

