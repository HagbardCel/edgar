"""Unit gate: revision 0001_source_v2 must not import live application metadata."""

from __future__ import annotations

from pathlib import Path

_REVISION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0001_source_v2.py"


def test_0001_source_v2_does_not_import_live_metadata() -> None:
    text = _REVISION.read_text(encoding="utf-8")
    assert "edgar.db.source_schema" not in text
    assert "SOURCE_TABLES" not in text
    assert "op.create_table(" in text
    assert "CREATE SCHEMA IF NOT EXISTS source" in text
