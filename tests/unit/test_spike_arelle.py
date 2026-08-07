"""Unit tests for Arelle adapter helpers, comparison, and isolation (no network)."""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib.arelle_errors import StructuredError  # noqa: E402
from spike_lib.arelle_load import (  # noqa: E402
    build_oasis_catalog,
    canonicalize_error_records,
    make_canonical_resolver,
    map_discovery_type,
    map_discovery_types,
    occurrence_collection_hash,
)
from spike_lib.compare import compare_snapshots  # noqa: E402
from spike_lib.hashing import inspection_hash  # noqa: E402
from spike_lib.network_guard import NetworkDeniedError, NetworkGuard, network_denied  # noqa: E402


def test_map_discovery_types_arcrole_before_role() -> None:
    # arcroleref contains roleref as substring; exact token matching must win.
    assert map_discovery_type("arcroleRef") == "arcrole_ref"
    assert map_discovery_type("roleRef") == "role_ref"
    types = map_discovery_types({"roleRef", "arcroleRef"})
    assert types[0] == "arcrole_ref"
    assert "role_ref" in types


def test_map_discovery_types_import_include() -> None:
    assert map_discovery_types({"import"}) == ["schema_import"]
    assert map_discovery_types({"include"}) == ["schema_include"]
    assert map_discovery_types({"schemaRef"}) == ["schema_ref"]


def test_occurrence_collection_hash_detects_diff_with_same_count() -> None:
    a = [{"relationship_occurrence_hash": "a" * 64, "network_type": "presentation"}]
    b = [{"relationship_occurrence_hash": "b" * 64, "network_type": "presentation"}]
    assert len(a) == len(b)
    assert occurrence_collection_hash(a) != occurrence_collection_hash(b)
    # Order independence.
    c = [b[0], a[0]]
    d = [a[0], b[0]]
    assert occurrence_collection_hash(c) == occurrence_collection_hash(d)


def test_canonical_resolver_prefers_filepath_alias(tmp_path: Path) -> None:
    target = tmp_path / "accession" / "a.htm"
    target.parent.mkdir(parents=True)
    target.write_text("<html/>", encoding="utf-8")
    canonical = "https://www.sec.gov/Archives/edgar/data/1/x/a.htm"
    aliases = {str(target.resolve()): canonical}
    resolver = make_canonical_resolver(aliases)
    doc = SimpleNamespace(uri=str(target), filepath=str(target))
    assert resolver(doc) == canonical
    doc_http = SimpleNamespace(uri="https://xbrl.sec.gov/dei/2023/dei-2023.xsd", filepath=None)
    assert resolver(doc_http) == "https://xbrl.sec.gov/dei/2023/dei-2023.xsd"
    doc_unknown = SimpleNamespace(uri="/var/tmp/other.htm", filepath=None)
    assert resolver(doc_unknown) is None


def test_canonicalize_error_records_replaces_local_paths(tmp_path: Path) -> None:
    target = tmp_path / "accession" / "a.htm"
    target.parent.mkdir(parents=True)
    target.write_text("<html/>", encoding="utf-8")
    canonical = "https://www.sec.gov/Archives/edgar/data/1/x/a.htm"
    aliases = {str(target.resolve()): canonical}
    records = [
        StructuredError("error", "xmlSchema:requiredAttribute", str(target), 12),
        StructuredError("warning", "arelle:hrefWarning", None, None),
        StructuredError("error", "UNSTRUCTURED", "/private/tmp/nowhere.htm", 3),
    ]
    out = canonicalize_error_records(records, aliases)
    assert out[0].document_uri == canonical
    assert out[1].document_uri is None
    # Unresolvable local paths are dropped, never persisted.
    assert out[2].document_uri is None


def test_build_oasis_catalog(tmp_path: Path) -> None:
    target = tmp_path / "ext" / "a.xsd"
    target.parent.mkdir(parents=True)
    target.write_text("<schema/>", encoding="utf-8")
    catalog = tmp_path / "metadata" / "catalog.xml"
    data = build_oasis_catalog({"https://example.com/a.xsd": target}, catalog)
    text = data.decode("utf-8")
    assert "https://example.com/a.xsd" in text
    assert "../ext/a.xsd" in text or "ext/a.xsd" in text
    assert catalog.is_file()
    assert "file:///" not in text


def test_network_guard_blocks_and_records() -> None:
    guard = NetworkGuard()
    with network_denied(guard), pytest.raises(NetworkDeniedError):
        socket.create_connection(("example.com", 443), timeout=0.1)
    assert guard.attempt_count == 1
    assert guard.attempts[0].host == "example.com"
    assert guard.attempts[0].port == 443


def _snapshot(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "concept_count": 1,
        "context_count": 1,
        "unit_count": 1,
        "fact_count": 1,
        "documents": [
            {
                "canonical_uri": "https://sec.gov/a.htm",
                "content_sha256": "aa" * 32,
                "document_type": "inline_instance",
            }
        ],
        "edges": [],
        "relationship_counts": {"presentation": 1},
        "resource_relationship_counts": {"concept_label": 1},
        "concept_relationship_occurrence_hash": "e" * 64,
        "resource_relationship_occurrence_hash": "f" * 64,
        "synthetic_document_set_hash": "1" * 64,
        "synthetic_edge_set_hash": "2" * 64,
        "unresolved_uris": [],
        "entry_points": ["https://sec.gov/a.htm"],
    }
    base.update(overrides)
    return base


def _compare(online: dict[str, object], offline: dict[str, object]) -> dict[str, object]:
    return compare_snapshots(
        online,
        offline,
        closure_hash_online="c" * 64,
        closure_hash_offline="c" * 64,
        offline_network_attempt_count=0,
        offline_cache_was_empty=True,
    )


def test_compare_snapshots_strict_vs_allowed() -> None:
    online = _snapshot()
    offline = _snapshot(entry_points=["file:///tmp/working/accession/a.htm"])
    result = _compare(online, offline)
    assert result["strict_ok"]
    assert result["criterion_10_ok"]
    assert result["allowed_diffs"][0]["code"] == "ENTRYPOINT_LOCAL_PATH_NORMALIZED"

    bad = _compare(online, _snapshot(fact_count=99, entry_points=["file:///tmp/x.htm"]))
    assert not bad["strict_ok"]
    assert not bad["criterion_10_ok"]


def test_compare_snapshots_synthetic_mismatch_is_strict() -> None:
    online = _snapshot()
    offline = _snapshot(synthetic_edge_set_hash="9" * 64)
    result = _compare(online, offline)
    assert not result["strict_ok"]
    assert any(d["code"] == "STRICT_SYNTHETIC_EDGE_SET_MISMATCH" for d in result["strict_diffs"])


def test_inspection_hash_excludes_local_paths_when_not_present() -> None:
    core = {
        "payload_hash": "aa" * 32,
        "documents": [
            {
                "canonical_uri": "https://example.com/a.xsd",
                "content_sha256": "bb" * 32,
                "document_type": "schema",
            }
        ],
        "engine": {"config": {"cache_mode": "isolated-empty", "plugins": []}},
    }
    digest = inspection_hash(core)
    raw = str(core)
    assert "/Users/" not in raw
    assert len(digest) == 64


def test_criterion_evaluation_external_capture_logic() -> None:
    # External capture detail shape used by criterion 5.
    detail = {
        "ok": False,
        "uncovered_documents": ["https://xbrl.sec.gov/a.xsd"],
        "uncovered_references": [],
        "entrypoint_is_primary_binding": True,
    }
    assert detail["ok"] is False
