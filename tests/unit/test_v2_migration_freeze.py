"""Unit gate: Alembic revisions must not import live application metadata."""

from __future__ import annotations

from pathlib import Path

_VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_REVISION_0001 = _VERSIONS / "0001_source_v2.py"
_REVISION_0002 = _VERSIONS / "0002_registry.py"
_REVISION_0003 = _VERSIONS / "0003_m1a_extraction_receipt.py"
_REVISION_0004 = _VERSIONS / "0004_m1a_network_identity.py"


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


def test_0003_m1a_extraction_receipt_does_not_import_live_metadata() -> None:
    text = _REVISION_0003.read_text(encoding="utf-8")
    assert "edgar.db.source_schema" not in text
    assert "SOURCE_TABLES" not in text
    assert "extraction_receipt" in text
    assert 'down_revision: str | Sequence[str] | None = "0002_registry"' in text
    assert "op.add_column(" in text


def test_0004_m1a_network_identity_does_not_import_live_metadata() -> None:
    text = _REVISION_0004.read_text(encoding="utf-8")
    assert "edgar.db.source_schema" not in text
    assert "SOURCE_TABLES" not in text
    assert 'down_revision: str | Sequence[str] | None = "0003_m1a_extraction_receipt"' in text
    assert "op.add_column(" in text
    assert "ck_source_relationship_link_arc_qname" in text
    assert "ck_source_concept_label_link_arc_qname" in text
    assert "ck_source_concept_reference_link_arc_qname" in text
    assert "op.drop_constraint(" in text
    assert "op.drop_column(" in text
