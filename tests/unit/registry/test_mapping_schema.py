"""JSON Schema contract for MappingReport."""

from __future__ import annotations

from pathlib import Path

from edgar.registry.export import SCHEMA_RELATIVE_PATH, mapping_report_schema_text

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_committed_mapping_report_schema_matches_model() -> None:
    committed = (_REPO_ROOT / SCHEMA_RELATIVE_PATH).read_text(encoding="utf-8")
    assert committed == mapping_report_schema_text()
