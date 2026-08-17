"""PostgreSQL integration tests for Phase 2B ``persist_extraction``."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, func, select

from edgar.db import source_schema as src
from edgar.db.source import (
    PersistExtractionError,
    SourceCatalogConflict,
    catalog_source_filing,
    persist_extraction,
)
from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.domain.concept_id import concept_id
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.objects import ObjectStore
from edgar.xbrl.records import ExpandedQName
from edgar.xbrl.source_records import (
    ConceptDeclarationRecord,
    ConceptLabelRecord,
    ConceptRecord,
    ContextDimensionRecord,
    ContextRecord,
    DocumentBlockRecord,
    ElementLocator,
    ExtractionIssueRecord,
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


def _make_bundle(
    data_root: Path,
    *,
    payload: bytes = b"hello-world",
    path: str = _DOC_PATH,
) -> FilingBundle:
    store = ObjectStore(data_root)
    obj = store.put_bytes(payload)
    artifacts = (
        BundleArtifact(
            logical_path=path,
            content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
    )
    uri = "https://example.com/a.htm"
    bindings = (
        UriBinding(
            document_uri=uri,
            artifact_path=path,
            content_sha256=obj.sha256,
            replay_aliases=(),
        ),
    )
    filing = FilingIdentity(
        cik="0001065088",
        accession="0001065088-24-000036",
        form_type="10-K",
        filing_date=date(2024, 2, 28),
        accepted_at=None,
        report_period_end=date(2023, 12, 31),
        primary_document="a.htm",
    )
    return FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(InstanceReportInput(document_uris=(uri,)),),
        uri_bindings=bindings,
    )


def _qname(local: str) -> ExpandedQName:
    return ExpandedQName(namespace_uri=_NS, local_name=local)


def _minimal_report(
    *,
    report_key: str,
    concepts: tuple[ConceptRecord, ...],
    facts: tuple[FactRecord, ...],
    issues: tuple[ExtractionIssueRecord, ...] = (),
    arelle_item_fact_count: int | None = None,
) -> ReportExtraction:
    contexts = (
        ContextRecord(
            source_context_id="c1",
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0001065088",
            period_kind="instant",
            period_instant="2023-12-31",
        ),
    )
    units = (UnitRecord(source_unit_id="u1"),)
    measures = (
        UnitMeasureRecord(
            source_unit_id="u1",
            side="numerator",
            ordinal=1,
            measure=ExpandedQName(
                namespace_uri="http://www.xbrl.org/2003/iso4217",
                local_name="USD",
            ),
        ),
    )
    return ReportExtraction(
        report_input={"kind": "instance", "document_uris": ["https://example.com/a.htm"]},
        report_key=report_key,
        extractor_version="source-extract-v1",
        arelle_version="2.43.1",
        arelle_item_fact_count=(
            len(facts) if arelle_item_fact_count is None else arelle_item_fact_count
        ),
        concepts=concepts,
        contexts=contexts,
        units=units,
        measures=measures,
        facts=facts,
        issues=issues,
    )


def _fact(
    *,
    source_order: int,
    local: str,
    value: str,
    numeric: Decimal,
) -> FactRecord:
    return FactRecord(
        source_order=source_order,
        concept=_qname(local),
        source_context_id="c1",
        value_status="valid",
        source_unit_id="u1",
        raw_lexical_value=value,
        resolved_value_kind="numeric",
        resolved_numeric=numeric,
        source_document_relative_path=_DOC_PATH,
    )


def _extraction_a() -> FilingExtraction:
    concepts = (ConceptRecord(namespace_uri=_NS, local_name="Revenue"),)
    facts = (_fact(source_order=0, local="Revenue", value="100", numeric=Decimal("100")),)
    issues = (
        ExtractionIssueRecord(
            component="xbrl",
            code="ISSUE_A",
            severity="warning",
            message="issue from extraction A",
        ),
    )
    blocks = (
        DocumentBlockRecord(
            document_relative_path=_DOC_PATH,
            ordinal=0,
            block_type="heading",
            text="Item 1. Business",
            heading_level=2,
            source_locator={"scheme": "html-xpath-v1", "value": "/html/body/h2[1]"},
            parser_version="document-html-v2",
        ),
        DocumentBlockRecord(
            document_relative_path=_DOC_PATH,
            ordinal=1,
            block_type="paragraph",
            text="We sell widgets.",
            parent_ordinal=0,
            source_locator={"scheme": "html-xpath-v1", "value": "/html/body/p[1]"},
            parser_version="document-html-v2",
        ),
    )
    sections = (
        FilingSectionRecord(
            document_relative_path=_DOC_PATH,
            section_key="item1",
            start_block_ordinal=0,
            end_block_ordinal_exclusive=2,
            method="sec-item-sequence-v3",
            confidence_score=90,
        ),
    )
    return FilingExtraction(
        reports=(
            _minimal_report(
                report_key="a" * 64,
                concepts=concepts,
                facts=facts,
                issues=issues,
            ),
        ),
        document_blocks=blocks,
        filing_sections=sections,
        issues=(),
    )


def _extraction_b() -> FilingExtraction:
    concepts = (
        ConceptRecord(namespace_uri=_NS, local_name="Revenue"),
        ConceptRecord(namespace_uri=_NS, local_name="Assets"),
    )
    facts = (
        _fact(source_order=0, local="Revenue", value="200", numeric=Decimal("200")),
        _fact(source_order=1, local="Assets", value="300", numeric=Decimal("300")),
    )
    issues = (
        ExtractionIssueRecord(
            component="xbrl",
            code="ISSUE_B",
            severity="info",
            message="issue from extraction B",
        ),
    )
    return FilingExtraction(
        reports=(
            _minimal_report(
                report_key="b" * 64,
                concepts=concepts,
                facts=facts,
                issues=issues,
            ),
        ),
        issues=(
            ExtractionIssueRecord(
                component="filing",
                code="FILING_B",
                severity="warning",
                message="filing-scoped B",
            ),
        ),
    )


def _extraction_without_revenue() -> FilingExtraction:
    concepts = (ConceptRecord(namespace_uri=_NS, local_name="Assets"),)
    facts = (_fact(source_order=0, local="Assets", value="50", numeric=Decimal("50")),)
    return FilingExtraction(
        reports=(
            _minimal_report(
                report_key="c" * 64,
                concepts=concepts,
                facts=facts,
            ),
        ),
    )


def test_persist_replaces_counts_and_reuses_concepts(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=_extraction_a())

    with engine.begin() as conn:
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=_extraction_b())
        fact_count = conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one()
        report_count = conn.execute(
            select(func.count()).select_from(src.source_xbrl_report)
        ).scalar_one()
        issue_codes = {
            row[0] for row in conn.execute(select(src.source_extraction_issue.c.code)).all()
        }
        concept_count = conn.execute(
            select(func.count()).select_from(src.source_concept)
        ).scalar_one()
        revenue_id = concept_id(_NS, "Revenue")
        assets_id = concept_id(_NS, "Assets")
        remaining = {row[0] for row in conn.execute(select(src.source_concept.c.id)).all()}

    assert int(fact_count) == 2
    assert int(report_count) == 1
    assert issue_codes == {"ISSUE_B", "FILING_B"}
    assert int(concept_count) == 2
    assert remaining == {revenue_id, assets_id}


def test_post_delete_rollback_keeps_prior_facts_and_issues(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=_extraction_a())

    incomplete = FilingExtraction(
        reports=(
            _minimal_report(
                report_key="d" * 64,
                concepts=(ConceptRecord(namespace_uri=_NS, local_name="Revenue"),),
                facts=(_fact(source_order=0, local="Revenue", value="9", numeric=Decimal("9")),),
                arelle_item_fact_count=99,
            ),
        ),
    )
    with (
        pytest.raises(PersistExtractionError, match="fact completeness"),
        engine.begin() as conn,
    ):
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=incomplete)

    with engine.connect() as conn:
        facts = conn.execute(
            select(src.source_fact.c.raw_lexical_value, src.source_fact.c.source_order)
        ).all()
        issues = {row[0] for row in conn.execute(select(src.source_extraction_issue.c.code)).all()}
        reports = conn.execute(select(src.source_xbrl_report.c.report_key)).all()

    assert facts == [("100", 0)]
    assert issues == {"ISSUE_A"}
    assert reports == [("a" * 64,)]


def test_concurrent_replacement_ends_as_single_extraction(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        filing_id = catalog.filing_id

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker(extraction: FilingExtraction) -> None:
        try:
            with engine.connect() as conn, conn.begin():
                barrier.wait(timeout=10)
                persist_extraction(conn, filing_id=filing_id, extraction=extraction)
        except BaseException as exc:  # noqa: BLE001 — collect for assertion
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=(_extraction_a(),))
    t2 = threading.Thread(target=worker, args=(_extraction_b(),))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert errors == []

    with engine.connect() as conn:
        report_keys = {
            row[0] for row in conn.execute(select(src.source_xbrl_report.c.report_key)).all()
        }
        fact_count = int(
            conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one()
        )
        issue_codes = {
            row[0] for row in conn.execute(select(src.source_extraction_issue.c.code)).all()
        }

    assert len(report_keys) == 1
    winner = next(iter(report_keys))
    if winner == "a" * 64:
        assert fact_count == 1
        assert issue_codes == {"ISSUE_A"}
    else:
        assert winner == "b" * 64
        assert fact_count == 2
        assert issue_codes == {"ISSUE_B", "FILING_B"}


def test_no_concept_gc_after_reextract_without_qname(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    revenue_id = concept_id(_NS, "Revenue")
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=_extraction_a())
        persist_extraction(
            conn, filing_id=catalog.filing_id, extraction=_extraction_without_revenue()
        )
        remaining = conn.execute(
            select(src.source_concept.c.id).where(src.source_concept.c.id == revenue_id)
        ).scalar_one()
        decl_count = conn.execute(
            select(func.count()).select_from(src.source_concept_declaration)
        ).scalar_one()

    assert remaining == revenue_id
    assert int(decl_count) == 0


def test_stale_issues_absent_after_successful_replacement(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=_extraction_a())
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=_extraction_b())
        codes = {row[0] for row in conn.execute(select(src.source_extraction_issue.c.code)).all()}

    assert "ISSUE_A" not in codes
    assert codes == {"ISSUE_B", "FILING_B"}


def test_hash_conflict_still_rejected_via_catalog(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path, payload=b"original")
    with engine.begin() as conn:
        catalog_source_filing(conn, bundle)

    other = _make_bundle(tmp_path / "b", payload=b"changed-bytes!!")
    conflict = FilingBundle(
        filing=bundle.filing,
        payload_hash=other.payload_hash,
        artifacts=other.artifacts,
        report_inputs=bundle.report_inputs,
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/a.htm",
                artifact_path=other.artifacts[0].logical_path,
                content_sha256=other.artifacts[0].content.sha256,
                replay_aliases=(),
            ),
        ),
    )
    with (
        engine.begin() as conn,
        pytest.raises(SourceCatalogConflict, match="inventory mismatch"),
    ):
        catalog_source_filing(conn, conflict)


def test_blocks_and_sections_persist_with_pr7_fields(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        result = persist_extraction(conn, filing_id=catalog.filing_id, extraction=_extraction_a())
        assert result.block_count == 2
        assert result.section_count == 1
        assert result.fact_count == 1

        blocks = (
            conn.execute(
                select(
                    src.source_document_block.c.ordinal,
                    src.source_document_block.c.parent_ordinal,
                    src.source_document_block.c.heading_level,
                    src.source_document_block.c.block_type,
                    src.source_document_block.c.source_locator,
                    src.source_document_block.c.parser_version,
                ).order_by(src.source_document_block.c.ordinal)
            )
            .mappings()
            .all()
        )
        sections = (
            conn.execute(
                select(
                    src.source_filing_section.c.section_key,
                    src.source_filing_section.c.start_block_ordinal,
                    src.source_filing_section.c.end_block_ordinal_exclusive,
                    src.source_filing_section.c.method,
                    src.source_filing_section.c.confidence_score,
                )
            )
            .mappings()
            .all()
        )

    assert len(blocks) == 2
    assert blocks[0]["ordinal"] == 0
    assert blocks[0]["heading_level"] == 2
    assert blocks[0]["block_type"] == "heading"
    assert blocks[0]["source_locator"] == {
        "scheme": "html-xpath-v1",
        "value": "/html/body/h2[1]",
    }
    assert blocks[0]["parser_version"] == "document-html-v2"
    assert blocks[1]["parent_ordinal"] == 0
    assert sections == [
        {
            "section_key": "item1",
            "start_block_ordinal": 0,
            "end_block_ordinal_exclusive": 2,
            "method": "sec-item-sequence-v3",
            "confidence_score": 90,
        }
    ]


def test_failed_reextract_keeps_prior_blocks(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=_extraction_a())

    incomplete = FilingExtraction(
        reports=(
            _minimal_report(
                report_key="d" * 64,
                concepts=(ConceptRecord(namespace_uri=_NS, local_name="Revenue"),),
                facts=(_fact(source_order=0, local="Revenue", value="9", numeric=Decimal("9")),),
                arelle_item_fact_count=99,
            ),
        ),
        document_blocks=(
            DocumentBlockRecord(
                document_relative_path=_DOC_PATH,
                ordinal=0,
                block_type="paragraph",
                text="replacement",
                source_locator={"scheme": "html-xpath-v1", "value": "/html/body/p"},
                parser_version="document-html-v2",
            ),
        ),
    )
    with (
        pytest.raises(PersistExtractionError, match="fact completeness"),
        engine.begin() as conn,
    ):
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=incomplete)

    with engine.connect() as conn:
        block_texts = [
            row[0]
            for row in conn.execute(
                select(src.source_document_block.c.text).order_by(
                    src.source_document_block.c.ordinal
                )
            ).all()
        ]
        section_keys = {
            row[0] for row in conn.execute(select(src.source_filing_section.c.section_key)).all()
        }
        facts = conn.execute(
            select(src.source_fact.c.raw_lexical_value, src.source_fact.c.source_order)
        ).all()

    assert block_texts == ["Item 1. Business", "We sell widgets."]
    assert section_keys == {"item1"}
    assert facts == [("100", 0)]


def test_persist_explicit_dimension_sql_null_typed_member(engine: Engine, tmp_path: Path) -> None:
    """Explicit dimensions must bind SQL NULL for typed_member (not JSON null)."""
    bundle = _make_bundle(tmp_path)
    axis = ConceptRecord(namespace_uri=_NS, local_name="SegmentAxis")
    member = ConceptRecord(namespace_uri=_NS, local_name="USMember")
    revenue = ConceptRecord(namespace_uri=_NS, local_name="Revenue")
    report = _minimal_report(
        report_key="a" * 64,
        concepts=(revenue, axis, member),
        facts=(_fact(source_order=0, local="Revenue", value="100", numeric=Decimal("100")),),
    )
    report = ReportExtraction(
        report_input=report.report_input,
        report_key=report.report_key,
        extractor_version=report.extractor_version,
        arelle_version=report.arelle_version,
        arelle_item_fact_count=report.arelle_item_fact_count,
        concepts=report.concepts,
        declarations=report.declarations,
        labels=report.labels,
        references=report.references,
        contexts=report.contexts,
        dimensions=(
            ContextDimensionRecord(
                source_context_id="c1",
                dimension=_qname("SegmentAxis"),
                context_element="segment",
                member_kind="explicit",
                member=_qname("USMember"),
                typed_member=None,
            ),
        ),
        units=report.units,
        measures=report.measures,
        facts=report.facts,
        relationships=report.relationships,
        issues=report.issues,
    )
    extraction = FilingExtraction(reports=(report,))
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=extraction)
        row = conn.execute(
            select(
                src.source_context_dimension.c.member_kind,
                src.source_context_dimension.c.explicit_member_concept_id,
                src.source_context_dimension.c.typed_member,
            )
        ).one()
    assert row[0] == "explicit"
    assert row[1] is not None
    assert row[2] is None


def _locator(value: str = "n1") -> ElementLocator:
    return ElementLocator(scheme="xml_id", value=value)


def test_persist_provenance_on_relationship_declaration_context_unit(
    engine: Engine, tmp_path: Path
) -> None:
    bundle = _make_bundle(tmp_path)
    loc = _locator("rel1")
    concepts = (
        ConceptRecord(namespace_uri=_NS, local_name="Revenue"),
        ConceptRecord(namespace_uri=_NS, local_name="Assets"),
    )
    report = _minimal_report(
        report_key="a" * 64,
        concepts=concepts,
        facts=(_fact(source_order=0, local="Revenue", value="100", numeric=Decimal("100")),),
    )
    report = ReportExtraction(
        report_input=report.report_input,
        report_key=report.report_key,
        extractor_version=report.extractor_version,
        arelle_version=report.arelle_version,
        arelle_item_fact_count=report.arelle_item_fact_count,
        concepts=concepts,
        declarations=(
            ConceptDeclarationRecord(
                concept=_qname("Revenue"),
                period_type="duration",
                source_document_relative_path=_DOC_PATH,
                source_locator=_locator("decl1"),
            ),
        ),
        labels=(
            ConceptLabelRecord(
                concept=_qname("Revenue"),
                link_role_uri="http://example.com/role/Statement",
                arcrole_uri="http://www.xbrl.org/2003/arcrole/concept-label",
                text="Revenue",
                source_order=0,
                language="en",
                resource_role_uri="http://www.xbrl.org/2003/role/label",
                source_document_relative_path=_DOC_PATH,
                source_locator=_locator("lab1"),
                arc_document_relative_path=_DOC_PATH,
                arc_locator=_locator("labarc1"),
            ),
        ),
        contexts=(
            ContextRecord(
                source_context_id="c1",
                entity_scheme="http://www.sec.gov/CIK",
                entity_identifier="0001065088",
                period_kind="instant",
                period_instant="2023-12-31",
                source_document_relative_path=_DOC_PATH,
                source_locator=_locator("ctx1"),
            ),
        ),
        units=(
            UnitRecord(
                source_unit_id="u1",
                source_document_relative_path=_DOC_PATH,
                source_locator=_locator("u1"),
            ),
        ),
        measures=report.measures,
        facts=report.facts,
        relationships=(
            RelationshipRecord(
                source_order=0,
                network_type="presentation",
                link_role_uri="http://example.com/role/Income",
                arcrole_uri="http://www.xbrl.org/2003/arcrole/parent-child",
                source_concept=_qname("Revenue"),
                target_concept=_qname("Assets"),
                source_document_relative_path=_DOC_PATH,
                source_locator=loc,
            ),
        ),
    )
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(
            conn, filing_id=catalog.filing_id, extraction=FilingExtraction(reports=(report,))
        )
        doc_id = conn.execute(
            select(src.source_document.c.id).where(src.source_document.c.relative_path == _DOC_PATH)
        ).scalar_one()
        rel = conn.execute(
            select(
                src.source_relationship.c.source_document_id,
                src.source_relationship.c.source_locator,
            )
        ).one()
        decl = conn.execute(
            select(
                src.source_concept_declaration.c.source_document_id,
                src.source_concept_declaration.c.source_locator,
            )
        ).one()
        ctx = conn.execute(
            select(
                src.source_context.c.source_document_id,
                src.source_context.c.source_locator,
                src.source_context.c.instant_lexical,
                src.source_context.c.instant_at,
            )
        ).one()
        unit = conn.execute(
            select(src.source_unit.c.source_document_id, src.source_unit.c.source_locator)
        ).one()
        label = conn.execute(
            select(
                src.source_concept_label.c.link_role_uri,
                src.source_concept_label.c.arcrole_uri,
                src.source_concept_label.c.resource_role_uri,
                src.source_concept_label.c.source_document_id,
                src.source_concept_label.c.arc_source_document_id,
            )
        ).one()
    assert rel[0] == doc_id
    assert rel[1]["scheme"] == "xml_id"
    assert decl[0] == doc_id
    assert decl[1]["value"] == "decl1"
    assert ctx[0] == doc_id
    assert ctx[2] == "2023-12-31"
    assert ctx[3] is None
    assert unit[0] == doc_id
    assert label[0] == "http://example.com/role/Statement"
    assert label[1] == "http://www.xbrl.org/2003/arcrole/concept-label"
    assert label[2] == "http://www.xbrl.org/2003/role/label"
    assert label[3] == doc_id
    assert label[4] == doc_id


def test_persist_missing_document_path_keeps_prior_snapshot(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=_extraction_a())

    bad_report = _minimal_report(
        report_key="e" * 64,
        concepts=(ConceptRecord(namespace_uri=_NS, local_name="Revenue"),),
        facts=(_fact(source_order=0, local="Revenue", value="9", numeric=Decimal("9")),),
    )
    bad_report = ReportExtraction(
        report_input=bad_report.report_input,
        report_key=bad_report.report_key,
        extractor_version=bad_report.extractor_version,
        arelle_version=bad_report.arelle_version,
        arelle_item_fact_count=bad_report.arelle_item_fact_count,
        concepts=bad_report.concepts,
        contexts=bad_report.contexts,
        units=bad_report.units,
        measures=bad_report.measures,
        facts=bad_report.facts,
        relationships=(
            RelationshipRecord(
                source_order=0,
                network_type="presentation",
                link_role_uri="http://example.com/role/Income",
                arcrole_uri="http://www.xbrl.org/2003/arcrole/parent-child",
                source_concept=_qname("Revenue"),
                target_concept=_qname("Revenue"),
                source_document_relative_path="missing.xml",
                source_locator=_locator("missing"),
            ),
        ),
    )
    with (
        pytest.raises(PersistExtractionError, match="not catalogued"),
        engine.begin() as conn,
    ):
        persist_extraction(
            conn,
            filing_id=catalog.filing_id,
            extraction=FilingExtraction(reports=(bad_report,)),
        )

    with engine.connect() as conn:
        facts = conn.execute(
            select(src.source_fact.c.raw_lexical_value, src.source_fact.c.source_order)
        ).all()
        issues = {row[0] for row in conn.execute(select(src.source_extraction_issue.c.code)).all()}
        reports = conn.execute(select(src.source_xbrl_report.c.report_key)).all()
    assert facts == [("100", 0)]
    assert issues == {"ISSUE_A"}
    assert reports == [("a" * 64,)]


def test_persist_datetime_context_lexical_and_offset_aware_at(
    engine: Engine, tmp_path: Path
) -> None:
    bundle = _make_bundle(tmp_path)

    def _report(context_id: str, lexical: str, key: str) -> ReportExtraction:
        base = _minimal_report(
            report_key=key,
            concepts=(ConceptRecord(namespace_uri=_NS, local_name="Revenue"),),
            facts=(_fact(source_order=0, local="Revenue", value="1", numeric=Decimal("1")),),
        )
        return ReportExtraction(
            report_input=base.report_input,
            report_key=base.report_key,
            extractor_version=base.extractor_version,
            arelle_version=base.arelle_version,
            arelle_item_fact_count=base.arelle_item_fact_count,
            concepts=base.concepts,
            contexts=(
                ContextRecord(
                    source_context_id=context_id,
                    entity_scheme="http://www.sec.gov/CIK",
                    entity_identifier="0001065088",
                    period_kind="instant",
                    period_instant=lexical,
                ),
            ),
            units=base.units,
            measures=base.measures,
            facts=(
                FactRecord(
                    source_order=0,
                    concept=_qname("Revenue"),
                    source_context_id=context_id,
                    value_status="valid",
                    source_unit_id="u1",
                    raw_lexical_value="1",
                    resolved_value_kind="numeric",
                    resolved_numeric=Decimal("1"),
                    source_document_relative_path=_DOC_PATH,
                ),
            ),
        )

    cases = (
        ("naive", "2024-06-15T12:30:00", False),
        ("zulu", "2024-06-15T12:30:00Z", True),
        ("offset", "2024-06-15T12:30:00-04:00", True),
        ("dateonly", "2024-12-31", False),
    )
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        filing_id = catalog.filing_id

    for name, lexical, expect_at in cases:
        key = name.encode().hex().ljust(64, "0")
        with engine.begin() as conn:
            persist_extraction(
                conn,
                filing_id=filing_id,
                extraction=FilingExtraction(reports=(_report("c-" + name, lexical, key),)),
            )
            row = conn.execute(
                select(
                    src.source_context.c.instant_lexical,
                    src.source_context.c.instant_at,
                )
            ).one()
        assert row[0] == lexical
        assert row[0] != "2025-01-01"
        if expect_at:
            assert row[1] is not None
            assert row[1].tzinfo is not None
            assert row[1].utcoffset() is not None
        else:
            assert row[1] is None
