"""Integration tests for mappings explain (pinned evidence only)."""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, select, update

from edgar.config import Settings
from edgar.db import schema as tables
from edgar.db.catalog import catalog_bundle
from edgar.db.mapping_evidence import MappingEvidenceError
from edgar.domain.bundle import bundle_fingerprint
from edgar.metrics.service import MetricRegistryService
from edgar.projection.semantic import SemanticProjectionService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from edgar.xbrl.config import build_semantic_config, semantic_config_fingerprint
from tests.helpers.database import alembic_config, test_database_url, truncate_all_tables
from tests.helpers.metrics_fixtures import write_test_registry_with_rules
from tests.helpers.xbrl_bundles import (
    make_minimal_semantic_bundle,
    make_non_dimensional_context_bundle,
)

pytestmark = pytest.mark.database


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = test_database_url()
    eng = create_engine(url, future=True)
    command.upgrade(alembic_config(url), "head")
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


def test_mappings_explain_resolves_pinned_evidence(engine: Engine, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    store = ObjectStore(data_root)
    bundle = make_minimal_semantic_bundle(store)
    repo = BundleRepository(data_root, store)
    published = repo.publish(bundle)
    config = build_semantic_config()
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(
        registry_dir,
        bundle_fingerprint=bundle_fingerprint(bundle),
        semantic_config_fingerprint=semantic_config_fingerprint(config),
        accession=bundle.filing.accession,
    )

    settings = _settings(data_root)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, published.opaque_id)

    SemanticProjectionService(settings, engine=engine).project_published_bundle(
        published.bundle_dir
    )

    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    payload = service.explain_mapping("map-test-equivalent")
    assert payload["state"] == "current"
    enrichment = payload["pinned_evidence_enrichment"]
    assert enrichment is not None
    assert enrichment["projection"]["status"] == "complete"
    assert enrichment["report_input_ordinal"] == 0
    assert enrichment["concept_declaration"]["qname"]["local_name"] == "CashAndCashEquivalents"
    assert enrichment["concept_declaration"]["period_type"] == "instant"
    assert len(enrichment["fact_occurrences"]) >= 1
    fact = enrichment["fact_occurrences"][0]
    assert "context" in fact
    assert fact["context"]["source_context_id"]
    assert fact["unit"] is not None
    assert fact["unit"]["source_unit_id"]
    assert fact["source"]["content_sha256"]
    assert payload["scope_kind"] == "global"


def test_mappings_export_is_db_free(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(
        registry_dir,
        bundle_fingerprint="a" * 64,
        semantic_config_fingerprint="b" * 64,
    )
    settings = Settings().model_copy(update={"edgar_database_url": test_database_url()})
    payload = MetricRegistryService(settings, registry_dir=registry_dir).export_mappings_audit()
    assert payload["count"] == 3
    assert payload["registry_hash"]
    assert len(payload["reports"]) == 3
    assert "pinned_evidence_enrichment" not in payload["reports"][0]


def test_explain_succeeds_with_duplicate_bundles_one_projected(
    engine: Engine, tmp_path: Path
) -> None:
    data_root = tmp_path / "data"
    store = ObjectStore(data_root)
    bundle = make_minimal_semantic_bundle(store)
    repo = BundleRepository(data_root, store)
    published = repo.publish(bundle)
    second_opaque = uuid.uuid4().hex
    second_dir = published.bundle_dir.parent / second_opaque
    shutil.copytree(published.bundle_dir, second_dir)

    config = build_semantic_config()
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(
        registry_dir,
        bundle_fingerprint=bundle_fingerprint(bundle),
        semantic_config_fingerprint=semantic_config_fingerprint(config),
        accession=bundle.filing.accession,
    )
    settings = _settings(data_root)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, published.opaque_id)
        catalog_bundle(conn, bundle, second_opaque)

    # Only project the first publication.
    SemanticProjectionService(settings, engine=engine).project_published_bundle(
        published.bundle_dir
    )
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    payload = service.explain_mapping("map-test-equivalent")
    assert payload["pinned_evidence_enrichment"]["projection"]["status"] == "complete"


def test_explain_collapses_duplicate_complete_projections(engine: Engine, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    store = ObjectStore(data_root)
    bundle = make_minimal_semantic_bundle(store)
    repo = BundleRepository(data_root, store)
    published = repo.publish(bundle)
    second_opaque = uuid.uuid4().hex
    second_dir = published.bundle_dir.parent / second_opaque
    shutil.copytree(published.bundle_dir, second_dir)

    config = build_semantic_config()
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(
        registry_dir,
        bundle_fingerprint=bundle_fingerprint(bundle),
        semantic_config_fingerprint=semantic_config_fingerprint(config),
        accession=bundle.filing.accession,
    )
    settings = _settings(data_root)
    with engine.begin() as conn:
        first = catalog_bundle(conn, bundle, published.opaque_id)
        second = catalog_bundle(conn, bundle, second_opaque)

    SemanticProjectionService(settings, engine=engine).project_published_bundle(
        published.bundle_dir
    )
    SemanticProjectionService(settings, engine=engine).project_published_bundle(second_dir)

    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    payload = service.explain_mapping("map-test-equivalent")
    chosen_bundle_id = payload["pinned_evidence_enrichment"]["bundle_id"]
    assert chosen_bundle_id == min(first.bundle_id, second.bundle_id)


def test_explain_prefers_complete_over_incomplete_duplicate(engine: Engine, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    store = ObjectStore(data_root)
    bundle = make_minimal_semantic_bundle(store)
    repo = BundleRepository(data_root, store)
    published = repo.publish(bundle)
    second_opaque = uuid.uuid4().hex
    second_dir = published.bundle_dir.parent / second_opaque
    shutil.copytree(published.bundle_dir, second_dir)

    config = build_semantic_config()
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(
        registry_dir,
        bundle_fingerprint=bundle_fingerprint(bundle),
        semantic_config_fingerprint=semantic_config_fingerprint(config),
        accession=bundle.filing.accession,
    )
    settings = _settings(data_root)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, published.opaque_id)
        second_catalog = catalog_bundle(conn, bundle, second_opaque)

    SemanticProjectionService(settings, engine=engine).project_published_bundle(
        published.bundle_dir
    )
    SemanticProjectionService(settings, engine=engine).project_published_bundle(second_dir)

    with engine.begin() as conn:
        conn.execute(
            update(tables.semantic_projection)
            .where(
                tables.semantic_projection.c.xbrl_report_input_id.in_(
                    select(tables.xbrl_report_input.c.id).where(
                        tables.xbrl_report_input.c.filing_bundle_id == second_catalog.bundle_id
                    )
                )
            )
            .values(status="incomplete")
        )

    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    payload = service.explain_mapping("map-test-equivalent")
    assert payload["pinned_evidence_enrichment"]["projection"]["status"] == "complete"


def test_explain_rejects_incomplete_projection(engine: Engine, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    store = ObjectStore(data_root)
    bundle = make_non_dimensional_context_bundle(store)
    repo = BundleRepository(data_root, store)
    published = repo.publish(bundle)
    config = build_semantic_config()
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(
        registry_dir,
        bundle_fingerprint=bundle_fingerprint(bundle),
        semantic_config_fingerprint=semantic_config_fingerprint(config),
        accession=bundle.filing.accession,
    )
    settings = _settings(data_root)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, published.opaque_id)
    result = SemanticProjectionService(settings, engine=engine).project_published_bundle(
        published.bundle_dir
    )
    assert result.projection.status == "incomplete"

    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    with pytest.raises(MappingEvidenceError, match="incomplete"):
        service.explain_mapping("map-test-equivalent")


def test_explain_rejects_issuer_period_outside_scope(engine: Engine, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    store = ObjectStore(data_root)
    base = make_minimal_semantic_bundle(store)
    bundle = replace(
        base,
        filing=replace(base.filing, report_period_end=date(2025, 12, 31)),
    )
    # payload_hash depends on artifacts, not report_period_end; identity is fine.
    repo = BundleRepository(data_root, store)
    published = repo.publish(bundle)
    config = build_semantic_config()
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(
        registry_dir,
        bundle_fingerprint=bundle_fingerprint(bundle),
        semantic_config_fingerprint=semantic_config_fingerprint(config),
        accession=bundle.filing.accession,
    )
    settings = _settings(data_root)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, published.opaque_id)
    SemanticProjectionService(settings, engine=engine).project_published_bundle(
        published.bundle_dir
    )
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    with pytest.raises(MappingEvidenceError, match="outside issuer_period"):
        service.explain_mapping("map-test-issuer-period")


def test_list_mappings_cik_includes_filing_scope(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(
        registry_dir,
        bundle_fingerprint="a" * 64,
        semantic_config_fingerprint="b" * 64,
        accession="0000000001-00-000001",
    )
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
    config = build_semantic_config()
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(
        registry_dir,
        bundle_fingerprint=bundle_fingerprint(bundle),
        semantic_config_fingerprint=semantic_config_fingerprint(config),
        accession=bundle.filing.accession,
    )
    settings = _settings(data_root)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, published.opaque_id)
    SemanticProjectionService(settings, engine=engine).project_published_bundle(
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
