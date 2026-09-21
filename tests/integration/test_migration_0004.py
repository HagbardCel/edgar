"""Integration: 0004_m1a_network_identity upgrade/downgrade and CHECK contracts."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from edgar.domain.concept_id import concept_id
from tests.helpers.database import (
    alembic_config,
    reset_test_database,
    test_database_url,
    truncate_all_tables,
)

pytestmark = pytest.mark.database

_TABLES = (
    ("relationship", "ck_source_relationship_link_arc_qname"),
    ("concept_label", "ck_source_concept_label_link_arc_qname"),
    ("concept_reference", "ck_source_concept_reference_link_arc_qname"),
)

_MARKER_ROLE = "http://example.com/role/Pre0004"
_MARKER_TEXT = "pre-0004-label-text"
_NS = "http://example.com/pre0004"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = test_database_url()
    eng = create_engine(url, future=True)
    reset_test_database(eng, database_url=url)
    yield eng
    eng.dispose()


def _revision(engine: Engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _column_exists(engine: Engine, table: str, column: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'source'
                      AND table_name = :table
                      AND column_name = :column
                    """
                ),
                {"table": table, "column": column},
            ).scalar_one_or_none()
        )


def _check_exists(engine: Engine, name: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT 1
                    FROM pg_constraint c
                    JOIN pg_namespace n ON n.oid = c.connamespace
                    WHERE n.nspname = 'source' AND c.conname = :name
                    """
                ),
                {"name": name},
            ).scalar_one_or_none()
        )


def _seed_pre_0004_rows(engine: Engine) -> None:
    cid = concept_id(_NS, "Assets")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO source.issuer (cik, name) VALUES ('0000000001', 'Pre0004')"))
        filing_id = conn.execute(
            text(
                """
                INSERT INTO source.filing
                  (issuer_cik, accession, form, filing_date, primary_document)
                VALUES
                  ('0000000001', '0000000001-00-000004', '10-K', :filing_date, 'a.xml')
                RETURNING id
                """
            ),
            {"filing_date": date(2024, 1, 1)},
        ).scalar_one()
        report_id = conn.execute(
            text(
                """
                INSERT INTO source.xbrl_report (
                  filing_id, report_key, report_input, extractor_version,
                  arelle_version, extracted_at, arelle_item_fact_count
                )
                VALUES (
                  :filing_id, :report_key, CAST(:report_input AS jsonb),
                  'source-extract-v3', '2.43.1', :extracted_at, 0
                )
                RETURNING id
                """
            ),
            {
                "filing_id": filing_id,
                "report_key": "a" * 64,
                "report_input": '{"kind":"instance","document_uris":["https://example.com/a.xml"]}',
                "extracted_at": datetime(2024, 1, 2, tzinfo=UTC),
            },
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO source.concept (id, namespace_uri, local_name)
                VALUES (:id, :ns, 'Assets')
                """
            ),
            {"id": cid, "ns": _NS},
        )
        conn.execute(
            text(
                """
                INSERT INTO source.relationship (
                  report_id, source_order, network_type, link_role_uri, arcrole_uri,
                  source_concept_id, target_concept_id
                )
                VALUES (
                  :report_id, 0, 'presentation', :role,
                  'http://www.xbrl.org/2003/arcrole/parent-child', :cid, :cid
                )
                """
            ),
            {"report_id": report_id, "role": _MARKER_ROLE, "cid": cid},
        )
        conn.execute(
            text(
                """
                INSERT INTO source.concept_label (
                  report_id, concept_id, link_role_uri, arcrole_uri, text, source_order
                )
                VALUES (:report_id, :cid, :role,
                        'http://www.xbrl.org/2003/arcrole/concept-label', :text, 0)
                """
            ),
            {"report_id": report_id, "cid": cid, "role": _MARKER_ROLE, "text": _MARKER_TEXT},
        )
        conn.execute(
            text(
                """
                INSERT INTO source.concept_reference (
                  report_id, concept_id, link_role_uri, arcrole_uri, source_order
                )
                VALUES (:report_id, :cid, :role,
                        'http://www.xbrl.org/2003/arcrole/concept-reference', 0)
                """
            ),
            {"report_id": report_id, "cid": cid, "role": _MARKER_ROLE},
        )


def test_0004_upgrade_preserves_pre_0004_rows_and_downgrades(engine: Engine) -> None:
    url = test_database_url()
    cfg = alembic_config(url)

    command.downgrade(cfg, "0003_m1a_extraction_receipt")
    assert _revision(engine) == "0003_m1a_extraction_receipt"
    for table, check_name in _TABLES:
        assert not _column_exists(engine, table, "link_qname")
        assert not _column_exists(engine, table, "arc_qname")
        assert not _check_exists(engine, check_name)

    _seed_pre_0004_rows(engine)

    command.upgrade(cfg, "0004_m1a_network_identity")
    assert _revision(engine) == "0004_m1a_network_identity"
    for table, check_name in _TABLES:
        assert _column_exists(engine, table, "link_qname")
        assert _column_exists(engine, table, "arc_qname")
        assert _check_exists(engine, check_name)

    with engine.connect() as conn:
        rel = conn.execute(
            text(
                """
                SELECT link_role_uri, link_qname, arc_qname
                FROM source.relationship WHERE source_order = 0
                """
            )
        ).one()
        label = conn.execute(
            text(
                """
                SELECT text, link_qname, arc_qname
                FROM source.concept_label WHERE source_order = 0
                """
            )
        ).one()
        ref = conn.execute(
            text(
                """
                SELECT link_role_uri, link_qname, arc_qname
                FROM source.concept_reference WHERE source_order = 0
                """
            )
        ).one()
    assert rel[0] == _MARKER_ROLE
    assert rel[1] is None and rel[2] is None
    assert label[0] == _MARKER_TEXT
    assert label[1] is None and label[2] is None
    assert ref[0] == _MARKER_ROLE
    assert ref[1] is None and ref[2] is None

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE source.relationship
                SET link_qname = '{http://www.xbrl.org/2003/linkbase}presentationLink',
                    arc_qname = '{http://www.xbrl.org/2003/linkbase}presentationArc'
                WHERE source_order = 0
                """
            )
        )

    command.downgrade(cfg, "0003_m1a_extraction_receipt")
    assert _revision(engine) == "0003_m1a_extraction_receipt"
    for table, check_name in _TABLES:
        assert not _column_exists(engine, table, "link_qname")
        assert not _column_exists(engine, table, "arc_qname")
        assert not _check_exists(engine, check_name)
    with engine.connect() as conn:
        remaining_role = conn.execute(
            text("SELECT link_role_uri FROM source.relationship WHERE source_order = 0")
        ).scalar_one()
        remaining_text = conn.execute(
            text("SELECT text FROM source.concept_label WHERE source_order = 0")
        ).scalar_one()
        remaining_ref = conn.execute(
            text("SELECT link_role_uri FROM source.concept_reference WHERE source_order = 0")
        ).scalar_one()
    assert remaining_role == _MARKER_ROLE
    assert remaining_text == _MARKER_TEXT
    assert remaining_ref == _MARKER_ROLE

    command.upgrade(cfg, "head")


@pytest.mark.parametrize("table,check_name", _TABLES)
@pytest.mark.parametrize(
    "link_qname,arc_qname",
    [
        ("{http://www.xbrl.org/2003/linkbase}presentationLink", None),
        (None, "{http://www.xbrl.org/2003/linkbase}presentationArc"),
        ("", "{http://www.xbrl.org/2003/linkbase}presentationArc"),
        ("{http://www.xbrl.org/2003/linkbase}presentationLink", ""),
    ],
)
def test_0004_check_rejects_half_key_and_empty_string(
    engine: Engine,
    table: str,
    check_name: str,
    link_qname: str | None,
    arc_qname: str | None,
) -> None:
    url = test_database_url()
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    assert _check_exists(engine, check_name)

    cid = concept_id(_NS, f"Check{table}")
    with engine.begin() as conn:
        truncate_all_tables(conn)
        conn.execute(text("INSERT INTO source.issuer (cik, name) VALUES ('0000000002', 'Check')"))
        filing_id = conn.execute(
            text(
                """
                INSERT INTO source.filing
                  (issuer_cik, accession, form, filing_date, primary_document)
                VALUES
                  ('0000000002', '0000000002-00-000004', '10-K', DATE '2024-01-01', 'a.xml')
                RETURNING id
                """
            )
        ).scalar_one()
        report_id = conn.execute(
            text(
                """
                INSERT INTO source.xbrl_report (
                  filing_id, report_key, report_input, extractor_version,
                  arelle_version, extracted_at, arelle_item_fact_count
                )
                VALUES (
                  :filing_id, :report_key, '{}'::jsonb, 'source-extract-v4',
                  '2.43.1', :extracted_at, 0
                )
                RETURNING id
                """
            ),
            {
                "filing_id": filing_id,
                "report_key": "b" * 64,
                "extracted_at": datetime(2024, 1, 2, tzinfo=UTC),
            },
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO source.concept (id, namespace_uri, local_name) "
                "VALUES (:id, :ns, :local)"
            ),
            {"id": cid, "ns": _NS, "local": f"Check{table}"},
        )

    insert_sql = {
        "relationship": """
            INSERT INTO source.relationship (
              report_id, source_order, network_type, link_role_uri, arcrole_uri,
              source_concept_id, target_concept_id, link_qname, arc_qname
            ) VALUES (
              :report_id, 0, 'presentation', 'http://example.com/role',
              'http://www.xbrl.org/2003/arcrole/parent-child', :cid, :cid,
              :link_qname, :arc_qname
            )
        """,
        "concept_label": """
            INSERT INTO source.concept_label (
              report_id, concept_id, link_role_uri, arcrole_uri, text, source_order,
              link_qname, arc_qname
            ) VALUES (
              :report_id, :cid, 'http://example.com/role',
              'http://www.xbrl.org/2003/arcrole/concept-label', 'x', 0,
              :link_qname, :arc_qname
            )
        """,
        "concept_reference": """
            INSERT INTO source.concept_reference (
              report_id, concept_id, link_role_uri, arcrole_uri, source_order,
              link_qname, arc_qname
            ) VALUES (
              :report_id, :cid, 'http://example.com/role',
              'http://www.xbrl.org/2003/arcrole/concept-reference', 0,
              :link_qname, :arc_qname
            )
        """,
    }
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(insert_sql[table]),
            {
                "report_id": report_id,
                "cid": cid,
                "link_qname": link_qname,
                "arc_qname": arc_qname,
            },
        )
