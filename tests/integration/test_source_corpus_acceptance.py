"""Integration tests for source.* corpus acceptance snapshot helpers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine

from edgar.corpus_acceptance import lookup_source_filing_id, source_canonical_snapshot
from edgar.db.source import catalog_source_filing, persist_extraction
from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.objects import ObjectStore
from edgar.xbrl.records import ExpandedQName
from edgar.xbrl.source_records import (
    ConceptDeclarationRecord,
    ConceptRecord,
    ContextRecord,
    DocumentBlockRecord,
    FactRecord,
    FilingExtraction,
    FilingSectionRecord,
    RelationshipRecord,
    ReportExtraction,
    UnitMeasureRecord,
    UnitRecord,
)
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables

pytestmark = pytest.mark.database

_NS = "http://example.com/ns"
_DOC_PATH = "accession/a.htm"


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


def _bundle(data_root: Path) -> FilingBundle:
    store = ObjectStore(data_root)
    obj = store.put_bytes(b"hello-world")
    artifacts = (
        BundleArtifact(
            logical_path=_DOC_PATH,
            content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
    )
    uri = "https://example.com/a.htm"
    return FilingBundle(
        filing=FilingIdentity(
            cik="0001065088",
            accession="0001065088-24-000036",
            form_type="10-K",
            filing_date=date(2024, 2, 28),
            accepted_at=None,
            report_period_end=date(2023, 12, 31),
            primary_document="a.htm",
        ),
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(InstanceReportInput(document_uris=(uri,)),),
        uri_bindings=(
            UriBinding(
                document_uri=uri,
                artifact_path=_DOC_PATH,
                content_sha256=obj.sha256,
                replay_aliases=(),
            ),
        ),
    )


def _extraction() -> FilingExtraction:
    concept = ExpandedQName(namespace_uri=_NS, local_name="Revenue")
    return FilingExtraction(
        reports=(
            ReportExtraction(
                report_input={"kind": "instance", "document_uris": ["https://example.com/a.htm"]},
                report_key="a" * 64,
                extractor_version="source-extract-v1",
                arelle_version="2.43.1",
                arelle_item_fact_count=1,
                concepts=(ConceptRecord(namespace_uri=_NS, local_name="Revenue"),),
                declarations=(ConceptDeclarationRecord(concept=concept, period_type="duration"),),
                contexts=(
                    ContextRecord(
                        source_context_id="c1",
                        entity_scheme="http://www.sec.gov/CIK",
                        entity_identifier="0001065088",
                        period_kind="duration",
                        period_start="2023-01-01",
                        period_end="2023-12-31",
                    ),
                ),
                units=(UnitRecord(source_unit_id="u1"),),
                measures=(
                    UnitMeasureRecord(
                        source_unit_id="u1",
                        side="numerator",
                        ordinal=1,
                        measure=ExpandedQName(
                            namespace_uri="http://www.xbrl.org/2003/iso4217",
                            local_name="USD",
                        ),
                    ),
                ),
                facts=(
                    FactRecord(
                        source_order=0,
                        concept=concept,
                        source_context_id="c1",
                        value_status="valid",
                        source_unit_id="u1",
                        raw_lexical_value="100",
                        resolved_value_kind="numeric",
                        resolved_numeric=Decimal("100"),
                        source_document_relative_path=_DOC_PATH,
                    ),
                ),
                relationships=(
                    RelationshipRecord(
                        source_order=0,
                        network_type="presentation",
                        link_role_uri="http://example.com/role/Income",
                        arcrole_uri="http://www.xbrl.org/2003/arcrole/parent-child",
                        source_concept=concept,
                        target_concept=concept,
                    ),
                ),
            ),
        ),
        document_blocks=(
            DocumentBlockRecord(
                document_relative_path=_DOC_PATH,
                ordinal=0,
                block_type="heading",
                text="Item 1",
                heading_level=2,
                source_locator={"scheme": "html-xpath-v1", "value": "/html/body/h2[1]"},
                parser_version="document-html-v2",
            ),
            DocumentBlockRecord(
                document_relative_path=_DOC_PATH,
                ordinal=1,
                block_type="paragraph",
                text="Body",
                parent_ordinal=0,
                source_locator={"scheme": "html-xpath-v1", "value": "/html/body/p[1]"},
                parser_version="document-html-v2",
            ),
        ),
        filing_sections=(
            FilingSectionRecord(
                document_relative_path=_DOC_PATH,
                section_key="item1",
                start_block_ordinal=0,
                end_block_ordinal_exclusive=2,
                method="sec-item-sequence-v3",
                confidence_score=90,
            ),
        ),
        issues=(),
    )


def test_source_canonical_snapshot_counts(engine: Engine, tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=_extraction())

    with engine.connect() as conn:
        filing_id = lookup_source_filing_id(conn, bundle.filing.accession)
        assert filing_id == catalog.filing_id
        snapshot = source_canonical_snapshot(conn, filing_id)

    assert snapshot.catalog.document_count == 1
    assert snapshot.catalog.report_count == 1
    assert snapshot.extraction.concept_declaration_count == 1
    assert snapshot.extraction.context_count == 1
    assert snapshot.extraction.unit_count == 1
    assert snapshot.extraction.unit_measure_count == 1
    assert snapshot.extraction.fact_count == 1
    assert snapshot.extraction.relationship_count == 1
    assert snapshot.extraction.block_count == 2
    assert snapshot.extraction.section_count == 1
