"""Seed source rows at Alembic revision 0004 for migration/preflight tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Connection, text

from edgar.domain.concept_id import concept_id

_NS = "http://example.com/mig0005"
_ASSETS = concept_id(_NS, "Assets")
_LIAB = concept_id(_NS, "Liabilities")


def seed_two_reports(conn: Connection) -> dict[str, int]:
    """Two xbrl_report rows on one filing with context/unit/declarations on report A."""
    conn.execute(text("INSERT INTO source.issuer (cik, name) VALUES ('0000000099', 'Mig0005')"))
    filing_id = conn.execute(
        text(
            """
            INSERT INTO source.filing
              (issuer_cik, accession, form, filing_date, primary_document)
            VALUES ('0000000099', '0000000099-00-000005', '10-K', :fd, 'a.xml')
            RETURNING id
            """
        ),
        {"fd": date(2024, 1, 1)},
    ).scalar_one()
    report_a = conn.execute(
        text(
            """
            INSERT INTO source.xbrl_report (
              filing_id, report_key, report_input, extractor_version,
              arelle_version, extracted_at, arelle_item_fact_count
            )
            VALUES (
              :filing_id, :rk_a, CAST(:ri AS jsonb),
              'source-extract-v3', '2.43.1', :at, 0
            )
            RETURNING id
            """
        ),
        {
            "filing_id": filing_id,
            "rk_a": "a" * 64,
            "ri": '{"kind":"instance","document_uris":["https://example.com/a.xml"]}',
            "at": datetime(2024, 1, 2, tzinfo=UTC),
        },
    ).scalar_one()
    report_b = conn.execute(
        text(
            """
            INSERT INTO source.xbrl_report (
              filing_id, report_key, report_input, extractor_version,
              arelle_version, extracted_at, arelle_item_fact_count
            )
            VALUES (
              :filing_id, :rk_b, CAST(:ri AS jsonb),
              'source-extract-v3', '2.43.1', :at, 0
            )
            RETURNING id
            """
        ),
        {
            "filing_id": filing_id,
            "rk_b": "b" * 64,
            "ri": '{"kind":"instance","document_uris":["https://example.com/b.xml"]}',
            "at": datetime(2024, 1, 2, tzinfo=UTC),
        },
    ).scalar_one()
    for cid in (_ASSETS, _LIAB):
        conn.execute(
            text(
                """
                INSERT INTO source.concept (id, namespace_uri, local_name)
                VALUES (:id, :ns, :ln)
                ON CONFLICT DO NOTHING
                """
            ),
            {"id": cid, "ns": _NS, "ln": "Assets" if cid == _ASSETS else "Liabilities"},
        )
    conn.execute(
        text(
            """
            INSERT INTO source.concept_declaration (report_id, concept_id, period_type)
            VALUES (:report_a, :cid, 'instant')
            """
        ),
        {"report_a": report_a, "cid": _ASSETS},
    )
    conn.execute(
        text(
            """
            INSERT INTO source.concept_declaration (report_id, concept_id, period_type)
            VALUES (:report_a, :cid, 'instant')
            """
        ),
        {"report_a": report_a, "cid": _LIAB},
    )
    ctx_a = conn.execute(
        text(
            """
            INSERT INTO source.context (
              report_id, source_context_id, entity_scheme, entity_identifier,
              period_kind, instant_lexical
            )
            VALUES (:report_a, 'c1', 'http://www.sec.gov/CIK', '1', 'instant', '2024-12-31')
            RETURNING id
            """
        ),
        {"report_a": report_a},
    ).scalar_one()
    unit_a = conn.execute(
        text(
            """
            INSERT INTO source.unit (report_id, source_unit_id)
            VALUES (:report_a, 'u1')
            RETURNING id
            """
        ),
        {"report_a": report_a},
    ).scalar_one()
    conn.execute(
        text(
            """
            INSERT INTO source.fact (
              report_id, source_order, concept_id, context_id, value_status,
              raw_lexical_value, is_nil
            )
            VALUES (:report_a, 0, :cid, :ctx, 'valid', '100', false)
            """
        ),
        {"report_a": report_a, "cid": _ASSETS, "ctx": ctx_a},
    )
    return {
        "filing_id": int(filing_id),
        "report_a": int(report_a),
        "report_b": int(report_b),
        "context_a": int(ctx_a),
        "unit_a": int(unit_a),
        "assets_id": _ASSETS,
        "liab_id": _LIAB,
    }


def insert_cross_report_fact_context(conn: Connection, ids: dict[str, int]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO source.concept_declaration (report_id, concept_id, period_type)
            VALUES (:report_b, :cid, 'instant')
            """
        ),
        {"report_b": ids["report_b"], "cid": ids["assets_id"]},
    )
    conn.execute(
        text(
            """
            INSERT INTO source.fact (
              report_id, source_order, concept_id, context_id, value_status,
              raw_lexical_value, is_nil
            )
            VALUES (:report_b, 0, :cid, :context_a, 'valid', '1', false)
            """
        ),
        {"report_b": ids["report_b"], "cid": ids["assets_id"], "context_a": ids["context_a"]},
    )


def insert_cross_report_fact_unit(conn: Connection, ids: dict[str, int]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO source.concept_declaration (report_id, concept_id, period_type)
            VALUES (:report_b, :cid, 'instant')
            """
        ),
        {"report_b": ids["report_b"], "cid": ids["assets_id"]},
    )
    ctx_b = conn.execute(
        text(
            """
            INSERT INTO source.context (
              report_id, source_context_id, entity_scheme, entity_identifier,
              period_kind, instant_lexical
            )
            VALUES (:report_b, 'c1', 'http://www.sec.gov/CIK', '1', 'instant', '2024-12-31')
            RETURNING id
            """
        ),
        {"report_b": ids["report_b"]},
    ).scalar_one()
    conn.execute(
        text(
            """
            INSERT INTO source.fact (
              report_id, source_order, concept_id, context_id, unit_id, value_status,
              raw_lexical_value, is_nil
            )
            VALUES (:report_b, 0, :cid, :ctx_b, :unit_a, 'valid', '1', false)
            """
        ),
        {
            "report_b": ids["report_b"],
            "cid": ids["assets_id"],
            "ctx_b": ctx_b,
            "unit_a": ids["unit_a"],
        },
    )


def insert_cross_report_fact_declaration(conn: Connection, ids: dict[str, int]) -> None:
    ctx_b = conn.execute(
        text(
            """
            INSERT INTO source.context (
              report_id, source_context_id, entity_scheme, entity_identifier,
              period_kind, instant_lexical
            )
            VALUES (:report_b, 'c1', 'http://www.sec.gov/CIK', '1', 'instant', '2024-12-31')
            RETURNING id
            """
        ),
        {"report_b": ids["report_b"]},
    ).scalar_one()
    conn.execute(
        text(
            """
            INSERT INTO source.fact (
              report_id, source_order, concept_id, context_id, value_status,
              raw_lexical_value, is_nil
            )
            VALUES (:report_b, 0, :cid, :ctx_b, 'valid', '1', false)
            """
        ),
        {"report_b": ids["report_b"], "cid": ids["assets_id"], "ctx_b": ctx_b},
    )


def insert_cross_report_label(conn: Connection, ids: dict[str, int]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO source.concept_label (
              report_id, concept_id, link_role_uri, arcrole_uri, text, source_order
            )
            VALUES (
              :report_b, :cid, 'http://example.com/role', 'http://www.xbrl.org/2003/arcrole/concept-label',
              'label', 0
            )
            """
        ),
        {"report_b": ids["report_b"], "cid": ids["assets_id"]},
    )


def insert_cross_report_reference(conn: Connection, ids: dict[str, int]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO source.concept_reference (
              report_id, concept_id, link_role_uri, arcrole_uri, source_order
            )
            VALUES (
              :report_b, :cid, 'http://example.com/role', 'http://www.xbrl.org/2003/arcrole/concept-reference',
              0
            )
            """
        ),
        {"report_b": ids["report_b"], "cid": ids["assets_id"]},
    )


def insert_cross_report_relationship_source(conn: Connection, ids: dict[str, int]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO source.concept_declaration (report_id, concept_id, period_type)
            VALUES (:report_b, :cid, 'instant')
            """
        ),
        {"report_b": ids["report_b"], "cid": ids["liab_id"]},
    )
    conn.execute(
        text(
            """
            INSERT INTO source.relationship (
              report_id, source_order, network_type, link_role_uri, arcrole_uri,
              source_concept_id, target_concept_id
            )
            VALUES (
              :report_b, 0, 'presentation', 'http://example.com/role',
              'http://www.xbrl.org/2003/arcrole/parent-child', :src, :tgt
            )
            """
        ),
        {"report_b": ids["report_b"], "src": ids["assets_id"], "tgt": ids["liab_id"]},
    )


def insert_cross_report_relationship_target(conn: Connection, ids: dict[str, int]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO source.concept_declaration (report_id, concept_id, period_type)
            VALUES (:report_b, :cid, 'instant')
            """
        ),
        {"report_b": ids["report_b"], "cid": ids["assets_id"]},
    )
    conn.execute(
        text(
            """
            INSERT INTO source.relationship (
              report_id, source_order, network_type, link_role_uri, arcrole_uri,
              source_concept_id, target_concept_id
            )
            VALUES (
              :report_b, 1, 'presentation', 'http://example.com/role',
              'http://www.xbrl.org/2003/arcrole/parent-child', :src, :tgt
            )
            """
        ),
        {"report_b": ids["report_b"], "src": ids["assets_id"], "tgt": ids["liab_id"]},
    )
