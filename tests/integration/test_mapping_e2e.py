"""Constructed-fixture E2E for the Phase 2C mapping ledger."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from sqlalchemy import Engine, create_engine, func, select
from typer.testing import CliRunner

from edgar.cli import app
from edgar.db import registry_schema as reg
from edgar.db import source_schema as src
from edgar.registry.loader import load_metrics_yml
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables
from tests.helpers.mapping_source_fixture import (
    ACCESSION_A_2024,
    SALES_QNAME,
    seed_mapping_source_corpus,
)

pytestmark = pytest.mark.database

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_YML = _REPO_ROOT / "registry" / "metrics.yml"
runner = CliRunner()


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


@pytest.fixture(autouse=True)
def database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDGAR_DATABASE_URL", test_database_url())


def _write_metrics(directory: Path) -> Path:
    metrics = [
        m.model_dump(mode="json")
        for m in load_metrics_yml(_PRODUCTION_YML).metrics
        if m.key == "revenue"
    ]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metrics.yml").write_text(
        yaml.safe_dump({"metrics": metrics}, sort_keys=False), encoding="utf-8"
    )
    return directory


def test_constructed_fixture_answers_dod_questions(engine: Engine, tmp_path: Path) -> None:
    """Validate → sync → propose → show → accept → show --include-facts → export.

    The twelve DoD questions:

    1. Does YAML validate?
    2. Does sync populate the canonical_metric mirror?
    3. Does propose snapshot the current YAML definition hash?
    4. Does show of the candidate name that revision (current candidate)?
    5. Does accept insert a successor without updating the candidate?
    6. Is the accepted revision current?
    7. Does show --include-facts return every qualifying occurrence?
    8. Is definition_changed false when hashes match?
    9. Does export include the current accepted assertion?
    10. Does export history include the superseded candidate?
    11. Is the source concept the Clark QName?
    12. Are source.concept rows left unmutated by registry writes?
    """
    registry_dir = _write_metrics(tmp_path / "reg")
    with engine.connect() as conn:
        concepts_before = int(
            conn.execute(select(func.count()).select_from(src.source_concept)).scalar_one()
        )

    validate = runner.invoke(app, ["registry", "validate", "--registry-dir", str(registry_dir)])
    assert validate.exit_code == 0, validate.output
    assert "metrics=1" in validate.output
    assert "semantic_registry_hash=" in validate.output

    sync = runner.invoke(app, ["registry", "sync", "--registry-dir", str(registry_dir)])
    assert sync.exit_code == 0, sync.output
    with engine.connect() as conn:
        keys = [row[0] for row in conn.execute(select(reg.registry_canonical_metric.c.key))]
    assert keys == ["revenue"]

    seed_mapping_source_corpus(engine, tmp_path / "data")
    with engine.connect() as conn:
        concepts_after_seed = int(
            conn.execute(select(func.count()).select_from(src.source_concept)).scalar_one()
        )
    assert concepts_after_seed > concepts_before

    rationale = tmp_path / "rationale.txt"
    rationale.write_text("standard taxonomy sales total", encoding="utf-8")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            [
                {
                    "kind": "label",
                    "summary": "Primary English label",
                    "data": {"text": "Net Sales"},
                    "accessions": [ACCESSION_A_2024],
                }
            ]
        ),
        encoding="utf-8",
    )
    propose = runner.invoke(
        app,
        [
            "mappings",
            "propose",
            "--concept",
            SALES_QNAME,
            "--metric",
            "revenue",
            "--relation",
            "exact",
            "--method",
            "curated",
            "--created-by",
            "human:proposer",
            "--rationale",
            str(rationale),
            "--evidence",
            str(evidence),
            "--registry-dir",
            str(registry_dir),
        ],
    )
    assert propose.exit_code == 0, propose.output
    candidate_id = int(propose.output.strip().rsplit(" ", 1)[-1])

    shown_candidate = runner.invoke(
        app,
        [
            "mappings",
            "show",
            str(candidate_id),
            "--format",
            "json",
            "--registry-dir",
            str(registry_dir),
        ],
    )
    assert shown_candidate.exit_code == 0, shown_candidate.output
    candidate_report = json.loads(shown_candidate.output)
    assert candidate_report["mapping"]["id"] == candidate_id
    assert candidate_report["mapping"]["status"] == "candidate"
    assert candidate_report["is_current"] is True
    yaml_hash = candidate_report["yaml_definition_hash"]
    assert candidate_report["mapping"]["target_definition_hash"] == yaml_hash

    accept_rationale = tmp_path / "accept.txt"
    accept_rationale.write_text("reviewed labels and presentation", encoding="utf-8")
    accept = runner.invoke(
        app,
        [
            "mappings",
            "accept",
            str(candidate_id),
            "--created-by",
            "human:reviewer",
            "--rationale",
            str(accept_rationale),
            "--evidence",
            str(evidence),
            "--registry-dir",
            str(registry_dir),
        ],
    )
    assert accept.exit_code == 0, accept.output
    accepted_id = int(accept.output.split("accepted mapping assertion ", 1)[1].split(" ", 1)[0])
    assert accepted_id != candidate_id
    with engine.connect() as conn:
        candidate_status = conn.execute(
            select(reg.registry_mapping_assertion.c.status).where(
                reg.registry_mapping_assertion.c.id == candidate_id
            )
        ).scalar_one()
    assert candidate_status == "candidate"

    shown_facts = runner.invoke(
        app,
        [
            "mappings",
            "show",
            str(accepted_id),
            "--include-facts",
            "--format",
            "json",
            "--registry-dir",
            str(registry_dir),
        ],
    )
    assert shown_facts.exit_code == 0, shown_facts.output
    accepted_report = json.loads(shown_facts.output)
    assert accepted_report["mapping"]["id"] == accepted_id
    assert accepted_report["mapping"]["status"] == "accepted"
    assert accepted_report["is_current"] is True
    assert accepted_report["definition_changed"] is False
    assert accepted_report["source_concept"]["clark_qname"] == SALES_QNAME
    assert accepted_report["affected_fact_summary"]["count"] == 6
    assert len(accepted_report["affected_facts"]) == 6
    assert accepted_report["affected_fact_summary"]["truncated"] is False

    exported = runner.invoke(
        app, ["mappings", "export", "--format", "json", "--registry-dir", str(registry_dir)]
    )
    assert exported.exit_code == 0, exported.output
    export_payload = json.loads(exported.output)
    assert export_payload["count"] == 1
    current = export_payload["assertions"][0]
    assert current["mapping"]["id"] == accepted_id
    assert [item["id"] for item in current["history"]] == [candidate_id, accepted_id]

    with engine.connect() as conn:
        concepts_final = int(
            conn.execute(select(func.count()).select_from(src.source_concept)).scalar_one()
        )
    assert concepts_final == concepts_after_seed
