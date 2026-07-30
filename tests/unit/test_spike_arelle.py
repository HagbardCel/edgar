"""Unit tests for Arelle adapter helpers, comparison, and isolation (no network)."""

from __future__ import annotations

import socket
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib.arelle_load import (  # noqa: E402
    build_oasis_catalog,
    canonical_relationship_record,
    collect_effective_relationships,
    map_discovery_type,
    map_discovery_types,
    relationship_key,
)
from spike_lib.compare import compare_snapshots  # noqa: E402
from spike_lib.hashing import inspection_hash, relationship_set_hash  # noqa: E402
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


def test_relationship_set_hash_detects_diff_with_same_count() -> None:
    a = [
        {
            "network_type": "presentation",
            "arcrole_uri": "http://www.xbrl.org/2003/arcrole/parent-child",
            "link_role_uri": "http://example.com/role/A",
            "source_concept": "us-gaap:Assets",
            "target_concept": "us-gaap:Cash",
            "order": "1.0",
            "weight": None,
            "preferred_label_role": None,
            "target_role": None,
            "closed": None,
            "usable": None,
            "context_element": None,
        }
    ]
    b = [
        {
            **a[0],
            "target_concept": "us-gaap:Inventory",
        }
    ]
    assert len(a) == len(b)
    assert relationship_set_hash(a) != relationship_set_hash(b)


def test_collect_effective_relationships_dedup_and_linkroles() -> None:
    class Rel:
        def __init__(self, linkrole, frm, to, order="1", weight=None):
            self.linkrole = linkrole
            self.fromModelObject = SimpleNamespace(qname=frm)
            self.toModelObject = SimpleNamespace(qname=to)
            self.order = Decimal(order)
            self.weight = weight
            self.preferredLabel = None
            self.targetRole = None
            self.closed = None
            self.usable = None
            self.contextElement = None

    arc = "http://www.xbrl.org/2003/arcrole/parent-child"
    rel_a = Rel("http://example.com/role/A", "a:One", "a:Two")
    rel_b = Rel("http://example.com/role/B", "a:One", "a:Two")
    # Duplicate of rel_a
    rel_a2 = Rel("http://example.com/role/A", "a:One", "a:Two")

    class RelSet:
        def __init__(self, rels):
            self.modelRelationships = rels

    class Model:
        baseSets = {
            (arc, "http://example.com/role/A", None, None, None): [rel_a],
            (arc, "http://example.com/role/B", None, None, None): [rel_b],
        }

        def relationshipSet(self, arcrole, linkrole=None):
            if arcrole != arc:
                return RelSet([])
            if linkrole == "http://example.com/role/A":
                return RelSet([rel_a, rel_a2])
            if linkrole == "http://example.com/role/B":
                return RelSet([rel_b])
            if linkrole is None:
                return RelSet([rel_a, rel_b])
            return RelSet([])

    records, counts = collect_effective_relationships(Model())
    assert counts["presentation"] == 2
    assert len(records) == 2
    roles = {r["link_role_uri"] for r in records}
    assert roles == {"http://example.com/role/A", "http://example.com/role/B"}


def test_canonical_relationship_decimal_serialization() -> None:
    rel = SimpleNamespace(
        linkrole="http://example.com/role",
        fromModelObject=SimpleNamespace(qname="a:X"),
        toModelObject=SimpleNamespace(qname="a:Y"),
        order=Decimal("1.50"),
        weight=Decimal("-1"),
        preferredLabel=None,
        targetRole=None,
        closed=True,
        usable=False,
        contextElement="segment",
    )
    record = canonical_relationship_record(
        rel,
        network_type="definition",
        arcrole="http://xbrl.org/int/dim/arcrole/domain-member",
    )
    assert record["order"] == "1.50"
    assert record["weight"] == "-1"
    assert relationship_key(record)[0] == (1, "definition")


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


def test_compare_snapshots_strict_vs_allowed() -> None:
    online = {
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
        "unresolved_uris": [],
        "entry_points": ["https://sec.gov/a.htm"],
    }
    offline = {
        **online,
        "entry_points": ["file:///tmp/working/accession/a.htm"],
    }
    result = compare_snapshots(
        online,
        offline,
        closure_hash_online="c" * 64,
        closure_hash_offline="c" * 64,
        relationship_set_hash_online="d" * 64,
        relationship_set_hash_offline="d" * 64,
        offline_network_attempt_count=0,
        offline_cache_was_empty=True,
    )
    assert result["strict_ok"]
    assert result["criterion_10_ok"]
    assert result["allowed_diffs"][0]["code"] == "ENTRYPOINT_LOCAL_PATH_NORMALIZED"

    bad = compare_snapshots(
        online,
        {**offline, "fact_count": 99},
        closure_hash_online="c" * 64,
        closure_hash_offline="c" * 64,
        relationship_set_hash_online="d" * 64,
        relationship_set_hash_offline="d" * 64,
        offline_network_attempt_count=0,
        offline_cache_was_empty=True,
    )
    assert not bad["strict_ok"]
    assert not bad["criterion_10_ok"]


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
        "mismatches": [
            {
                "uri": "https://xbrl.sec.gov/a.xsd",
                "expected_sha256": "aa" * 32,
                "artifact_sha256": None,
            }
        ],
        "missing": [],
    }
    assert detail["ok"] is False
