"""PostgreSQL tests for mapping assertion propose/accept/reject."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import Engine, create_engine, select

from edgar.config import Settings
from edgar.db import registry_schema as reg
from edgar.db import source_schema as src
from edgar.domain.concept_id import concept_id
from edgar.registry.hashing import definition_hash
from edgar.registry.loader import load_metrics_yml
from edgar.registry.mapping import (
    MappingAssertionCreate,
    MappingAssertionRevision,
    MappingEvidenceItem,
)
from edgar.registry.service import (
    ConceptNotFoundError,
    ConflictingExactMappingError,
    MappingDecisionError,
    MetricDefinitionChangedError,
    RegistryOutOfSyncError,
    RegistryService,
)
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables

pytestmark = pytest.mark.database

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_YML = _REPO_ROOT / "registry" / "metrics.yml"
_NS = "http://example.com/acme"
_CONCEPT = "{http://example.com/acme}NetSales"


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


def _write_metrics(directory: Path, metrics: list[dict[str, Any]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metrics.yml").write_text(
        yaml.safe_dump({"metrics": metrics}, sort_keys=False), encoding="utf-8"
    )
    return directory


def _metric_dicts(*keys: str) -> list[dict[str, Any]]:
    loaded = load_metrics_yml(_PRODUCTION_YML)
    wanted = set(keys)
    return [m.model_dump(mode="json") for m in loaded.metrics if m.key in wanted]


def _dump_dir_metrics(registry_dir: Path) -> list[dict[str, Any]]:
    loaded = load_metrics_yml(registry_dir / "metrics.yml")
    return [m.model_dump(mode="json") for m in loaded.metrics]


def _service(engine: Engine, registry_dir: Path) -> RegistryService:
    return RegistryService(_settings(), engine=engine, registry_dir=registry_dir)


def _seed(engine: Engine, registry_dir: Path) -> RegistryService:
    service = _service(engine, registry_dir)
    service.sync_canonical_metrics()
    cid = concept_id(_NS, "NetSales")
    with engine.begin() as conn:
        conn.execute(
            src.source_concept.insert().values(id=cid, namespace_uri=_NS, local_name="NetSales")
        )
        conn.execute(src.source_issuer.insert().values(cik="0000123456", name="Acme"))
    return service


def _evidence() -> tuple[MappingEvidenceItem, ...]:
    return (
        MappingEvidenceItem(
            kind="label",
            summary="Primary English label",
            data={"role": "http://www.xbrl.org/2003/role/label", "text": "Net Sales"},
            accessions=("0000123456-24-000001",),
        ),
    )


def _create(**overrides: object) -> MappingAssertionCreate:
    payload: dict[str, object] = {
        "concept": _CONCEPT,
        "target_metric_key": "revenue",
        "relation": "exact",
        "scope_kind": "global",
        "method": "curated",
        "created_by": "human:proposer",
        "rationale": "standard taxonomy sales total",
        "evidence": _evidence(),
    }
    payload.update(overrides)
    return MappingAssertionCreate.model_validate(payload)


def _accept(**overrides: object) -> MappingAssertionRevision:
    payload: dict[str, object] = {
        "method": "human_review",
        "created_by": "human:reviewer",
        "rationale": "reviewed labels and presentation",
        "evidence": _evidence(),
    }
    payload.update(overrides)
    return MappingAssertionRevision.model_validate(payload)


def test_propose_accept_preserves_candidate_row(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _write_metrics(tmp_path / "reg", _metric_dicts("revenue"))
    service = _seed(engine, registry_dir)
    candidate_id = service.propose_mapping(_create())
    accepted_id = service.accept_mapping(candidate_id, _accept())
    assert accepted_id != candidate_id
    with engine.connect() as conn:
        candidate = (
            conn.execute(
                select(reg.registry_mapping_assertion).where(
                    reg.registry_mapping_assertion.c.id == candidate_id
                )
            )
            .mappings()
            .one()
        )
        accepted = (
            conn.execute(
                select(reg.registry_mapping_assertion).where(
                    reg.registry_mapping_assertion.c.id == accepted_id
                )
            )
            .mappings()
            .one()
        )
    assert candidate["status"] == "candidate"
    assert accepted["status"] == "accepted"
    assert accepted["supersedes_id"] == candidate_id
    assert accepted["target_definition_hash"] == candidate["target_definition_hash"]
    assert accepted["source_concept_id"] == candidate["source_concept_id"]


def test_reject_then_cannot_revise(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _write_metrics(tmp_path / "reg", _metric_dicts("revenue"))
    service = _seed(engine, registry_dir)
    candidate_id = service.propose_mapping(_create())
    rejected_id = service.reject_mapping(
        candidate_id,
        MappingAssertionRevision.model_validate(
            {
                "method": "human_review",
                "created_by": "human:reviewer",
                "rationale": "wrong concept",
            }
        ),
    )
    with pytest.raises(MappingDecisionError, match="terminal"):
        service.reject_mapping(
            rejected_id,
            MappingAssertionRevision.model_validate(
                {
                    "method": "human_review",
                    "created_by": "human:reviewer",
                    "rationale": "again",
                }
            ),
        )
    with pytest.raises(MappingDecisionError, match="not the current"):
        service.accept_mapping(candidate_id, _accept())


def test_accept_requires_evidence(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _write_metrics(tmp_path / "reg", _metric_dicts("revenue"))
    service = _seed(engine, registry_dir)
    candidate_id = service.propose_mapping(_create())
    with pytest.raises(MappingDecisionError, match="evidence"):
        service.accept_mapping(
            candidate_id,
            MappingAssertionRevision.model_validate(
                {
                    "method": "human_review",
                    "created_by": "human:reviewer",
                    "rationale": "looks fine",
                    "evidence": [],
                }
            ),
        )
    with engine.connect() as conn:
        count = conn.execute(select(reg.registry_mapping_assertion.c.id)).all()
    assert len(count) == 1


def test_accept_fails_when_yaml_definition_changed(engine: Engine, tmp_path: Path) -> None:
    metrics = _metric_dicts("revenue")
    registry_dir = _write_metrics(tmp_path / "reg", metrics)
    service = _seed(engine, registry_dir)
    candidate_id = service.propose_mapping(_create())
    original = load_metrics_yml(registry_dir / "metrics.yml").metrics[0]
    original_hash = definition_hash(original)
    changed = original.model_dump(mode="json")
    changed["definition"] = "A subsequently broadened revenue contract."
    _write_metrics(tmp_path / "reg", [changed])
    service.sync_canonical_metrics()
    with pytest.raises(MetricDefinitionChangedError, match="changed since proposal"):
        service.accept_mapping(candidate_id, _accept())
    rejected_id = service.reject_mapping(
        candidate_id,
        MappingAssertionRevision.model_validate(
            {
                "method": "human_review",
                "created_by": "human:reviewer",
                "rationale": "definition moved; re-propose against current hash",
            }
        ),
    )
    with engine.connect() as conn:
        rejected = (
            conn.execute(
                select(reg.registry_mapping_assertion).where(
                    reg.registry_mapping_assertion.c.id == rejected_id
                )
            )
            .mappings()
            .one()
        )
    assert rejected["target_definition_hash"] == original_hash
    assert rejected["target_definition_hash"] != definition_hash(
        load_metrics_yml(registry_dir / "metrics.yml").metrics[0]
    )


def test_conflicting_exact_rejected_including_stale_hash(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _write_metrics(tmp_path / "reg", _metric_dicts("revenue", "operating_income"))
    service = _seed(engine, registry_dir)
    first = service.propose_mapping(_create())
    service.accept_mapping(first, _accept())
    dumped = _dump_dir_metrics(registry_dir)
    for item in dumped:
        if item["key"] == "revenue":
            item["definition"] = "Changed revenue definition after acceptance."
    _write_metrics(tmp_path / "reg", dumped)
    service.sync_canonical_metrics()
    second = service.propose_mapping(_create(target_metric_key="operating_income"))
    with pytest.raises(ConflictingExactMappingError):
        service.accept_mapping(second, _accept())


def test_propose_fails_when_concept_missing(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _write_metrics(tmp_path / "reg", _metric_dicts("revenue"))
    service = _service(engine, registry_dir)
    service.sync_canonical_metrics()
    with pytest.raises(ConceptNotFoundError, match="source concept not found"):
        service.propose_mapping(_create())


def test_unsynced_mirror_rejects_propose_and_accept(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _write_metrics(tmp_path / "reg", _metric_dicts("revenue"))
    service = _seed(engine, registry_dir)
    dumped = _dump_dir_metrics(registry_dir)
    dumped[0]["name"] = "Renamed Revenue Without Sync"
    _write_metrics(tmp_path / "reg", dumped)
    with pytest.raises(RegistryOutOfSyncError, match="registry out of sync"):
        service.propose_mapping(_create())

    _write_metrics(tmp_path / "reg", _metric_dicts("revenue"))
    candidate_id = service.propose_mapping(_create())
    dumped = _dump_dir_metrics(registry_dir)
    dumped[0]["name"] = "Renamed Revenue Without Sync"
    _write_metrics(tmp_path / "reg", dumped)
    with pytest.raises(RegistryOutOfSyncError, match="registry out of sync"):
        service.accept_mapping(candidate_id, _accept())
    with engine.connect() as conn:
        statuses = [row[0] for row in conn.execute(select(reg.registry_mapping_assertion.c.status))]
    assert statuses == ["candidate"]


def test_duplicate_exact_same_metric_conflicts(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _write_metrics(tmp_path / "reg", _metric_dicts("revenue"))
    service = _seed(engine, registry_dir)
    first = service.propose_mapping(_create())
    service.accept_mapping(first, _accept())
    second = service.propose_mapping(_create())
    with pytest.raises(ConflictingExactMappingError):
        service.accept_mapping(second, _accept())


def test_cannot_branch_revision(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _write_metrics(tmp_path / "reg", _metric_dicts("revenue"))
    service = _seed(engine, registry_dir)
    candidate_id = service.propose_mapping(_create())
    service.accept_mapping(candidate_id, _accept())
    with pytest.raises(MappingDecisionError, match="not the current"):
        service.reject_mapping(
            candidate_id,
            MappingAssertionRevision.model_validate(
                {
                    "method": "human_review",
                    "created_by": "human:reviewer",
                    "rationale": "branch",
                }
            ),
        )
