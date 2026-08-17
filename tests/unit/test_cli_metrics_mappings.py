"""CLI contract tests for metrics/mappings commands."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from edgar.cli import app
from tests.unit.registry.test_canonical_metrics import EXPECTED_CANONICAL_METRIC_KEYS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_REGISTRY_DIR = _REPO_ROOT / "semantic-registry"
runner = CliRunner()


def _empty_registry(tmp_path: Path) -> Path:
    dest = tmp_path / "empty-registry"
    dest.mkdir()
    shutil.copy2(_LEGACY_REGISTRY_DIR / "metric-families.json", dest / "metric-families.json")
    shutil.copy2(_LEGACY_REGISTRY_DIR / "metric-definitions.json", dest / "metric-definitions.json")
    (dest / "mapping-rules.json").write_text('{"rules": []}\n', encoding="utf-8")
    return dest


def test_registry_validate_prints_count_and_semantic_hash() -> None:
    result = runner.invoke(app, ["registry", "validate"])
    assert result.exit_code == 0, result.output
    assert "metrics=39" in result.output
    assert "semantic_registry_hash=" in result.output


def test_metrics_list_json_includes_semantic_hash_and_canonical_keys() -> None:
    result = runner.invoke(app, ["metrics", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["semantic_registry_hash"]
    assert payload["count"] == 39
    keys = {row["key"] for row in payload["metrics"]}
    assert keys == EXPECTED_CANONICAL_METRIC_KEYS


def test_metrics_show_json_includes_full_contract() -> None:
    result = runner.invoke(app, ["metrics", "show", "revenue", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["semantic_registry_hash"]
    assert payload["count"] == 1
    definition = payload["metrics"][0]
    assert definition["key"] == "revenue"
    assert definition["definition"]
    assert definition["includes"]
    assert definition["excludes"]
    assert definition["definition_hash"]


def test_metrics_show_unknown_metric_exits_nonzero() -> None:
    result = runner.invoke(app, ["metrics", "show", "not_a_metric"])
    assert result.exit_code == 1
    assert "unknown metric" in result.output


def test_mappings_list_json_includes_registry_hash() -> None:
    result = runner.invoke(app, ["mappings", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["registry_hash"]
    assert "count" in payload
    assert "rules" in payload


def test_mappings_export_json_empty_registry(tmp_path: Path) -> None:
    registry_dir = _empty_registry(tmp_path)
    result = runner.invoke(
        app,
        ["mappings", "export", "--format", "json", "--registry-dir", str(registry_dir)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["registry_hash"]
    assert payload["reports"] == []
    assert payload["count"] == 0


def test_mappings_export_markdown_empty_registry(tmp_path: Path) -> None:
    registry_dir = _empty_registry(tmp_path)
    result = runner.invoke(
        app,
        ["mappings", "export", "--format", "markdown", "--registry-dir", str(registry_dir)],
    )
    assert result.exit_code == 0, result.output
    assert "# Mapping audit ledger" in result.output
    assert "Registry hash:" in result.output
    assert "Rules: 0" in result.output
