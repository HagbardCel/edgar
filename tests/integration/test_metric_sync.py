"""PostgreSQL metric registry sync integration tests."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, update

from edgar.config import Settings
from edgar.db import schema as tables
from edgar.db.catalog import catalog_bundle
from edgar.db.metrics import MetricRegistryConflict, verify_materialization
from edgar.metrics.registry import load_registry
from edgar.metrics.service import MetricRegistryService, RegistryNotSyncedError
from edgar.projection.semantic import SemanticProjectionService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from tests.helpers.database import alembic_config, test_database_url, truncate_all_tables
from tests.helpers.metrics_fixtures import (
    build_test_registry_with_projection_rule,
    copy_registry_skeleton,
)
from tests.helpers.xbrl_bundles import make_minimal_semantic_bundle

pytestmark = pytest.mark.database

_REPO_REGISTRY = Path(__file__).resolve().parents[2] / "semantic-registry"


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


def test_registry_sync_definitions_only(engine: Engine, tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    copy_registry_skeleton(registry_dir)
    settings = Settings().model_copy(update={"edgar_database_url": test_database_url()})
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    first = service.sync()
    assert first.verified_noop is False
    assert first.definition_count == 20
    assert first.rule_count == 0
    second = service.sync()
    assert second.verified_noop is True
    assert second.revision_id == first.revision_id


def test_registry_read_requires_sync(engine: Engine, tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    copy_registry_skeleton(registry_dir)
    settings = Settings().model_copy(update={"edgar_database_url": test_database_url()})
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    with pytest.raises(RegistryNotSyncedError):
        service.list_metrics()


def test_corrupted_definition_fails_verified_noop(engine: Engine, tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    copy_registry_skeleton(registry_dir)
    settings = Settings().model_copy(update={"edgar_database_url": test_database_url()})
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    service.sync()
    with engine.begin() as conn:
        conn.execute(
            update(tables.metric_definition)
            .where(tables.metric_definition.c.metric_code == "operating_company_revenue")
            .values(name="TAMPERED")
        )
    with pytest.raises(MetricRegistryConflict), engine.begin() as conn:
        verify_materialization(conn, service.load_git_registry())


def test_git_ahead_of_db_fails_public_read(engine: Engine, tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    copy_registry_skeleton(registry_dir)
    settings = Settings().model_copy(update={"edgar_database_url": test_database_url()})
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    service.sync()
    mutated = tmp_path / "mutated"
    shutil.copytree(registry_dir, mutated)
    families = (mutated / "metric-families.json").read_text(encoding="utf-8")
    (mutated / "metric-families.json").write_text(
        families.replace('"Operating revenue measures"', '"Operating revenue measures (edited)"'),
        encoding="utf-8",
    )
    stale_service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    ahead_service = MetricRegistryService(settings, engine=engine, registry_dir=mutated)
    stale_service.list_metrics()
    with pytest.raises(RegistryNotSyncedError):
        ahead_service.list_metrics()


def test_sync_with_mapping_rule_after_projection(engine: Engine, tmp_path: Path) -> None:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    store = ObjectStore(tmp_path)
    bundle = make_minimal_semantic_bundle(store)
    repo = BundleRepository(tmp_path, store)
    published = repo.publish(bundle)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, published.opaque_id)
    projection = SemanticProjectionService(settings, engine=engine).project_published_bundle(
        published.bundle_dir
    )

    registry_dir = tmp_path / "registry-with-rule"
    with engine.connect() as conn:
        _, rule_key = build_test_registry_with_projection_rule(
            registry_dir,
            conn=conn,
            projection=projection,
            bundle_opaque_id=published.opaque_id,
            accession=bundle.filing.accession,
        )
    service = MetricRegistryService(settings, engine=engine, registry_dir=registry_dir)
    result = service.sync()
    assert result.rule_count >= 1
    rows = service.list_mappings()
    assert any(r.rule.rule_key == rule_key for r in rows)


def test_production_registry_loads(engine: Engine) -> None:
    registry = load_registry(_REPO_REGISTRY)
    assert len(registry.definitions) == 20
