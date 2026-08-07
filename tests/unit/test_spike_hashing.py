"""Unit tests for spike hashing helpers (no network)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib.hashing import (  # noqa: E402
    canonical_json_bytes,
    closure_hash,
    inspection_hash,
    payload_hash_v1,
    sha256_hex,
)


def test_payload_hash_is_order_independent() -> None:
    a = [("b/file.txt", "aa" * 32, 10), ("a/file.txt", "bb" * 32, 3)]
    b = list(reversed(a))
    assert payload_hash_v1(a) == payload_hash_v1(b)


def test_payload_hash_changes_with_bytes() -> None:
    base = [("a.txt", "ab" * 32, 1)]
    changed = [("a.txt", "cd" * 32, 1)]
    assert payload_hash_v1(base) != payload_hash_v1(changed)


def test_closure_hash_byte_discipline() -> None:
    docs = [
        {
            "document_uri": "https://example.com/b.xsd",
            "content_sha256": "11" * 32,
            "document_type": "schema",
        },
        {
            "document_uri": "https://example.com/a.xsd",
            "content_sha256": "22" * 32,
            "document_type": "schema",
        },
    ]
    edges = [
        {
            "edge_occurrence": {
                "document_uri": "https://example.com/a.xsd",
                "locator": {"kind": "unqualified_id", "value": "r1"},
            },
            "source_document_uri": "https://example.com/a.xsd",
            "target_document_uri": "https://example.com/b.xsd",
            "reference_kind": "schema_import",
            "normalized_reference_uri": "https://example.com/b.xsd",
            "reference_attribute_qname": "schemaLocation",
        }
    ]
    h1 = closure_hash(docs, edges)
    h2 = closure_hash(list(reversed(docs)), edges)
    assert h1 == h2
    assert len(h1) == 64
    # Multiplicity retained: two identical edges change the hash.
    h3 = closure_hash(docs, edges + edges)
    assert h3 != h1


def test_inspection_hash_excludes_float_and_sorts() -> None:
    payload = {"z": 1, "a": [Decimal("1.50"), Decimal("2")]}
    digest = inspection_hash(payload)
    assert digest == sha256_hex(canonical_json_bytes(payload))
    raw = canonical_json_bytes(payload).decode("utf-8")
    assert raw == '{"a":["1.50","2"],"z":1}'


def test_validate_logical_path_rejects_traversal() -> None:
    from spike_lib.sec import validate_logical_path

    with pytest.raises(ValueError):
        validate_logical_path("../etc/passwd")
    with pytest.raises(ValueError):
        validate_logical_path("/abs")
    assert validate_logical_path("accession/a.htm") == "accession/a.htm"
