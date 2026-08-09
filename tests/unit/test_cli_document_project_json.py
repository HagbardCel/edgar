"""CLI JSON smoke tests for documents project (service monkeypatched)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from edgar.cli import app
from edgar.db.document import DocumentProjectionResult
from edgar.projection.document import ProjectDocumentResult


def test_documents_project_json(monkeypatch) -> None:
    def fake_project(self, bundle_dir: Path, *, artifact_path: str | None = None):
        return ProjectDocumentResult(
            accession="0000000000-00-000001",
            bundle_id=1,
            filing_document_id=2,
            artifact_path="accession/primary.htm",
            projection=DocumentProjectionResult(
                projection_id=3,
                attempt_id=4,
                status="complete",
                reused=False,
                counts={"blocks": 10, "sections": 2, "issues": 0},
            ),
        )

    monkeypatch.setattr(
        "edgar.projection.document.DocumentProjectionService.project_published_bundle",
        fake_project,
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["documents", "project", "--bundle-dir", "/tmp/fake", "--json"],
    )
    assert result.exit_code == 0
    assert '"projection_id": 3' in result.stdout
    assert '"block_count": 10' in result.stdout
