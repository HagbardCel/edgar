"""Integration tests for mapping inspection, history, and affected facts."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import Engine, create_engine

from edgar.config import Settings
from edgar.registry.hashing import definition_hash
from edgar.registry.loader import load_metrics_yml
from edgar.registry.mapping import (
    MappingAssertionCreate,
    MappingAssertionRevision,
    MappingEvidenceItem,
)
from edgar.registry.service import RegistryService
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables
from tests.helpers.mapping_source_fixture import (
    ACCESSION_A_2023,
    ACCESSION_A_2024,
    ACCESSION_A_UNDATED,
    ACCESSION_B_2024,
    ISSUER_A,
    SALES_QNAME,
    seed_mapping_source_corpus,
)

pytestmark = pytest.mark.database

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_YML = _REPO_ROOT / "registry" / "metrics.yml"


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


def _evidence() -> tuple[MappingEvidenceItem, ...]:
    return (
        MappingEvidenceItem(
            kind="label",
            summary="Primary English label",
            data={"role": "http://www.xbrl.org/2003/role/label", "text": "Net Sales"},
            accessions=(ACCESSION_A_2024,),
        ),
    )


def _service(engine: Engine, registry_dir: Path) -> RegistryService:
    return RegistryService(_settings(), engine=engine, registry_dir=registry_dir)


def _seed_registry(engine: Engine, tmp_path: Path) -> tuple[RegistryService, Path]:
    registry_dir = _write_metrics(tmp_path / "reg", _metric_dicts("revenue"))
    service = _service(engine, registry_dir)
    service.sync_canonical_metrics()
    seed_mapping_source_corpus(engine, tmp_path / "data")
    return service, registry_dir


def _propose(
    service: RegistryService,
    **overrides: object,
) -> int:
    payload: dict[str, object] = {
        "concept": SALES_QNAME,
        "target_metric_key": "revenue",
        "relation": "exact",
        "scope_kind": "global",
        "method": "curated",
        "created_by": "human:proposer",
        "rationale": "standard taxonomy sales total",
        "evidence": _evidence(),
    }
    payload.update(overrides)
    return service.propose_mapping(MappingAssertionCreate.model_validate(payload))


def _accept() -> MappingAssertionRevision:
    return MappingAssertionRevision.model_validate(
        {
            "method": "human_review",
            "created_by": "human:reviewer",
            "rationale": "reviewed labels and presentation",
            "evidence": _evidence(),
        }
    )


def test_global_mapping_returns_every_occurrence(engine: Engine, tmp_path: Path) -> None:
    service, _registry_dir = _seed_registry(engine, tmp_path)
    assertion_id = _propose(service)
    facts = service.affected_facts(assertion_id)
    accessions = [fact.accession for fact in facts]
    assert ACCESSION_A_2023 in accessions
    assert ACCESSION_A_2024 in accessions
    assert ACCESSION_B_2024 in accessions
    assert ACCESSION_A_UNDATED in accessions
    assert len(facts) == 6
    a2024 = [fact for fact in facts if fact.accession == ACCESSION_A_2024]
    assert len(a2024) == 3
    assert any(fact.dimensions for fact in a2024)
    assert any(not fact.dimensions for fact in a2024)


def test_issuer_scope_excludes_other_issuer(engine: Engine, tmp_path: Path) -> None:
    service, _registry_dir = _seed_registry(engine, tmp_path)
    assertion_id = _propose(service, scope_kind="issuer", issuer_cik=ISSUER_A)
    facts = service.affected_facts(assertion_id)
    assert {fact.issuer_cik for fact in facts} == {ISSUER_A}
    assert ACCESSION_B_2024 not in {fact.accession for fact in facts}
    assert len(facts) == 5


def test_half_bounded_interval_excludes_earlier_and_undated(engine: Engine, tmp_path: Path) -> None:
    service, _registry_dir = _seed_registry(engine, tmp_path)
    assertion_id = _propose(service, valid_from=date(2024, 1, 1))
    facts = service.affected_facts(assertion_id)
    accessions = {fact.accession for fact in facts}
    assert ACCESSION_A_2023 not in accessions
    assert ACCESSION_A_UNDATED not in accessions
    assert ACCESSION_A_2024 in accessions
    assert ACCESSION_B_2024 in accessions


def test_show_named_revision_not_current_tip(engine: Engine, tmp_path: Path) -> None:
    service, _registry_dir = _seed_registry(engine, tmp_path)
    candidate_id = _propose(service)
    accepted_id = service.accept_mapping(candidate_id, _accept())
    rejected_id = service.reject_mapping(
        accepted_id,
        MappingAssertionRevision.model_validate(
            {
                "method": "human_review",
                "created_by": "human:reviewer",
                "rationale": "revoked after definition review",
            }
        ),
    )
    report = service.get_mapping(accepted_id)
    assert report.mapping.id == accepted_id
    assert report.mapping.status == "accepted"
    assert report.is_current is False
    assert report.current_revision_id == rejected_id
    assert [item.id for item in report.history] == [candidate_id, accepted_id, rejected_id]
    listed = service.list_mappings()
    assert [item.id for item in listed] == [rejected_id]
    assert listed[0].status == "rejected"


def test_list_includes_candidates(engine: Engine, tmp_path: Path) -> None:
    service, _registry_dir = _seed_registry(engine, tmp_path)
    candidate_id = _propose(service)
    listed = service.list_mappings()
    assert [item.id for item in listed] == [candidate_id]
    assert listed[0].status == "candidate"
    accepted_only = service.list_mappings(status="accepted")
    assert accepted_only == []


def test_definition_changed_when_yaml_hash_moves(engine: Engine, tmp_path: Path) -> None:
    service, registry_dir = _seed_registry(engine, tmp_path)
    candidate_id = _propose(service)
    accepted_id = service.accept_mapping(candidate_id, _accept())
    original = load_metrics_yml(registry_dir / "metrics.yml").metrics[0]
    changed = original.model_dump(mode="json")
    changed["definition"] = "Broadened revenue contract after acceptance."
    _write_metrics(registry_dir, [changed])
    service.sync_canonical_metrics()
    report = service.get_mapping(accepted_id)
    assert report.definition_changed is True
    assert report.mapping.target_definition_hash == definition_hash(original)
    assert report.yaml_definition_hash == definition_hash(
        load_metrics_yml(registry_dir / "metrics.yml").metrics[0]
    )
    assert report.mapping.target_definition_hash != report.yaml_definition_hash


def test_affected_facts_are_deterministically_ordered(engine: Engine, tmp_path: Path) -> None:
    service, _registry_dir = _seed_registry(engine, tmp_path)
    assertion_id = _propose(service)
    facts = service.affected_facts(assertion_id)
    keys = [
        (
            fact.accession,
            fact.report_period_end is None,
            fact.report_period_end,
            fact.source_document,
            fact.source_locator["value"] if fact.source_locator else "",
            fact.fact_id,
        )
        for fact in facts
    ]
    assert keys == sorted(keys)
    a2024 = [fact for fact in facts if fact.accession == ACCESSION_A_2024]
    assert [fact.source_document for fact in a2024] == sorted(
        fact.source_document or "" for fact in a2024
    )
    accessions = [fact.accession for fact in facts]
    assert accessions == sorted(accessions)
