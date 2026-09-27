"""Document-qualified fact locator multiset parity (M1A-3)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select

from edgar.db import source_schema as src
from edgar.db.source import catalog_source_filing, persist_extraction
from edgar.domain.report_key import report_key as compute_report_key
from edgar.xbrl.source_records import (
    ConceptDeclarationRecord,
    ConceptRecord,
    ContextRecord,
    ElementLocator,
    FactRecord,
    FilingExtraction,
    ReportExtraction,
)
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables
from tests.helpers.extraction_receipt import wrap_filing_extraction
from tests.integration.test_source_persist import _DOC_PATH, _make_bundle, _qname

_REPORT_INPUT = {"kind": "instance", "document_uris": ["https://example.com/a.htm"]}

pytestmark = pytest.mark.database


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


def test_persisted_locator_multiset_matches_sql(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path, path=_DOC_PATH)
    concept = ConceptRecord(namespace_uri="http://example.com/ns", local_name="Revenue")
    report = ReportExtraction(
        report_input=dict(_REPORT_INPUT),
        report_key=compute_report_key(_REPORT_INPUT),
        extractor_version="source-extract-v1",
        arelle_version="2.43.1",
        arelle_item_fact_count=2,
        concepts=(concept,),
        declarations=(ConceptDeclarationRecord(concept=_qname("Revenue"), period_type="duration"),),
        contexts=(
            ContextRecord(
                source_context_id="c1",
                entity_scheme="http://www.sec.gov/CIK",
                entity_identifier="1",
                period_kind="instant",
                period_instant="2024-12-31",
            ),
        ),
        facts=(
            FactRecord(
                source_order=0,
                concept=_qname("Revenue"),
                source_context_id="c1",
                value_status="valid",
                raw_lexical_value="1",
                resolved_value_kind="numeric",
                resolved_numeric=Decimal("1"),
                source_document_relative_path=_DOC_PATH,
                source_locator=ElementLocator(scheme="xml_id", value="f1"),
            ),
            FactRecord(
                source_order=1,
                concept=_qname("Revenue"),
                source_context_id="c1",
                value_status="valid",
                raw_lexical_value="2",
                resolved_value_kind="numeric",
                resolved_numeric=Decimal("2"),
                source_document_relative_path=_DOC_PATH,
                source_locator=ElementLocator(
                    scheme="expanded_element_path",
                    value="/xbrl/fact[2]",
                ),
            ),
        ),
    )
    extraction = FilingExtraction(reports=(report,))
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(
            conn,
            filing_id=catalog.filing_id,
            extraction=wrap_filing_extraction(extraction, bundle=bundle),
        )
        sql_rows = conn.execute(
            select(
                src.source_document.c.relative_path,
                src.source_fact.c.source_locator,
            )
            .select_from(src.source_fact)
            .join(
                src.source_document,
                src.source_fact.c.source_document_id == src.source_document.c.id,
            )
            .order_by(src.source_fact.c.source_order)
        ).all()

    dto_counter = Counter(
        (
            fact.source_document_relative_path,
            fact.source_locator.scheme if fact.source_locator else "",
            fact.source_locator.value if fact.source_locator else "",
        )
        for fact in report.facts
    )
    sql_counter = Counter(
        (
            row.relative_path,
            row.source_locator["scheme"],
            row.source_locator["value"],
        )
        for row in sql_rows
    )
    assert dto_counter == sql_counter
