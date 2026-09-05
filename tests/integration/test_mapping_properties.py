"""Hypothesis-backed mapping ledger properties against the constructed corpus."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, create_engine, select

from edgar.config import Settings
from edgar.db import registry_schema as reg
from edgar.registry.interval import interval_contains
from edgar.registry.loader import load_metrics_yml
from edgar.registry.mapping import (
    MappingAssertionCreate,
    MappingAssertionRevision,
    MappingEvidenceItem,
)
from edgar.registry.service import RegistryService
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables
from tests.helpers.mapping_source_fixture import (
    ACCESSION_A_2024,
    ISSUER_A,
    ISSUER_B,
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


def _service(engine: Engine, tmp_path: Path) -> RegistryService:
    metrics = [
        m.model_dump(mode="json")
        for m in load_metrics_yml(_PRODUCTION_YML).metrics
        if m.key == "revenue"
    ]
    registry_dir = tmp_path / "reg"
    registry_dir.mkdir(exist_ok=True)
    (registry_dir / "metrics.yml").write_text(
        yaml.safe_dump({"metrics": metrics}, sort_keys=False), encoding="utf-8"
    )
    settings = Settings().model_copy(update={"edgar_database_url": test_database_url()})
    service = RegistryService(settings, engine=engine, registry_dir=registry_dir)
    service.sync_canonical_metrics()
    seed_mapping_source_corpus(engine, tmp_path / "data")
    return service


def _evidence() -> tuple[MappingEvidenceItem, ...]:
    return (
        MappingEvidenceItem(
            kind="human_analysis",
            summary="reviewed",
            data={"text": "sales total"},
            accessions=(ACCESSION_A_2024,),
        ),
    )


def _propose(service: RegistryService, **overrides: object) -> int:
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


def _row(engine: Engine, assertion_id: int) -> dict[str, object]:
    with engine.connect() as conn:
        return dict(
            conn.execute(
                select(reg.registry_mapping_assertion).where(
                    reg.registry_mapping_assertion.c.id == assertion_id
                )
            )
            .mappings()
            .one()
        )


_RATIONALES = st.text(
    min_size=1,
    max_size=40,
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
)


@given(_RATIONALES)
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_accept_does_not_mutate_predecessor(engine: Engine, tmp_path: Path, rationale: str) -> None:
    with engine.begin() as conn:
        truncate_all_tables(conn)
    service = _service(engine, tmp_path)
    candidate_id = _propose(service)
    before = _row(engine, candidate_id)
    service.accept_mapping(
        candidate_id,
        MappingAssertionRevision.model_validate(
            {
                "method": "human_review",
                "created_by": "human:reviewer",
                "rationale": rationale.strip() or "reviewed",
                "evidence": _evidence(),
            }
        ),
    )
    after = _row(engine, candidate_id)
    assert after == before


def test_issuer_scope_never_returns_other_issuer_facts(engine: Engine, tmp_path: Path) -> None:
    service = _service(engine, tmp_path)
    assertion_id = _propose(service, scope_kind="issuer", issuer_cik=ISSUER_A)
    facts = service.affected_facts(assertion_id)
    assert facts
    assert all(fact.issuer_cik == ISSUER_A for fact in facts)
    assert ISSUER_B not in {fact.issuer_cik for fact in facts}


def test_n_source_facts_yield_n_affected_rows(engine: Engine, tmp_path: Path) -> None:
    service = _service(engine, tmp_path)
    assertion_id = _propose(service)
    row = _row(engine, assertion_id)
    facts = service.affected_facts(assertion_id)
    matching = [
        fact
        for fact in facts
        if interval_contains(
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            report_period_end=fact.report_period_end,
        )
    ]
    assert len(matching) == len(facts)
    assert len(facts) == 6
