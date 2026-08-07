"""Synthetic (engine-created) documents and edges (synthetic-document-v1).

Engine-created structures are inventoried and hashed explicitly, never silently
mixed into the source-backed partition. The registry is versioned: a new
synthetic kind or serialization change requires a serialization-version bump.

Source-backed partition: documents whose bytes came from captured artifacts
(stable content hashes) and discovery edges between them.

Synthetic partition: engine-created documents/edges with explicit kinds.
Comparison invariant: online/offline synthetic inventories must match exactly
or extraction completeness fails.
"""

from __future__ import annotations

from typing import Any

from spike_lib import SYNTHETIC_DOCUMENT_SERIALIZATION_VERSION
from spike_lib.hashing import canonical_json_bytes, sha256_hex

INLINE_DOCUMENT_SET = "inline_document_set"

KNOWN_SYNTHETIC_KINDS = frozenset({INLINE_DOCUMENT_SET})


def inline_document_set_identity(member_source_document_uris: list[str]) -> dict[str, Any]:
    """Identity for an Arelle inline document set (IXDS) document."""
    return {
        "kind": INLINE_DOCUMENT_SET,
        "member_source_document_uris": sorted(member_source_document_uris),
    }


def unknown_synthetic_identity(engine_uri: str) -> dict[str, Any]:
    """Unregistered synthetic structure: identity pinned to its engine URI."""
    return {"kind": "unregistered", "engine_uri": engine_uri}


def synthetic_document_set_hash(identities: list[dict[str, Any]]) -> str:
    records = sorted(canonical_json_bytes(i) for i in identities)
    payload = {
        "serialization_version": SYNTHETIC_DOCUMENT_SERIALIZATION_VERSION,
        "synthetic_documents": [r.decode("utf-8") for r in records],
    }
    return sha256_hex(canonical_json_bytes(payload))


def synthetic_edge_record(
    *,
    kind: str,
    source: dict[str, Any],
    target: dict[str, Any],
    edge_attributes: dict[str, Any],
) -> dict[str, Any]:
    """Synthetic edge using the same endpoint-occurrence discipline.

    ``source``/``target`` are either a source-backed canonical URI
    (``{"kind": "source_backed_document", "document_uri": ...}``) or a
    synthetic document identity (``{"kind": "synthetic_document",
    "synthetic_document_identity": {...}}``).
    """
    return {
        "kind": kind,
        "source": source,
        "target": target,
        "edge_attributes": edge_attributes,
    }


def synthetic_edge_set_hash(edges: list[dict[str, Any]]) -> str:
    records = sorted(canonical_json_bytes(e) for e in edges)
    payload = {
        "serialization_version": SYNTHETIC_DOCUMENT_SERIALIZATION_VERSION,
        "synthetic_edges": [r.decode("utf-8") for r in records],
    }
    return sha256_hex(canonical_json_bytes(payload))


def empty_document_set_hash() -> str:
    return synthetic_document_set_hash([])


def empty_edge_set_hash() -> str:
    return synthetic_edge_set_hash([])
