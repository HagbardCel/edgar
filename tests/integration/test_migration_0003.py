"""Integration: 0003_m1a_extraction_receipt upgrade/downgrade reversibility."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text

from tests.helpers.database import alembic_config, reset_test_database, test_database_url

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
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'source'
                      AND table_name = 'xbrl_report'
                      AND column_name = :column
                    """
                ),
                {"column": column},
            ).scalar_one_or_none()
        )


def _revision(engine: Engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _is_nullable_jsonb(engine: Engine) -> bool:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    """
                SELECT is_nullable, data_type, udt_name
                FROM information_schema.columns
                WHERE table_schema = 'source'
                  AND table_name = 'xbrl_report'
                  AND column_name = 'extraction_receipt'
                """
                )
            )
            .mappings()
            .one()
        )
    return row["is_nullable"] == "YES" and row["udt_name"] == "jsonb"


def test_0003_upgrade_downgrade_reupgrade(engine: Engine) -> None:
    url = test_database_url()
    cfg = alembic_config(url)

    command.downgrade(cfg, "0002_registry")
    assert _revision(engine) == "0002_registry"
    assert not _column_exists(engine, "extraction_receipt")

    command.upgrade(cfg, "0003_m1a_extraction_receipt")
    assert _revision(engine) == "0003_m1a_extraction_receipt"
    assert _column_exists(engine, "extraction_receipt")
    assert _is_nullable_jsonb(engine)

    command.downgrade(cfg, "0002_registry")
    assert _revision(engine) == "0002_registry"
    assert not _column_exists(engine, "extraction_receipt")

    command.upgrade(cfg, "0003_m1a_extraction_receipt")
    assert _revision(engine) == "0003_m1a_extraction_receipt"
    assert _column_exists(engine, "extraction_receipt")

    command.upgrade(cfg, "0003_m1a_extraction_receipt")
    assert _revision(engine) == "0003_m1a_extraction_receipt"
