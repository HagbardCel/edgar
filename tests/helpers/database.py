"""Shared helpers for guarded PostgreSQL integration tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url

from edgar.db.schema import ALL_TABLES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


def test_database_url() -> str:
    """Return EDGAR_TEST_DATABASE_URL or skip; refuse non-edgar_test databases."""
    raw = os.environ.get("EDGAR_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("EDGAR_TEST_DATABASE_URL not set")
    url = make_url(raw)
    if url.database != "edgar_test":
        pytest.fail(
            "Refusing destructive database tests: "
            "EDGAR_TEST_DATABASE_URL must target database 'edgar_test'"
        )
    return raw


# Prevent pytest from treating this helper as a collected test when imported.
test_database_url.__test__ = False  # type: ignore[attr-defined]


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.attributes["database_url"] = database_url
    return cfg


def truncate_all_tables(conn: Connection) -> None:
    """Truncate every catalog/semantic/document table owned by this schema."""
    names = [table.name for table in ALL_TABLES]
    conn.execute(text("TRUNCATE " + ", ".join(names) + " RESTART IDENTITY CASCADE"))
