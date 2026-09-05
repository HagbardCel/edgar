"""CLI contract tests for metrics/mappings commands."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from edgar.cli import app
from tests.unit.registry.test_canonical_metrics import EXPECTED_CANONICAL_METRIC_KEYS

runner = CliRunner()


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


def test_mappings_explain_is_removed() -> None:
    result = runner.invoke(app, ["mappings", "explain", "map-test-equivalent"])
    assert result.exit_code != 0


def test_mappings_export_unsupported_format_exits_nonzero() -> None:
    result = runner.invoke(app, ["mappings", "export", "--format", "xml"])
    assert result.exit_code == 1
    assert "unsupported format" in result.output
