"""Unit gate: Alembic revisions must not import live application metadata."""

from __future__ import annotations

from pathlib import Path

_VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_REVISION_0001 = _VERSIONS / "0001_source_v2.py"
_REVISION_0002 = _VERSIONS / "0002_registry.py"


def test_0001_source_v2_does_not_import_live_metadata() -> None:
    text = _REVISION_0001.read_text(encoding="utf-8")
    assert "edgar.db.source_schema" not in text
    assert "SOURCE_TABLES" not in text
    assert "op.create_table(" in text
    assert "CREATE SCHEMA IF NOT EXISTS source" in text


def test_0002_registry_does_not_import_live_metadata() -> None:
    text = _REVISION_0002.read_text(encoding="utf-8")
    assert "edgar.db.registry_schema" not in text
    assert "REGISTRY_TABLES" not in text
    assert "op.create_table(" in text
    assert "CREATE SCHEMA IF NOT EXISTS registry" in text
    assert 'down_revision: str | Sequence[str] | None = "0001_source_v2"' in text
