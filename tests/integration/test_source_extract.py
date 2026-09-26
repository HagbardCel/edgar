"""Integration: live source extract path writes facts and document blocks."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, func, select

from edgar.config import Settings
from edgar.db import source_schema as src
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
from edgar.ingestion.source_extract import SourceExtractService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from edgar.xbrl.extraction_receipt import RECEIPT_VERSION, ExtractionReceipt
from edgar.xbrl.source_documents import extract_documents_for_filing
from edgar.xbrl.source_extract import extract_filing
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables
from tests.helpers.document_fixtures import RICH_10K_HTML
from tests.helpers.extraction_receipt import wrap_filing_extraction
from tests.helpers.xbrl_bundles import make_minimal_semantic_bundle

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


def _hybrid_html_xbrl_bundle(store: ObjectStore) -> FilingBundle:
    """XBRL instance report plus HTML attachment for document extraction.

    Keeps the minimal semantic bundle's URI bindings intact so offline Arelle
    replay stays faithful. HTML is an attachment artifact only (blocks; no
    regulatory sections — those require primary HTML, covered by unit tests).
    """
    xbrl = make_minimal_semantic_bundle(store)
    html_obj = store.put_bytes(RICH_10K_HTML)
    html_path = "accession/primary.htm"
    artifacts = list(xbrl.artifacts) + [
        BundleArtifact(
            logical_path=html_path,
            content=ContentObject(sha256=html_obj.sha256, byte_size=html_obj.byte_size),
            artifact_kind="attachment",
            required=True,
        )
    ]
    artifact_tuple = tuple(artifacts)
    return FilingBundle(
        filing=xbrl.filing,
        payload_hash=compute_payload_hash(artifact_tuple),
        artifacts=artifact_tuple,
        report_inputs=xbrl.report_inputs,
        uri_bindings=xbrl.uri_bindings,
    )


def test_extract_filing_writes_facts_and_blocks(engine: Engine, tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    bundle = _hybrid_html_xbrl_bundle(store)
    extraction = extract_filing(bundle, store)
    assert extraction.reports
    assert extraction.reports[0].arelle_item_fact_count == len(extraction.reports[0].facts)
    assert extraction.reports[0].arelle_item_fact_count >= 2
    assert extraction.document_blocks
    assert all(
        b.document_relative_path == "accession/primary.htm" for b in extraction.document_blocks
    )
    # Attachment HTML: blocks yes, regulatory sections no (Phase-1 rule).
    assert extraction.filing_sections == ()

    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        result = persist_extraction(
            conn,
            filing_id=catalog.filing_id,
            extraction=wrap_filing_extraction(extraction, bundle=bundle),
        )

    assert result.fact_count >= 2
    assert result.block_count == len(extraction.document_blocks)
    assert result.section_count == 0

    with engine.connect() as conn:
        fact_count = int(
            conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one()
        )
        block_count = int(
            conn.execute(select(func.count()).select_from(src.source_document_block)).scalar_one()
        )
        section_count = int(
            conn.execute(select(func.count()).select_from(src.source_filing_section)).scalar_one()
        )
        locators = [
            row[0] for row in conn.execute(select(src.source_document_block.c.source_locator)).all()
        ]

    assert fact_count == result.fact_count
    assert block_count == result.block_count
    assert section_count == result.section_count
    assert all(loc.get("scheme") == "html-xpath-v1" for loc in locators)


def test_source_extract_service_end_to_end(engine: Engine, tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    bundle = _hybrid_html_xbrl_bundle(store)
    repo = BundleRepository(tmp_path, store)
    published = repo.publish(bundle)
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    service = SourceExtractService(settings, engine=engine, bundles=repo)
    result = service.extract_published_bundle(published.bundle_dir)
    assert result.filing_id > 0
    assert result.persist.fact_count >= 2
    assert result.persist.block_count > 0
    assert result.persist.section_count == 0

    # Idempotent catalog on second extract; replacement still succeeds.
    second = service.extract_published_bundle(published.bundle_dir)
    assert second.catalog_reused is True
    assert second.persist.fact_count == result.persist.fact_count

    with engine.connect() as conn:
        receipt_row = conn.execute(
            select(src.source_xbrl_report.c.extraction_receipt).where(
                src.source_xbrl_report.c.filing_id == result.filing_id
            )
        ).scalar_one()
    assert receipt_row is not None
    receipt = ExtractionReceipt.from_dict(receipt_row)
    assert receipt.receipt_version == RECEIPT_VERSION
    assert receipt.semantic_config


def test_invalid_base_set_qname_leaves_prior_snapshot(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar.ingestion.source_extract import SourceExtractError
    from edgar.xbrl.extract import INVALID_BASE_SET_QNAME
    from edgar.xbrl.records import SemanticIssueRecord
    from edgar.xbrl.replay_normalize import NormalizedReplayView
    from edgar.xbrl.semantic import SourceExtractWorkerError

    store = ObjectStore(tmp_path)
    bundle = _hybrid_html_xbrl_bundle(store)
    repo = BundleRepository(tmp_path, store)
    published = repo.publish(bundle)
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    service = SourceExtractService(settings, engine=engine, bundles=repo)
    first = service.extract_published_bundle(published.bundle_dir)
    assert first.persist.fact_count >= 2

    with engine.connect() as conn:
        reports_before = conn.execute(
            select(src.source_xbrl_report.c.id, src.source_xbrl_report.c.report_key).order_by(
                src.source_xbrl_report.c.id
            )
        ).all()
        facts_before = conn.execute(
            select(
                src.source_fact.c.id,
                src.source_fact.c.source_order,
                src.source_fact.c.raw_lexical_value,
            ).order_by(src.source_fact.c.id)
        ).all()
        fact_count_before = int(
            conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one()
        )

    def boom(*_args: object, **_kwargs: object) -> object:
        raise SourceExtractWorkerError(
            "INVALID_BASE_SET_QNAME: supported base set is missing an exact "
            "link or arc QName identity",
            replay=NormalizedReplayView(
                load_completed=False,
                network_attempts=(),
                unresolved_documents=(),
                loaded_source_documents=(),
                resolved_documents=(),
                expected_binding_documents=(),
                diagnostics=(),
                errors=("INVALID_BASE_SET_QNAME",),
                closure_equal=False,
            ),
            issues=(
                SemanticIssueRecord(
                    severity="fatal",
                    code=INVALID_BASE_SET_QNAME,
                    message="supported base set is missing an exact link or arc QName identity",
                ),
            ),
            arelle_version="test-arelle",
        )

    monkeypatch.setattr(
        "edgar.ingestion.source_extract.extract_filing_with_outcomes",
        boom,
    )
    with pytest.raises(SourceExtractError, match=INVALID_BASE_SET_QNAME):
        service.extract_published_bundle(published.bundle_dir)

    with engine.connect() as conn:
        reports_after = conn.execute(
            select(src.source_xbrl_report.c.id, src.source_xbrl_report.c.report_key).order_by(
                src.source_xbrl_report.c.id
            )
        ).all()
        facts_after = conn.execute(
            select(
                src.source_fact.c.id,
                src.source_fact.c.source_order,
                src.source_fact.c.raw_lexical_value,
            ).order_by(src.source_fact.c.id)
        ).all()
        fact_count_after = int(
            conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one()
        )
    assert reports_after == reports_before
    assert facts_after == facts_before
    assert fact_count_after == fact_count_before


def _dual_instance_bundle(store: ObjectStore) -> FilingBundle:
    from tests.helpers.xbrl_bundles import INSTANCE, INSTANCE_URI, make_minimal_semantic_bundle

    base = make_minimal_semantic_bundle(store)
    uri_b = "https://www.sec.gov/Archives/edgar/data/1/0000000001000010/b.xml"
    path_b = "accession/b.xml"
    inst_b = store.put_bytes(INSTANCE)
    artifacts = (
        *base.artifacts,
        BundleArtifact(
            logical_path=path_b,
            content=ContentObject(sha256=inst_b.sha256, byte_size=inst_b.byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
    )
    artifact_tuple = tuple(artifacts)
    return FilingBundle(
        filing=base.filing,
        payload_hash=compute_payload_hash(artifact_tuple),
        artifacts=artifact_tuple,
        report_inputs=(
            InstanceReportInput(document_uris=(INSTANCE_URI,)),
            InstanceReportInput(document_uris=(uri_b,)),
        ),
        uri_bindings=(
            *base.uri_bindings,
            UriBinding(uri_b, path_b, inst_b.sha256),
        ),
    )


def _dual_report_filing_outcome(store: ObjectStore, published_bundle: FilingBundle) -> object:
    """Two successful single-report extracts merged (dual-input bundle is not replay-faithful)."""
    from edgar.xbrl.config import build_semantic_config
    from edgar.xbrl.source_documents import extract_documents_for_filing
    from edgar.xbrl.source_extract import FilingExtractOutcome, extract_report_with_outcome
    from edgar.xbrl.source_records import FilingExtraction
    from tests.helpers.xbrl_bundles import INSTANCE, INSTANCE_URI, make_minimal_semantic_bundle

    base = make_minimal_semantic_bundle(store)
    uri_b = published_bundle.report_inputs[1].document_uris[0]
    path_b = "accession/b.xml"
    inst_b = store.put_bytes(INSTANCE)
    artifacts_b = tuple(
        (
            BundleArtifact(
                logical_path=path_b,
                content=ContentObject(sha256=inst_b.sha256, byte_size=inst_b.byte_size),
                artifact_kind="primary_document",
                required=True,
            )
            if a.logical_path == "accession/a.xml"
            else a
        )
        for a in base.artifacts
    )
    bindings_b = tuple(
        UriBinding(uri_b, path_b, inst_b.sha256) if b.document_uri == INSTANCE_URI else b
        for b in base.uri_bindings
    )
    bundle_b = FilingBundle(
        filing=base.filing,
        payload_hash=compute_payload_hash(artifacts_b),
        artifacts=artifacts_b,
        report_inputs=(InstanceReportInput(document_uris=(uri_b,)),),
        uri_bindings=bindings_b,
    )
    config = build_semantic_config()
    outcome_a = extract_report_with_outcome(
        base, store, base.report_inputs[0], semantic_config=config
    )
    outcome_b = extract_report_with_outcome(
        bundle_b, store, bundle_b.report_inputs[0], semantic_config=config
    )
    blocks, sections, issues = extract_documents_for_filing(published_bundle, store)
    extraction = FilingExtraction(
        reports=(outcome_a.report, outcome_b.report),
        document_blocks=blocks,
        filing_sections=sections,
        issues=issues,
    )
    return FilingExtractOutcome(
        extraction=extraction,
        report_outcomes=(outcome_a, outcome_b),
    )


def test_dual_report_service_reextract_failure_preserves_snapshot(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar.ingestion.source_extract import SourceExtractError
    from edgar.xbrl.source_extract import FilingExtractError

    store = ObjectStore(tmp_path)
    bundle = _dual_instance_bundle(store)
    repo = BundleRepository(tmp_path, store)
    published = repo.publish(bundle)
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    service = SourceExtractService(settings, engine=engine, bundles=repo)
    calls = {"n": 0}

    def fake_extract(pub_bundle: FilingBundle, store_arg: ObjectStore, **kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            return _dual_report_filing_outcome(store_arg, pub_bundle)
        raise FilingExtractError("injected B worker failure")

    monkeypatch.setattr(
        "edgar.ingestion.source_extract.extract_filing_with_outcomes",
        fake_extract,
    )
    first = service.extract_published_bundle(published.bundle_dir)
    assert first.persist.fact_count >= 2
    assert len(first.persist.report_ids) == 2

    with engine.connect() as conn:
        reports_before = conn.execute(
            select(src.source_xbrl_report.c.report_key).order_by(src.source_xbrl_report.c.id)
        ).all()
        fact_count_before = int(
            conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one()
        )

    with pytest.raises(SourceExtractError, match="injected B worker failure"):
        service.extract_published_bundle(published.bundle_dir)

    with engine.connect() as conn:
        reports_after = conn.execute(
            select(src.source_xbrl_report.c.report_key).order_by(src.source_xbrl_report.c.id)
        ).all()
        fact_count_after = int(
            conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one()
        )
    assert reports_after == reports_before
    assert fact_count_after == fact_count_before


def test_source_extract_aborts_when_implementation_changes(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar.ingestion.source_extract import SourceExtractError
    from edgar.provenance import ImplementationIdentity

    store = ObjectStore(tmp_path)
    bundle = _hybrid_html_xbrl_bundle(store)
    repo = BundleRepository(tmp_path, store)
    published = repo.publish(bundle)
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    service = SourceExtractService(settings, engine=engine, bundles=repo)

    calls = {"n": 0}

    def _mutating_identity(
        repo_root: object | None = None,
    ) -> ImplementationIdentity:
        calls["n"] += 1
        if calls["n"] == 1:
            return ImplementationIdentity(revision="pre", tree_state="clean")
        return ImplementationIdentity(revision="post", tree_state="clean")

    monkeypatch.setattr(
        "edgar.ingestion.source_extract.gather_implementation_identity",
        _mutating_identity,
    )
    monkeypatch.setattr(
        "edgar.ingestion.source_extract.gather_dependency_lock_sha256",
        lambda repo_root=None: "d" * 64,
    )

    with pytest.raises(SourceExtractError, match="implementation identity changed"):
        service.extract_published_bundle(published.bundle_dir)


def test_source_extract_aborts_when_lock_changes(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar.ingestion.source_extract import SourceExtractError
    from edgar.provenance import ImplementationIdentity

    store = ObjectStore(tmp_path)
    bundle = _hybrid_html_xbrl_bundle(store)
    repo = BundleRepository(tmp_path, store)
    published = repo.publish(bundle)
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    service = SourceExtractService(settings, engine=engine, bundles=repo)

    monkeypatch.setattr(
        "edgar.ingestion.source_extract.gather_implementation_identity",
        lambda repo_root=None: ImplementationIdentity(revision="stable", tree_state="clean"),
    )
    calls = {"n": 0}

    def _mutating_lock(repo_root: object | None = None) -> str:
        calls["n"] += 1
        return "a" * 64 if calls["n"] == 1 else "b" * 64

    monkeypatch.setattr(
        "edgar.ingestion.source_extract.gather_dependency_lock_sha256",
        _mutating_lock,
    )

    with pytest.raises(SourceExtractError, match="dependency lock digest changed"):
        service.extract_published_bundle(published.bundle_dir)

    with engine.connect() as conn:
        count = int(
            conn.execute(select(func.count()).select_from(src.source_xbrl_report)).scalar_one()
        )
    assert count == 0


def test_source_extract_aborts_when_descriptor_changes(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar.ingestion.source_extract import SourceExtractError
    from edgar.provenance import ImplementationIdentity
    from edgar.xbrl.source_extract import extract_filing_with_outcomes

    store = ObjectStore(tmp_path)
    bundle = _hybrid_html_xbrl_bundle(store)
    repo = BundleRepository(tmp_path, store)
    published = repo.publish(bundle)
    descriptor = published.bundle_dir / "bundle.json"
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    service = SourceExtractService(settings, engine=engine, bundles=repo)

    monkeypatch.setattr(
        "edgar.ingestion.source_extract.gather_implementation_identity",
        lambda repo_root=None: ImplementationIdentity(revision="stable", tree_state="clean"),
    )
    monkeypatch.setattr(
        "edgar.ingestion.source_extract.gather_dependency_lock_sha256",
        lambda repo_root=None: "c" * 64,
    )

    original_extract = extract_filing_with_outcomes

    def extract_then_mutate(*args: object, **kwargs: object) -> object:
        outcome = original_extract(*args, **kwargs)
        descriptor.write_bytes(descriptor.read_bytes() + b" ")
        return outcome

    monkeypatch.setattr(
        "edgar.ingestion.source_extract.extract_filing_with_outcomes",
        extract_then_mutate,
    )

    with pytest.raises(SourceExtractError, match="descriptor SHA changed"):
        service.extract_published_bundle(published.bundle_dir)

    with engine.connect() as conn:
        count = int(
            conn.execute(select(func.count()).select_from(src.source_xbrl_report)).scalar_one()
        )
    assert count == 0


def test_document_parity_matches_parser_output(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    html = store.put_bytes(RICH_10K_HTML)
    path = "accession/primary.htm"
    artifacts = (
        BundleArtifact(
            logical_path=path,
            content=ContentObject(sha256=html.sha256, byte_size=html.byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
    )
    # Minimal XBRL stub so FilingExtraction can be built elsewhere; documents-only check here.
    filing = FilingIdentity(
        cik="0001065088",
        accession="0001065088-24-000036",
        form_type="10-K",
        filing_date=date(2024, 2, 28),
        accepted_at=None,
        report_period_end=None,
        primary_document="primary.htm",
    )
    bundle = FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/primary.htm",)),),
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/primary.htm",
                artifact_path=path,
                content_sha256=html.sha256,
            ),
        ),
    )
    blocks, sections, _issues = extract_documents_for_filing(bundle, store)
    from edgar.parsing.html import parse_html_document
    from edgar.parsing.sections import extract_filing_sections

    parsed = parse_html_document(RICH_10K_HTML)
    expected_sections, _, _, _ = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    assert len(blocks) == len(parsed.blocks)
    assert [b.ordinal for b in blocks] == [b.ordinal for b in parsed.blocks]
    assert [b.block_type for b in blocks] == [b.kind for b in parsed.blocks]
    assert [b.parent_ordinal for b in blocks] == [b.parent_ordinal for b in parsed.blocks]
    assert [b.heading_level for b in blocks] == [b.heading_level for b in parsed.blocks]
    assert [b.source_locator["value"] for b in blocks] == [
        b.source_locator_value for b in parsed.blocks
    ]
    assert len(sections) == len(expected_sections)
    assert [s.section_key for s in sections] == [s.section_key for s in expected_sections]
    assert [s.method for s in sections] == [s.method for s in expected_sections]
    assert [s.confidence_score for s in sections] == [s.confidence_score for s in expected_sections]


def test_non_dimensional_fatal_leaves_prior_snapshot(engine: Engine, tmp_path: Path) -> None:
    """Fatal re-extract must not replace a committed accession snapshot."""
    from edgar.db.source import PersistExtractionError
    from edgar.xbrl.semantic import SourceExtractWorkerError
    from edgar.xbrl.source_records import ExtractionIssueRecord
    from tests.helpers.xbrl_bundles import (
        make_minimal_semantic_bundle,
        make_non_dimensional_context_bundle,
    )

    store = ObjectStore(tmp_path)
    good = make_minimal_semantic_bundle(store)
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, good)
        extraction_a = extract_filing(good, store)
        persist_extraction(
            conn,
            filing_id=catalog.filing_id,
            extraction=wrap_filing_extraction(extraction_a, bundle=good),
        )
        facts_before = int(
            conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one()
        )
        issues_before = int(
            conn.execute(select(func.count()).select_from(src.source_extraction_issue)).scalar_one()
        )

    bad = make_non_dimensional_context_bundle(store)
    # Same accession identity so a successful extract would replace A.
    from edgar.domain.bundle import FilingBundle

    bad_same_accession = FilingBundle(
        filing=good.filing,
        payload_hash=bad.payload_hash,
        artifacts=bad.artifacts,
        report_inputs=bad.report_inputs,
        uri_bindings=bad.uri_bindings,
    )
    with pytest.raises(SourceExtractWorkerError):
        extract_filing(bad_same_accession, store)

    with engine.connect() as conn:
        facts_after = int(
            conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one()
        )
        issues_after = int(
            conn.execute(select(func.count()).select_from(src.source_extraction_issue)).scalar_one()
        )
    assert facts_after == facts_before
    assert issues_after == issues_before

    # Persist also refuses severity=fatal if a buggy DTO arrives.
    fatal_dto = extract_filing(good, store)
    fatal_issues = (
        ExtractionIssueRecord(
            component="xbrl",
            code="SHOULD_NOT_PERSIST",
            severity="fatal",
            message="must not commit",
        ),
    )
    from edgar.xbrl.source_records import FilingExtraction, ReportExtraction

    bad_report = fatal_dto.reports[0]
    poisoned = FilingExtraction(
        reports=(
            ReportExtraction(
                report_input=bad_report.report_input,
                report_key=bad_report.report_key,
                extractor_version=bad_report.extractor_version,
                arelle_version=bad_report.arelle_version,
                arelle_item_fact_count=bad_report.arelle_item_fact_count,
                concepts=bad_report.concepts,
                declarations=bad_report.declarations,
                labels=bad_report.labels,
                references=bad_report.references,
                contexts=bad_report.contexts,
                dimensions=bad_report.dimensions,
                units=bad_report.units,
                measures=bad_report.measures,
                facts=bad_report.facts,
                relationships=bad_report.relationships,
                issues=fatal_issues,
            ),
        ),
        document_blocks=fatal_dto.document_blocks,
        filing_sections=fatal_dto.filing_sections,
        issues=(),
    )
    with engine.begin() as conn, pytest.raises(PersistExtractionError, match="fatal"):
        persist_extraction(
            conn,
            filing_id=catalog.filing_id,
            extraction=wrap_filing_extraction(poisoned, bundle=good),
        )

    with engine.connect() as conn:
        assert (
            int(conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one())
            == facts_before
        )


def test_report2_fatal_leaves_prior_snapshot_unchanged(engine: Engine, tmp_path: Path) -> None:
    """Report 1 OK + report 2 fatal must not replace a committed accession snapshot."""
    from edgar.domain.bundle import BundleArtifact, ContentObject, FilingBundle, UriBinding
    from edgar.ingestion.payload import compute_payload_hash
    from edgar.xbrl.semantic import SourceExtractWorkerError
    from tests.helpers.xbrl_bundles import (
        INSTANCE_NON_DIM,
        INSTANCE_URI,
        make_minimal_semantic_bundle,
    )

    store = ObjectStore(tmp_path)
    good = make_minimal_semantic_bundle(store)
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, good)
        extraction_a = extract_filing(good, store)
        persist_extraction(
            conn,
            filing_id=catalog.filing_id,
            extraction=wrap_filing_extraction(extraction_a, bundle=good),
        )
        facts_before = int(
            conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one()
        )
        reports_before = int(
            conn.execute(select(func.count()).select_from(src.source_xbrl_report)).scalar_one()
        )
        blocks_before = int(
            conn.execute(select(func.count()).select_from(src.source_document_block)).scalar_one()
        )

    uri_bad = "https://www.sec.gov/Archives/edgar/data/1/0000000001000011/bad.xml"
    path_bad = "accession/bad.xml"
    bad_obj = store.put_bytes(INSTANCE_NON_DIM)
    artifacts = (
        *good.artifacts,
        BundleArtifact(
            logical_path=path_bad,
            content=ContentObject(sha256=bad_obj.sha256, byte_size=bad_obj.byte_size),
            artifact_kind="attachment",
            required=True,
        ),
    )
    dual = FilingBundle(
        filing=good.filing,
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(
            InstanceReportInput(document_uris=(INSTANCE_URI,)),
            InstanceReportInput(document_uris=(uri_bad,)),
        ),
        uri_bindings=(
            *good.uri_bindings,
            UriBinding(uri_bad, path_bad, bad_obj.sha256),
        ),
    )
    with pytest.raises(SourceExtractWorkerError):
        extract_filing(dual, store)

    with engine.connect() as conn:
        assert (
            int(conn.execute(select(func.count()).select_from(src.source_fact)).scalar_one())
            == facts_before
        )
        assert (
            int(conn.execute(select(func.count()).select_from(src.source_xbrl_report)).scalar_one())
            == reports_before
        )
        assert (
            int(
                conn.execute(
                    select(func.count()).select_from(src.source_document_block)
                ).scalar_one()
            )
            == blocks_before
        )
