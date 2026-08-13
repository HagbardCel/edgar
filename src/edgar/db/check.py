"""Shared PostgreSQL reachability and Alembic revision checks."""

from __future__ import annotations

from dataclasses import dataclass

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine

from edgar.db.engine import create_db_engine


@dataclass(frozen=True)
class DatabaseRevision:
    current: str | None
    head: str


class DatabaseRevisionMismatch(RuntimeError):
    def __init__(self, revision: DatabaseRevision) -> None:
        self.revision = revision
        super().__init__(f"database revision {revision.current!r} != head {revision.head!r}")


def _alembic_ini_path() -> str:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    return str(repo_root / "alembic.ini")


def database_revision(url: str, *, engine: Engine | None = None) -> DatabaseRevision:
    """Return current Alembic revision and script head after verifying connectivity."""
    owned_engine = engine is None
    db_engine = engine or create_db_engine(url)
    try:
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        from alembic.config import Config

        cfg = Config(_alembic_ini_path())
        cfg.attributes["database_url"] = url
        script = ScriptDirectory.from_config(cfg)
        head = script.get_current_head()
        if head is None:
            raise RuntimeError("alembic script has no head revision")
        with db_engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current = context.get_current_revision()
        return DatabaseRevision(current=current, head=head)
    finally:
        if owned_engine:
            db_engine.dispose()


def require_database_at_head(url: str, *, engine: Engine | None = None) -> DatabaseRevision:
    revision = database_revision(url, engine=engine)
    if revision.current != revision.head:
        raise DatabaseRevisionMismatch(revision)
    return revision
