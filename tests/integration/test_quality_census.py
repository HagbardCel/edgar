"""P2.6 census counts a concept only when an undimensioned fact exists."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import Connection

from edgar.db import source_schema as src
from edgar.domain.concept_id import concept_id
from edgar.financials.census import qname_census
from edgar.financials.source_load import load_quality_filing_source
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables

pytestmark = pytest.mark.database

_NS = "http://fasb.org/us-gaap/2024"
_FOO = "Foo"
_ACC_A = "0000000001-24-000001"
_ACC_B = "0000000002-24-000001"
_ACC_C = "0000000003-24-000001"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = test_database_url()
    eng = create_engine(url, future=True)
    reset_test_database(eng, database_url=url)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def truncate_tables(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        truncate_all_tables(conn)
    yield


def _insert_filing(conn: Connection, accession: str, report_key: str) -> int:
    cik = accession.split("-", 1)[0]
    conn.execute(src.source_issuer.insert().values(cik=cik, name=cik))
    filing_id = conn.execute(
        src.source_filing.insert()
        .values(
            issuer_cik=cik,
            accession=accession,
            form="10-K",
            filing_date=date(2024, 2, 1),
            report_period_end=date(2023, 12, 31),
            primary_document="a.htm",
        )
        .returning(src.source_filing.c.id)
    ).scalar_one()
    return conn.execute(
        src.source_xbrl_report.insert()
        .values(
            filing_id=filing_id,
            report_key=report_key,
            report_input={"kind": "instance", "document_uris": ["https://example.com/a.htm"]},
            extractor_version="test",
            arelle_version="test",
            extracted_at=datetime(2024, 2, 1, tzinfo=UTC),
            arelle_item_fact_count=0,
        )
        .returning(src.source_xbrl_report.c.id)
    ).scalar_one()


def _context(conn: Connection, report_id: int, source_id: str, cik: str) -> int:
    return conn.execute(
        src.source_context.insert()
        .values(
            report_id=report_id,
            source_context_id=source_id,
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier=cik,
            period_kind="instant",
            instant_lexical="2023-12-31",
        )
        .returning(src.source_context.c.id)
    ).scalar_one()


def _fact(conn: Connection, report_id: int, context_id: int, concept: object, order: int) -> None:
    conn.execute(
        src.source_fact.insert().values(
            report_id=report_id,
            source_order=order,
            concept_id=concept,
            context_id=context_id,
            value_status="valid",
            is_nil=False,
        )
    )


def test_census_keeps_only_undimensioned_concept_usages(engine: Engine) -> None:
    foo = concept_id(_NS, _FOO)
    axis = concept_id(_NS, "FooAxis")
    member = concept_id(_NS, "FooMember")
    with engine.begin() as conn:
        for concept, local in ((foo, _FOO), (axis, "FooAxis"), (member, "FooMember")):
            conn.execute(
                src.source_concept.insert().values(
                    id=concept,
                    namespace_uri=_NS,
                    local_name=local,
                )
            )
        report_a = _insert_filing(conn, _ACC_A, "a" * 64)
        report_b = _insert_filing(conn, _ACC_B, "b" * 64)
        report_c = _insert_filing(conn, _ACC_C, "c" * 64)
        for report_id in (report_a, report_b, report_c):
            conn.execute(
                src.source_concept_declaration.insert().values(
                    report_id=report_id,
                    concept_id=foo,
                    period_type="instant",
                )
            )
        dim_a = _context(conn, report_a, "dim", "0000000001")
        undim_b = _context(conn, report_b, "undim", "0000000002")
        dim_c = _context(conn, report_c, "dim", "0000000003")
        undim_c = _context(conn, report_c, "undim", "0000000003")
        for context_id in (dim_a, dim_c):
            conn.execute(
                src.source_context_dimension.insert().values(
                    context_id=context_id,
                    dimension_concept_id=axis,
                    context_element="segment",
                    member_kind="explicit",
                    explicit_member_concept_id=member,
                )
            )
        _fact(conn, report_a, dim_a, foo, 0)
        _fact(conn, report_b, undim_b, foo, 0)
        _fact(conn, report_c, dim_c, foo, 0)
        _fact(conn, report_c, undim_c, foo, 1)

        present = {
            accession: {
                (namespace, local)
                for namespace, local in (
                    load_quality_filing_source(conn, accession).fact_concepts  # type: ignore[union-attr]
                )
            }
            for accession in (_ACC_A, _ACC_B, _ACC_C)
        }
    assert present[_ACC_A] == set()
    assert present[_ACC_B] == {(_NS, _FOO)}
    assert present[_ACC_C] == {(_NS, _FOO)}
    census = qname_census(
        (accession, _NS, _FOO) for accession, concepts in present.items() if concepts
    )
    assert census == ({"qname": f"{{{_NS}}}{_FOO}", "n_accessions": 2},)
