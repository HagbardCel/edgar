"""CLI JSON payload includes arelle_version from the projection result."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from edgar.cli import app
from edgar.db.semantic import SemanticProjectionResult
from edgar.projection.semantic import ProjectPublishedBundleResult


def test_project_json_emits_arelle_version(monkeypatch) -> None:  # noqa: ANN001
    expected = SemanticProjectionResult(
        projection_id=7,
        attempt_id=9,
        status="complete",
        reused=False,
        counts={
            "facts": 2,
            "concept_declarations": 1,
            "contexts": 1,
            "units": 1,
            "relationships": 0,
            "issues": 0,
        },
        arelle_version="arelle-test-1.2.3",
    )

    def fake_project(self, bundle_dir: Path) -> ProjectPublishedBundleResult:  # noqa: ANN001
        return ProjectPublishedBundleResult(
            accession="0000000001-00-000001",
            bundle_id=1,
            report_input_id=2,
            projection=expected,
        )

    monkeypatch.setattr(
        "edgar.cli.SemanticProjectionService.project_published_bundle",
        fake_project,
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["xbrl", "project", "--bundle-dir", "/tmp/fake-bundle", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["arelle_version"] == expected.arelle_version
    assert payload["arelle_version"] is not None
