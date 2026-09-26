"""Execute shipped 0005 preflight SQL against a database at revision 0004."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text

from tests.helpers.database import alembic_config, reset_test_database, test_database_url

pytestmark = pytest.mark.database

_PREFLIGHT_SQL = (
    Path(__file__).resolve().parents[2] / "migrations" / "preflight" / "0005_readonly_preflight.sql"
)


@pytest.fixture(scope="module")
def engine_at_0004() -> Iterator[Engine]:
    url = test_database_url()
    eng = create_engine(url, future=True)
    reset_test_database(eng, database_url=url)
    cfg = alembic_config(url)
    command.downgrade(cfg, "0004_m1a_network_identity")
    yield eng
    reset_test_database(eng, database_url=url)
    eng.dispose()


def _run_preflight(conn) -> list[list]:
    sql = _PREFLIGHT_SQL.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
    results: list[list] = []
    for statement in statements:
        rows = conn.execute(text(statement)).fetchall()
        results.append(list(rows))
    return results


def test_preflight_clean_on_empty_0004(engine_at_0004: Engine) -> None:
    with engine_at_0004.connect() as conn:
        for rows in _run_preflight(conn):
            assert rows == []
