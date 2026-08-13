"""Synthetic semantic acceptance cases A–F for Phase 2A mapping registry."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine

from edgar.config import Settings
from edgar.db import schema as tables
from edgar.db.catalog import catalog_bundle
from edgar.metrics.service import MetricRegistryService
from edgar.projection.semantic import SemanticProjectionService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from tests.helpers.database import alembic_config, test_database_url, truncate_all_tables
from tests.helpers.metrics_fixtures import build_acceptance_registry
from tests.helpers.xbrl_bundles import make_rich_semantic_bundle

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


@pytest.fixture
def acceptance_service(engine: Engine, tmp_path: Path) -> MetricRegistryService:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    store = ObjectStore(tmp_path)
    bundle = make_rich_semantic_bundle(store)
    repo = BundleRepository(tmp_path, store)
    published = repo.publish(bundle)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, published.opaque_id)
    projection = SemanticProjectionService(settings, engine=engine).project_published_bundle(
        published.bundle_dir
    )
    registry_dir = tmp_path / "acceptance-registry"
    with engine.connect() as conn:
        build_acceptance_registry(
            registry_dir,
            conn=conn,
            projection=projection,
            bundle_opaque_id=published.opaque_id,
            accession=bundle.filing.accession,
        )
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    service.sync()
    return service


def test_acceptance_cases_present(acceptance_service: MetricRegistryService) -> None:
    rows = acceptance_service.list_mappings()
    keys = {row.rule.rule_key for row in rows}
    assert "map-acc-a-equivalent" in keys
    assert "map-acc-b-issuer-equivalent" in keys
    assert "map-acc-c-incompatible" in keys
    assert "map-acc-d-component" in keys
    assert "map-acc-e-unresolved" in keys
    states = {row.rule.rule_key: row.state for row in rows}
    assert states["map-acc-e-equivalent-old"] == "superseded"
    assert states["map-acc-e-unresolved"] == "current"


def test_explain_does_not_claim_observations(acceptance_service: MetricRegistryService) -> None:
    payload = acceptance_service.explain_mapping("map-acc-a-equivalent")
    occ = payload["source_fact_occurrences"]
    assert "not canonical observations" in occ["label"]
    assert occ["count"] >= 1


def test_no_metric_observation_table(
    engine: Engine, acceptance_service: MetricRegistryService
) -> None:
    _ = acceptance_service
    table_names = {table.name for table in tables.ALL_TABLES}
    assert "metric_observation" not in table_names


def test_export_audit_report(acceptance_service: MetricRegistryService) -> None:
    reports = acceptance_service.export_mappings_audit()
    assert len(reports) >= 5
    for report in reports:
        assert "rule_key" in report
        assert report["source_fact_occurrences"]["label"]
