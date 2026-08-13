"""Integration tests for mappings explain (pinned evidence only)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine

from edgar.config import Settings
from edgar.db.catalog import catalog_bundle
from edgar.domain.bundle import bundle_fingerprint
from edgar.metrics.service import MetricRegistryService
from edgar.projection.semantic import SemanticProjectionService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from edgar.xbrl.config import build_semantic_config, semantic_config_fingerprint
from tests.helpers.database import alembic_config, test_database_url, truncate_all_tables
from tests.helpers.metrics_fixtures import write_test_registry_with_rules
from tests.helpers.xbrl_bundles import make_minimal_semantic_bundle

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

    settings = Settings().model_copy(
        update={"edgar_data_root": data_root, "edgar_database_url": test_database_url()}
    )
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
    assert len(enrichment["fact_occurrences"]) >= 1
    assert payload["scope_kind"] == "global"


def test_mappings_export_is_db_free(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    write_test_registry_with_rules(
        registry_dir,
        bundle_fingerprint="a" * 64,
        semantic_config_fingerprint="b" * 64,
    )
    settings = Settings().model_copy(update={"edgar_database_url": test_database_url()})
    reports = MetricRegistryService(settings, registry_dir=registry_dir).export_mappings_audit()
    assert len(reports) == 3
    assert "pinned_evidence_enrichment" not in reports[0]
