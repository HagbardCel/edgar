"""Integration: 0005_m1a_integrity upgrade and upstream CHECK."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.helpers.database import (
    alembic_config,
    reset_test_database,
    test_database_url,
    truncate_all_tables,
)
from tests.helpers.migration_0005_seed import seed_two_reports

pytestmark = pytest.mark.database

_COMPOSITE_FK_NAMES = (
    "fact_report_context_fkey",
    "fact_report_unit_fkey",
    "fact_report_concept_declaration_fkey",
    "concept_label_report_concept_declaration_fkey",
    "concept_reference_report_concept_declaration_fkey",
    "relationship_report_source_concept_declaration_fkey",
    "relationship_report_target_concept_declaration_fkey",
)


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


def _constraint_exists(engine: Engine, name: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT 1 FROM pg_constraint c
                    JOIN pg_namespace n ON n.oid = c.connamespace
                    WHERE n.nspname = 'source' AND c.conname = :name
                    """
                ),
                {"name": name},
            ).scalar_one_or_none()
        )


def test_upgrade_adds_upstream_columns(engine: Engine) -> None:
    assert _column_exists(engine, "upstream_item_fact_count")
    assert _column_exists(engine, "upstream_inventory_version")


def test_all_0005_constraints_present(engine: Engine) -> None:
    for name in _COMPOSITE_FK_NAMES:
        assert _constraint_exists(engine, name)
    assert _constraint_exists(engine, "uq_source_context_report_id")
    assert _constraint_exists(engine, "uq_source_unit_report_id")
    assert _constraint_exists(engine, "ck_source_xbrl_report_upstream_inventory")


def test_populated_0004_to_0005_upgrade(engine: Engine) -> None:
    url = test_database_url()
    cfg = alembic_config(url)
    command.downgrade(cfg, "0004_m1a_network_identity")
    with engine.begin() as conn:
        truncate_all_tables(conn)
        ids = seed_two_reports(conn)
    command.upgrade(cfg, "0005_m1a_integrity")
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM source.xbrl_report")).scalar_one()
    assert int(count) == 2
    assert ids["report_a"] > 0
    command.upgrade(cfg, "head")


def test_upstream_check_rejects_half_paired(engine: Engine) -> None:
    with engine.connect() as conn:
        report_id = conn.execute(
            text("SELECT id FROM source.xbrl_report ORDER BY id LIMIT 1")
        ).scalar_one()
        nested = conn.begin_nested()
        with pytest.raises(DBAPIError):
            conn.execute(
                text(
                    """
                    UPDATE source.xbrl_report
                    SET upstream_item_fact_count = 1,
                        upstream_inventory_version = NULL
                    WHERE id = :id
                    """
                ),
                {"id": report_id},
            )
        nested.rollback()


def test_upstream_check_rejects_null_count_with_version(engine: Engine) -> None:
    with engine.connect() as conn:
        report_id = conn.execute(
            text("SELECT id FROM source.xbrl_report ORDER BY id LIMIT 1")
        ).scalar_one()
        nested = conn.begin_nested()
        with pytest.raises(DBAPIError):
            conn.execute(
                text(
                    """
                    UPDATE source.xbrl_report
                    SET upstream_item_fact_count = NULL,
                        upstream_inventory_version = 'upstream-v1'
                    WHERE id = :id
                    """
                ),
                {"id": report_id},
            )
        nested.rollback()


def test_upstream_check_rejects_wrong_version(engine: Engine) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, arelle_item_fact_count
                FROM source.xbrl_report ORDER BY id LIMIT 1
                """
            )
        ).one()
        report_id, fact_count = row[0], row[1]
        nested = conn.begin_nested()
        with pytest.raises(DBAPIError):
            conn.execute(
                text(
                    """
                    UPDATE source.xbrl_report
                    SET upstream_item_fact_count = :fc,
                        upstream_inventory_version = 'upstream-bad'
                    WHERE id = :id
                    """
                ),
                {"id": report_id, "fc": fact_count},
            )
        nested.rollback()


def test_upstream_check_accepts_matching_upstream_v1(engine: Engine) -> None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, arelle_item_fact_count
                FROM source.xbrl_report ORDER BY id LIMIT 1
                """
            )
        ).one()
        report_id, fact_count = row[0], row[1]
        nested = conn.begin_nested()
        conn.execute(
            text(
                """
                UPDATE source.xbrl_report
                SET upstream_item_fact_count = :fc,
                    upstream_inventory_version = 'upstream-v1'
                WHERE id = :id
                """
            ),
            {"id": report_id, "fc": fact_count},
        )
        stored = conn.execute(
            text(
                """
                SELECT upstream_item_fact_count, upstream_inventory_version,
                       arelle_item_fact_count
                FROM source.xbrl_report WHERE id = :id
                """
            ),
            {"id": report_id},
        ).one()
        assert stored[0] == stored[2]
        assert stored[1] == "upstream-v1"
        nested.rollback()


def test_upstream_check_rejects_count_mismatch(engine: Engine) -> None:
    with engine.connect() as conn:
        report_id = conn.execute(
            text("SELECT id FROM source.xbrl_report ORDER BY id LIMIT 1")
        ).scalar_one()
        nested = conn.begin_nested()
        with pytest.raises(DBAPIError):
            conn.execute(
                text(
                    """
                    UPDATE source.xbrl_report
                    SET upstream_item_fact_count = 999,
                        upstream_inventory_version = 'upstream-v1'
                    WHERE id = :id
                    """
                ),
                {"id": report_id},
            )
        nested.rollback()


def test_downgrade_removes_all_0005_objects(engine: Engine) -> None:
    url = test_database_url()
    cfg = alembic_config(url)
    command.downgrade(cfg, "0004_m1a_network_identity")
    with engine.begin() as conn:
        truncate_all_tables(conn)
        seed_two_reports(conn)
    command.upgrade(cfg, "0005_m1a_integrity")
    command.downgrade(cfg, "0004_m1a_network_identity")
    assert not _column_exists(engine, "upstream_item_fact_count")
    assert not _column_exists(engine, "upstream_inventory_version")
    for name in _COMPOSITE_FK_NAMES:
        assert not _constraint_exists(engine, name)
    assert not _constraint_exists(engine, "uq_source_context_report_id")
    assert not _constraint_exists(engine, "uq_source_unit_report_id")
    assert not _constraint_exists(engine, "ck_source_xbrl_report_upstream_inventory")
    with engine.connect() as conn:
        reports = conn.execute(text("SELECT COUNT(*) FROM source.xbrl_report")).scalar_one()
    assert int(reports) == 2
    command.upgrade(cfg, "head")


def test_report_delete_cascades_owned_rows_with_composite_fks(engine: Engine) -> None:
    url = test_database_url()
    cfg = alembic_config(url)
    command.downgrade(cfg, "0004_m1a_network_identity")
    with engine.begin() as conn:
        truncate_all_tables(conn)
        ids = seed_two_reports(conn)
    command.upgrade(cfg, "0005_m1a_integrity")
    report_a = ids["report_a"]
    report_b = ids["report_b"]
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM source.xbrl_report WHERE id = :id"),
            {"id": report_b},
        )
        remaining_reports = conn.execute(
            text("SELECT COUNT(*) FROM source.xbrl_report")
        ).scalar_one()
        facts_a = conn.execute(
            text("SELECT COUNT(*) FROM source.fact WHERE report_id = :id"),
            {"id": report_a},
        ).scalar_one()
        contexts_a = conn.execute(
            text("SELECT COUNT(*) FROM source.context WHERE report_id = :id"),
            {"id": report_a},
        ).scalar_one()
    assert int(remaining_reports) == 1
    assert int(facts_a) == 1
    assert int(contexts_a) == 1

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM source.xbrl_report WHERE id = :id"),
            {"id": report_a},
        )
        assert conn.execute(text("SELECT COUNT(*) FROM source.fact")).scalar_one() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM source.context")).scalar_one() == 0

    command.upgrade(cfg, "head")
