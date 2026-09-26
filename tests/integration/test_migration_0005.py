"""Integration: 0005_m1a_integrity upgrade and upstream CHECK."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text

from tests.helpers.database import (
    alembic_config,
    reset_test_database,
    test_database_url,
)

pytestmark = pytest.mark.database


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = test_database_url()
    eng = create_engine(url, future=True)
    reset_test_database(eng, database_url=url)
    yield eng
    eng.dispose()


def _column_exists(engine: Engine, column: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'source' AND table_name = 'xbrl_report'
                      AND column_name = :column
                    """
                ),
                {"column": column},
            ).scalar_one_or_none()
        )


def test_upgrade_adds_upstream_columns(engine: Engine) -> None:
    assert _column_exists(engine, "upstream_item_fact_count")
    assert _column_exists(engine, "upstream_inventory_version")


def test_composite_fk_present(engine: Engine) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT 1 FROM pg_constraint c
                JOIN pg_namespace n ON n.oid = c.connamespace
                WHERE n.nspname = 'source' AND c.conname = 'fact_report_context_fkey'
                """
            )
        ).scalar_one_or_none()
    assert row is not None


def test_downgrade_removes_0005_objects(engine: Engine) -> None:
    url = test_database_url()
    cfg = alembic_config(url)
    command.downgrade(cfg, "0004_m1a_network_identity")
    assert not _column_exists(engine, "upstream_item_fact_count")
    with engine.connect() as conn:
        fk = conn.execute(
            text(
                """
                SELECT 1 FROM pg_constraint c
                JOIN pg_namespace n ON n.oid = c.connamespace
                WHERE n.nspname = 'source' AND c.conname = 'fact_report_context_fkey'
                """
            )
        ).scalar_one_or_none()
    assert fk is None
    command.upgrade(cfg, "head")
