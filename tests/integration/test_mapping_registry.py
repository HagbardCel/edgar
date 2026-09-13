"""PostgreSQL integration tests for registry sync (Phase 2C)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import IntegrityError

from edgar.config import Settings
from edgar.db import registry_schema as reg
from edgar.db import source_schema as src
from edgar.domain.concept_id import concept_id
from edgar.registry.hashing import definition_hash
from edgar.registry.loader import load_metrics_yml
from edgar.registry.service import (
    RegistryService,
    UnsafeMetricDeletionError,
    row_mirror_payload,
)
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables

pytestmark = pytest.mark.database

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_YML = _REPO_ROOT / "registry" / "metrics.yml"
_NS = "http://example.com/test"


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


def _settings() -> Settings:
    return Settings().model_copy(update={"edgar_database_url": test_database_url()})


def _write_metrics(directory: Path, metrics: list[dict[object, object]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "metrics.yml"
    path.write_text(yaml.safe_dump({"metrics": metrics}, sort_keys=False), encoding="utf-8")
    return directory


def _production_metric_dicts() -> list[dict[object, object]]:
    loaded = load_metrics_yml(_PRODUCTION_YML)
    return [metric.model_dump(mode="json") for metric in loaded.metrics]


def test_sync_inserts_and_is_idempotent(engine: Engine, tmp_path: Path) -> None:
    metrics = _production_metric_dicts()[:3]
    registry_dir = _write_metrics(tmp_path / "reg", metrics)
    service = RegistryService(_settings(), engine=engine, registry_dir=registry_dir)
    first = service.sync_canonical_metrics()
    assert len(first.added) == 3
    assert first.changed == ()
    assert first.removed == ()
    assert first.unchanged == ()
    second = service.sync_canonical_metrics()
    assert second.added == ()
    assert second.changed == ()
    assert second.removed == ()
    assert len(second.unchanged) == 3
    with engine.connect() as conn:
        synced = conn.execute(select(reg.registry_canonical_metric)).mappings().all()
        first_synced_at = {row["key"]: row["synced_at"] for row in synced}
    third = service.sync_canonical_metrics()
    assert third.unchanged == second.unchanged
    with engine.connect() as conn:
        again = conn.execute(select(reg.registry_canonical_metric)).mappings().all()
        for row in again:
            assert row["synced_at"] == first_synced_at[row["key"]]


def test_sync_name_only_change_updates_mirror_without_hash_change(
    engine: Engine, tmp_path: Path
) -> None:
    metrics = _production_metric_dicts()[:1]
    registry_dir = _write_metrics(tmp_path / "reg", metrics)
    service = RegistryService(_settings(), engine=engine, registry_dir=registry_dir)
    service.sync_canonical_metrics()
    loaded = load_metrics_yml(registry_dir / "metrics.yml")
    original_hash = definition_hash(loaded.metrics[0])
    renamed = loaded.metrics[0].model_dump(mode="json")
    renamed["name"] = "Renamed display label"
    _write_metrics(tmp_path / "reg", [renamed])
    result = service.sync_canonical_metrics()
    assert result.changed == (renamed["key"],)
    with engine.connect() as conn:
        row = conn.execute(select(reg.registry_canonical_metric)).mappings().one()
    assert row["name"] == "Renamed display label"
    assert row["definition_hash"] == original_hash


def test_unsafe_metric_deletion_fails(engine: Engine, tmp_path: Path) -> None:
    metrics = _production_metric_dicts()[:2]
    registry_dir = _write_metrics(tmp_path / "reg", metrics)
    service = RegistryService(_settings(), engine=engine, registry_dir=registry_dir)
    service.sync_canonical_metrics()
    key = str(metrics[0]["key"])
    cid = concept_id(_NS, "NetSales")
    with engine.begin() as conn:
        conn.execute(
            src.source_concept.insert().values(id=cid, namespace_uri=_NS, local_name="NetSales")
        )
        conn.execute(
            reg.registry_mapping_assertion.insert().values(
                source_concept_id=cid,
                target_metric_key=key,
                target_definition_hash="a" * 64,
                relation="exact",
                scope_kind="global",
                status="candidate",
                method="curated",
                evidence=[],
                created_at=datetime.now(UTC),
                created_by="human:test",
            )
        )
    _write_metrics(tmp_path / "reg", [metrics[1]])
    with pytest.raises(UnsafeMetricDeletionError, match=key):
        service.sync_canonical_metrics()


def test_accepted_null_rationale_rejected_by_check(engine: Engine, tmp_path: Path) -> None:
    metrics = _production_metric_dicts()[:1]
    registry_dir = _write_metrics(tmp_path / "reg", metrics)
    RegistryService(_settings(), engine=engine, registry_dir=registry_dir).sync_canonical_metrics()
    cid = concept_id(_NS, "Foo")
    with engine.begin() as conn:
        conn.execute(
            src.source_concept.insert().values(id=cid, namespace_uri=_NS, local_name="Foo")
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            reg.registry_mapping_assertion.insert().values(
                source_concept_id=cid,
                target_metric_key=str(metrics[0]["key"]),
                target_definition_hash="b" * 64,
                relation="exact",
                scope_kind="global",
                status="accepted",
                method="curated",
                rationale=None,
                evidence=[{"kind": "human_analysis", "summary": "x", "data": {}}],
                created_at=datetime.now(UTC),
                created_by="human:test",
            )
        )


def test_null_created_by_rejected_by_check(engine: Engine, tmp_path: Path) -> None:
    metrics = _production_metric_dicts()[:1]
    registry_dir = _write_metrics(tmp_path / "reg", metrics)
    RegistryService(_settings(), engine=engine, registry_dir=registry_dir).sync_canonical_metrics()
    cid = concept_id(_NS, "Bar")
    with engine.begin() as conn:
        conn.execute(
            src.source_concept.insert().values(id=cid, namespace_uri=_NS, local_name="Bar")
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                """
                    INSERT INTO registry.mapping_assertion (
                        source_concept_id, target_metric_key, target_definition_hash,
                        relation, scope_kind, status, method, evidence, created_at, created_by
                    ) VALUES (
                        :cid, :key, :hash, 'related', 'global', 'candidate', 'curated',
                        '[]'::jsonb, now(), NULL
                    )
                    """
            ),
            {
                "cid": cid,
                "key": str(metrics[0]["key"]),
                "hash": "c" * 64,
            },
        )


def test_row_mirror_payload_roundtrip(engine: Engine, tmp_path: Path) -> None:
    metrics = _production_metric_dicts()[:1]
    registry_dir = _write_metrics(tmp_path / "reg", metrics)
    service = RegistryService(_settings(), engine=engine, registry_dir=registry_dir)
    service.sync_canonical_metrics()
    with engine.connect() as conn:
        row = dict(conn.execute(select(reg.registry_canonical_metric)).mappings().one())
    loaded = load_metrics_yml(registry_dir / "metrics.yml").metrics[0]
    from edgar.registry.service import mirror_payload

    assert row_mirror_payload(row) == mirror_payload(loaded)
