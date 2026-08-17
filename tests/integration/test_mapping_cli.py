"""CLI tests for the mapping decision ledger."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import Engine, create_engine, func, select
from typer.testing import CliRunner

from edgar.cli import app
from edgar.db import registry_schema as reg
from edgar.registry.export import dump_json, dump_jsonl, dump_markdown
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


def _seed(engine: Engine, tmp_path: Path) -> Path:
    registry_dir = _write_metrics(tmp_path / "reg", _metric_dicts("revenue"))
    result = runner.invoke(app, ["registry", "sync", "--registry-dir", str(registry_dir)])
    assert result.exit_code == 0, result.output
    seed_mapping_source_corpus(engine, tmp_path / "data")
    return registry_dir


def _evidence_file(path: Path) -> Path:
    payload = [
        {
            "kind": "label",
            "summary": "Primary English label",
            "data": {"role": "http://www.xbrl.org/2003/role/label", "text": "Net Sales"},
            "accessions": [ACCESSION_A_2024],
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _rationale_file(path: Path, text: str = "reviewed labels and presentation") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _assertion_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                select(func.count()).select_from(reg.registry_mapping_assertion)
            ).scalar_one()
        )


def _propose(registry_dir: Path, tmp_path: Path) -> int:
    rationale = _rationale_file(tmp_path / "rationale.txt", "standard taxonomy sales total")
    evidence = _evidence_file(tmp_path / "evidence.json")
    result = runner.invoke(
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
    assert result.exit_code == 0, result.output
    return int(result.output.strip().rsplit(" ", 1)[-1])


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<ts>" if key == "created_at" else _normalize(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def test_accept_missing_evidence_does_not_mutate(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _seed(engine, tmp_path)
    candidate_id = _propose(registry_dir, tmp_path)
    rationale = _rationale_file(tmp_path / "accept.txt")
    before = _assertion_count(engine)
    result = runner.invoke(
        app,
        [
            "mappings",
            "accept",
            str(candidate_id),
            "--created-by",
            "human:reviewer",
            "--rationale",
            str(rationale),
            "--registry-dir",
            str(registry_dir),
        ],
    )
    assert result.exit_code == 1
    assert "evidence" in result.output
    assert _assertion_count(engine) == before


def test_accept_stale_mirror_does_not_mutate(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _seed(engine, tmp_path)
    candidate_id = _propose(registry_dir, tmp_path)
    dumped = _metric_dicts("revenue")
    dumped[0]["name"] = "Renamed Without Sync"
    _write_metrics(registry_dir, dumped)
    rationale = _rationale_file(tmp_path / "accept.txt")
    evidence = _evidence_file(tmp_path / "accept.json")
    before = _assertion_count(engine)
    result = runner.invoke(
        app,
        [
            "mappings",
            "accept",
            str(candidate_id),
            "--created-by",
            "human:reviewer",
            "--rationale",
            str(rationale),
            "--evidence",
            str(evidence),
            "--registry-dir",
            str(registry_dir),
        ],
    )
    assert result.exit_code == 1
    assert "registry out of sync" in result.output
    assert _assertion_count(engine) == before


def test_accept_after_definition_change_does_not_mutate(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _seed(engine, tmp_path)
    candidate_id = _propose(registry_dir, tmp_path)
    dumped = _metric_dicts("revenue")
    dumped[0]["definition"] = "Changed after proposal."
    _write_metrics(registry_dir, dumped)
    sync = runner.invoke(app, ["registry", "sync", "--registry-dir", str(registry_dir)])
    assert sync.exit_code == 0, sync.output
    rationale = _rationale_file(tmp_path / "accept.txt")
    evidence = _evidence_file(tmp_path / "accept.json")
    before = _assertion_count(engine)
    result = runner.invoke(
        app,
        [
            "mappings",
            "accept",
            str(candidate_id),
            "--created-by",
            "human:reviewer",
            "--rationale",
            str(rationale),
            "--evidence",
            str(evidence),
            "--registry-dir",
            str(registry_dir),
        ],
    )
    assert result.exit_code == 1
    assert "changed since proposal" in result.output
    assert _assertion_count(engine) == before


def test_show_named_revision_and_export_formats(engine: Engine, tmp_path: Path) -> None:
    registry_dir = _seed(engine, tmp_path)
    candidate_id = _propose(registry_dir, tmp_path)
    rationale = _rationale_file(tmp_path / "accept.txt")
    evidence = _evidence_file(tmp_path / "accept.json")
    accept = runner.invoke(
        app,
        [
            "mappings",
            "accept",
            str(candidate_id),
            "--created-by",
            "human:reviewer",
            "--rationale",
            str(rationale),
            "--evidence",
            str(evidence),
            "--registry-dir",
            str(registry_dir),
        ],
    )
    assert accept.exit_code == 0, accept.output
    accepted_id = int(accept.output.split("accepted mapping assertion ", 1)[1].split(" ", 1)[0])
    shown = runner.invoke(
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
    assert shown.exit_code == 0, shown.output
    payload = json.loads(shown.output)
    assert payload["mapping"]["id"] == candidate_id
    assert payload["mapping"]["status"] == "candidate"
    assert payload["is_current"] is False
    assert payload["current_revision_id"] == accepted_id
    listed = runner.invoke(app, ["mappings", "list", "--json", "--registry-dir", str(registry_dir)])
    assert listed.exit_code == 0, listed.output
    listed_payload = json.loads(listed.output)
    assert listed_payload["count"] == 1
    assert listed_payload["assertions"][0]["id"] == accepted_id
    exported = runner.invoke(
        app, ["mappings", "export", "--format", "json", "--registry-dir", str(registry_dir)]
    )
    assert exported.exit_code == 0, exported.output
    export_payload = json.loads(exported.output)
    assert export_payload["count"] == 1
    assert export_payload["assertions"][0]["history"][0]["id"] == candidate_id
    assert "affected_facts" in export_payload["assertions"][0]
    assert export_payload["assertions"][0]["affected_facts"] == []
    jsonl = runner.invoke(
        app, ["mappings", "export", "--format", "jsonl", "--registry-dir", str(registry_dir)]
    )
    assert jsonl.exit_code == 0, jsonl.output
    lines = [line for line in jsonl.output.splitlines() if line]
    assert len(lines) == 1
    markdown = runner.invoke(
        app, ["mappings", "export", "--format", "markdown", "--registry-dir", str(registry_dir)]
    )
    assert markdown.exit_code == 0, markdown.output
    assert "# Mapping assertions" in markdown.output
    assert "accepted" in markdown.output
    from edgar.config import Settings
    from edgar.registry.service import RegistryService

    reports = RegistryService(
        Settings(), engine=engine, registry_dir=registry_dir
    ).export_mappings()
    assert _normalize(json.loads(dump_json(reports))) == _normalize(export_payload)
    assert dump_jsonl(reports) == jsonl.output
    assert dump_markdown(reports) == markdown.output
