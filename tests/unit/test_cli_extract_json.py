"""CLI smoke tests for filings extract."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from edgar.cli import app
from edgar.db.source import PersistExtractionResult
from edgar.ingestion.source_extract import SourceExtractResult


def test_legacy_project_commands_removed() -> None:
    runner = CliRunner()
    xbrl = runner.invoke(app, ["xbrl", "project", "--bundle-dir", "/tmp/fake"])
    assert xbrl.exit_code != 0
    docs = runner.invoke(app, ["documents", "project", "--bundle-dir", "/tmp/fake"])
    assert docs.exit_code != 0


def test_filings_extract_json(monkeypatch) -> None:  # noqa: ANN001
    def fake_extract(self, bundle_dir: Path) -> SourceExtractResult:  # noqa: ANN001
        return SourceExtractResult(
            accession="0001065088-24-000036",
            opaque_id="a" * 32,
            filing_id=7,
            catalog_reused=False,
            document_count=3,
            persist=PersistExtractionResult(
                filing_id=7,
                report_ids=(11,),
                fact_count=42,
                block_count=10,
                section_count=2,
                issue_count=1,
                concept_upsert_count=5,
            ),
        )

    monkeypatch.setattr(
        "edgar.cli.SourceExtractService.extract_published_bundle",
        fake_extract,
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["filings", "extract", "--bundle-dir", "/tmp/fake-bundle", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["filing_id"] == 7
    assert payload["fact_count"] == 42
    assert payload["block_count"] == 10
    assert payload["section_count"] == 2
