"""Execute shipped 0005 preflight SQL against a database at revision 0004."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text

from tests.helpers.database import (
    alembic_config,
    reset_test_database,
    test_database_url,
    truncate_all_tables,
)
from tests.helpers.migration_0005_seed import (
    insert_cross_report_fact_context,
    insert_cross_report_fact_declaration,
    insert_cross_report_fact_unit,
    insert_cross_report_label,
    insert_cross_report_reference,
    insert_cross_report_relationship_source,
    insert_cross_report_relationship_target,
    seed_two_reports,
)
from tests.helpers.preflight_0005 import load_preflight_statements, run_preflight

pytestmark = pytest.mark.database


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


def test_preflight_parser_contract() -> None:
    load_preflight_statements()


def _truncate(engine: Engine) -> None:
    with engine.begin() as conn:
        truncate_all_tables(conn)


def test_preflight_clean_on_populated_0004(engine_at_0004: Engine) -> None:
    _truncate(engine_at_0004)
    with engine_at_0004.begin() as conn:
        seed_two_reports(conn)
    with engine_at_0004.connect() as conn:
        for rows in run_preflight(conn):
            assert rows == []


@pytest.mark.parametrize(
    ("offender", "query_index"),
    [
        (insert_cross_report_fact_context, 2),
        (insert_cross_report_fact_unit, 3),
        (insert_cross_report_fact_declaration, 4),
        (insert_cross_report_label, 5),
        (insert_cross_report_reference, 6),
        (insert_cross_report_relationship_source, 7),
        (insert_cross_report_relationship_target, 8),
    ],
)
def test_preflight_detects_cross_report_fk_offender(
    engine_at_0004: Engine,
    offender: Callable,
    query_index: int,
) -> None:
    url = test_database_url()
    _truncate(engine_at_0004)
    with engine_at_0004.begin() as conn:
        ids = seed_two_reports(conn)
        offender(conn, ids)
    with engine_at_0004.connect() as conn:
        results = run_preflight(conn)
    assert all(i == query_index or not results[i] for i in range(len(results)))
    assert results[query_index]

    report_b = ids["report_b"]
    with engine_at_0004.begin() as conn:
        if query_index in (2, 3, 4):
            conn.execute(
                text("DELETE FROM source.fact WHERE report_id = :b"),
                {"b": report_b},
            )
        elif query_index == 5:
            conn.execute(
                text("DELETE FROM source.concept_label WHERE report_id = :b"),
                {"b": report_b},
            )
        elif query_index == 6:
            conn.execute(
                text("DELETE FROM source.concept_reference WHERE report_id = :b"),
                {"b": report_b},
            )
        elif query_index == 7:
            conn.execute(
                text("DELETE FROM source.relationship WHERE report_id = :b"),
                {"b": report_b},
            )
        else:
            conn.execute(
                text("DELETE FROM source.relationship WHERE report_id = :b"),
                {"b": report_b},
            )
            conn.execute(
                text(
                    "DELETE FROM source.concept_declaration"
                    " WHERE report_id = :b AND concept_id = :c"
                ),
                {"b": report_b, "c": ids["assets_id"]},
            )

    with engine_at_0004.connect() as conn:
        for rows in run_preflight(conn):
            assert rows == []

    cfg = alembic_config(url)
    command.upgrade(cfg, "0005_m1a_integrity")
    command.downgrade(cfg, "0004_m1a_network_identity")
