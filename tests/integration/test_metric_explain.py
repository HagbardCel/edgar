"""Integration tests for mappings explain (pinned source.* evidence)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine

from edgar.config import Settings
from edgar.db.mapping_evidence import MappingEvidenceError
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
from edgar.metrics.service import MetricRegistryService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from edgar.xbrl.records import ExpandedQName
from edgar.xbrl.source_records import (
    ConceptDeclarationRecord,
    ConceptRecord,
    ContextRecord,
    FactRecord,
    FilingExtraction,
    ReportExtraction,
    UnitMeasureRecord,
    UnitRecord,
)
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables
from tests.helpers.metrics_fixtures import write_test_registry_with_rules
from tests.helpers.xbrl_bundles import make_minimal_semantic_bundle

pytestmark = pytest.mark.database

_NS = "http://example.com/test"
_DOC_PATH = "accession/a.htm"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = test_database_url()
    eng = create_engine(url, future=True)
    reset_test_database(eng, database_url=url)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def truncate_all(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        truncate_all_tables(conn)
    yield


def _settings(data_root: Path) -> Settings:
    return Settings().model_copy(
        update={"edgar_data_root": data_root, "edgar_database_url": test_database_url()}
    )


def _qname(local: str) -> ExpandedQName:
    return ExpandedQName(namespace_uri=_NS, local_name=local)


def _make_catalog_bundle(
    data_root: Path,
    *,
    accession: str = "0000000001-00-000001",
    report_period_end: date | None = date(2024, 12, 31),
) -> FilingBundle:
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
            cik="0000000001",
            accession=accession,
            form_type="10-K",
            filing_date=date(2024, 2, 28),
            accepted_at=None,
            report_period_end=report_period_end,
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


def _report(
    *,
    report_key: str,
    local: str = "CashAndCashEquivalents",
    lexical: str = "100",
    numeric: Decimal = Decimal("100"),
) -> ReportExtraction:
    concept = _qname(local)
    return ReportExtraction(
        report_input={"kind": "instance", "document_uris": ["https://example.com/a.htm"]},
        report_key=report_key,
        extractor_version="source-extract-v1",
        arelle_version="2.43.1",
        arelle_item_fact_count=1,
        concepts=(ConceptRecord(namespace_uri=_NS, local_name=local),),
        declarations=(
            ConceptDeclarationRecord(
                concept=concept,
                period_type="instant",
                balance="debit",
            ),
        ),
        contexts=(
            ContextRecord(
                source_context_id="c1",
                entity_scheme="http://www.sec.gov/CIK",
                entity_identifier="0000000001",
                period_kind="instant",
                period_instant="2024-12-31",
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
                raw_lexical_value=lexical,
                resolved_value_kind="numeric",
                resolved_numeric=numeric,
                source_document_relative_path=_DOC_PATH,
            ),
        ),
    )


def test_mappings_explain_resolves_pinned_source_evidence(engine: Engine, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    store = ObjectStore(data_root)
    bundle = make_minimal_semantic_bundle(store)
    repo = BundleRepository(data_root, store)
    published = repo.publish(bundle)
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(registry_dir, accession=bundle.filing.accession)

    settings = _settings(data_root)
    SourceExtractService(settings, engine=engine, bundles=repo).extract_published_bundle(
        published.bundle_dir
    )

    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    payload = service.explain_mapping("map-test-equivalent")
    assert payload["state"] == "current"
    enrichment = payload["pinned_evidence_enrichment"]
    assert enrichment is not None
    assert enrichment["report_count"] >= 1
    assert len(enrichment["reports"]) == enrichment["report_count"]
    report = enrichment["reports"][0]
    assert report["report_id"] > 0
    assert len(report["report_key"]) == 64
    assert report["concept_declaration"]["qname"]["local_name"] == "CashAndCashEquivalents"
    assert report["concept_declaration"]["period_type"] == "instant"
    assert len(report["fact_occurrences"]) >= 1
    fact = report["fact_occurrences"][0]
    assert "context" in fact
    assert fact["context"]["source_context_id"]
    assert fact["unit"] is not None
    assert fact["unit"]["source_unit_id"]
    assert payload["scope_kind"] == "global"
    assert "bundle_fingerprint" not in payload["evidence"]
    assert set(payload["evidence"].keys()) == {"accession_number", "concept"}


def test_mappings_export_is_db_free(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(registry_dir)
    settings = Settings().model_copy(update={"edgar_database_url": test_database_url()})
    payload = MetricRegistryService(settings, registry_dir=registry_dir).export_mappings_audit()
    assert payload["count"] == 3
    assert payload["registry_hash"]
    assert len(payload["reports"]) == 3
    assert "pinned_evidence_enrichment" not in payload["reports"][0]


def test_explain_returns_both_reports_for_same_qname(engine: Engine, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    accession = "0000000001-00-000001"
    key_a = "a" * 64
    key_b = "b" * 64
    bundle = _make_catalog_bundle(data_root, accession=accession)
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(registry_dir, accession=accession)

    extraction = FilingExtraction(
        reports=(
            _report(report_key=key_a, lexical="111", numeric=Decimal("111")),
            _report(report_key=key_b, lexical="222", numeric=Decimal("222")),
        ),
        document_blocks=(),
        filing_sections=(),
        issues=(),
    )
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=extraction)

    settings = _settings(data_root)
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    payload = service.explain_mapping("map-test-equivalent")
    enrichment = payload["pinned_evidence_enrichment"]
    assert enrichment["report_count"] == 2
    reports = enrichment["reports"]
    assert len(reports) == 2
    keys = {r["report_key"] for r in reports}
    ids = {r["report_id"] for r in reports}
    assert keys == {key_a, key_b}
    assert len(ids) == 2
    # Separate declarations — not merged into one section.
    decl_ids = {r["concept_declaration_id"] for r in reports}
    assert len(decl_ids) == 2
    facts_by_key = {r["report_key"]: r["fact_occurrences"][0]["resolved_numeric"] for r in reports}
    assert facts_by_key[key_a] == "111"
    assert facts_by_key[key_b] == "222"
    # Stable ordering by report_id, not arbitrary first-row pick.
    assert [r["report_id"] for r in reports] == sorted(r["report_id"] for r in reports)


def test_explain_rejects_missing_source_filing(engine: Engine, tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(registry_dir)
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    with pytest.raises(MappingEvidenceError, match="no source.filing"):
        service.explain_mapping("map-test-equivalent")


def test_explain_rejects_issuer_period_outside_scope(engine: Engine, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    accession = "0000000001-00-000001"
    bundle = _make_catalog_bundle(
        data_root,
        accession=accession,
        report_period_end=date(2025, 12, 31),
    )
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(registry_dir, accession=accession)
    extraction = FilingExtraction(
        reports=(_report(report_key="c" * 64),),
        document_blocks=(),
        filing_sections=(),
        issues=(),
    )
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=extraction)

    settings = _settings(data_root)
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    with pytest.raises(MappingEvidenceError, match="outside issuer_period"):
        service.explain_mapping("map-test-issuer-period")


def test_list_mappings_cik_includes_filing_scope(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(registry_dir, accession="0000000001-00-000001")
    settings = Settings()
    service = MetricRegistryService(settings, registry_dir=registry_dir)
    rows = service.list_mappings(cik="0000000001")
    keys = {r.rule.rule_key for r in rows}
    assert "map-test-incompatible" in keys
    assert "map-test-issuer-period" in keys
    assert "map-test-equivalent" not in keys


def test_explain_loads_registry_once(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    store = ObjectStore(data_root)
    bundle = make_minimal_semantic_bundle(store)
    repo = BundleRepository(data_root, store)
    published = repo.publish(bundle)
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(registry_dir, accession=bundle.filing.accession)
    settings = _settings(data_root)
    SourceExtractService(settings, engine=engine, bundles=repo).extract_published_bundle(
        published.bundle_dir
    )

    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    calls = {"n": 0}
    original = service.load_git_registry

    def counted() -> object:
        calls["n"] += 1
        return original()

    monkeypatch.setattr(service, "load_git_registry", counted)
    service.explain_mapping("map-test-equivalent")
    assert calls["n"] == 1


def test_explain_uses_filing_period_not_bundle_replace(engine: Engine, tmp_path: Path) -> None:
    """Issuer-period scope still keys off source.filing.report_period_end."""
    data_root = tmp_path / "data"
    accession = "0000000001-00-000001"
    base = _make_catalog_bundle(data_root, accession=accession, report_period_end=date(2024, 6, 30))
    bundle = replace(
        base,
        filing=replace(base.filing, report_period_end=date(2024, 6, 30)),
    )
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(registry_dir, accession=accession)
    extraction = FilingExtraction(
        reports=(_report(report_key="d" * 64),),
        document_blocks=(),
        filing_sections=(),
        issues=(),
    )
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(conn, filing_id=catalog.filing_id, extraction=extraction)

    settings = _settings(data_root)
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    payload = service.explain_mapping("map-test-issuer-period")
    assert payload["pinned_evidence_enrichment"]["filing"]["report_period_end"] == "2024-06-30"
