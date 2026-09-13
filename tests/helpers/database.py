"""Shared helpers for guarded PostgreSQL integration tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
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


def reset_test_database(engine: Engine, *, database_url: str | None = None) -> None:
    """Drop source + public test objects, then ``alembic upgrade head``.

    Phase-1 DBs stamped with the deleted 0001–0004 lineage cannot upgrade to
    ``0001_source_v2``. Integration fixtures must recreate via this helper.
    """
    url = database_url or str(engine.url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS source CASCADE"))
        # Drop leftover Phase-1 public tables / alembic_version from prior baselines.
        conn.execute(
            text(
                """
                DO $$
                DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (
                        SELECT tablename
                        FROM pg_tables
                        WHERE schemaname = 'public'
                    ) LOOP
                        EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename);
                    END LOOP;
                END $$;
                """
            )
        )
    command.upgrade(alembic_config(url), "head")


def truncate_all_tables(conn: Connection) -> None:
    """Truncate every source.* table owned by the V2 schema."""
    qualified: list[str] = []
    for table in ALL_TABLES:
        if table.schema:
            qualified.append(f"{table.schema}.{table.name}")
        else:
            qualified.append(table.name)
    conn.execute(text("TRUNCATE " + ", ".join(qualified) + " RESTART IDENTITY CASCADE"))
