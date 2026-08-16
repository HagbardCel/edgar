"""CLI contract tests for metrics/mappings commands."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from edgar.cli import app
from edgar.metrics.registry import EXPECTED_V1_METRICS

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_DIR = _REPO_ROOT / "semantic-registry"
runner = CliRunner()


def _empty_registry(tmp_path: Path) -> Path:
    dest = tmp_path / "empty-registry"
    dest.mkdir()
    shutil.copy2(_REGISTRY_DIR / "metric-families.json", dest / "metric-families.json")
    shutil.copy2(_REGISTRY_DIR / "metric-definitions.json", dest / "metric-definitions.json")
    (dest / "mapping-rules.json").write_text('{"rules": []}\n', encoding="utf-8")
    return dest


def test_metrics_list_json_includes_registry_hash_and_v1_set() -> None:
    result = runner.invoke(app, ["metrics", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["registry_hash"]
    assert payload["count"] == 20
    codes = {row["metric_code"] for row in payload["metrics"]}
    assert codes == EXPECTED_V1_METRICS


def test_metrics_show_json_includes_full_contract() -> None:
    result = runner.invoke(
        app,
        ["metrics", "show", "operating_company_revenue", "--version", "1", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["registry_hash"]
    assert payload["count"] == 1
    definition = payload["definitions"][0]
    assert definition["metric_code"] == "operating_company_revenue"
    assert definition["economic_definition"]
    assert definition["constraints"]["inclusion_rules"]


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
