"""Deterministic hashing helpers for payload, closure, relationships, and inspection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of_uri(uri: str) -> str:
    return sha256_hex(uri.encode("utf-8"))


def payload_artifact_identities(
    entries: Sequence[tuple[str, str, int]],
) -> list[dict[str, Any]]:
    """Canonical payload artifact identity records (payload-v1).

    Each entry is (logical_path, sha256_lowercase, byte_size). The manifest
    itself is never part of the payload identity: callers must not pass an
    entry for ``manifest.json``. Role classification and provenance attributes
    are deliberately excluded from bundle identity.
    """
    identities = [
        {"logical_path": path, "sha256": digest.lower(), "byte_size": int(size)}
        for path, digest, size in entries
    ]
    identities.sort(key=lambda item: item["logical_path"].encode("utf-8"))
    return identities


def payload_hash_v1(entries: Sequence[tuple[str, str, int]]) -> str:
    """Explicit payload-v1 construction.

    SHA-256 over the canonical JSON of::

        {
            "payload_hash_schema_version": "payload-v1",
            "artifacts": [
                {"logical_path": ..., "sha256": ..., "byte_size": ...},
                ...  # sorted by logical_path UTF-8 bytes
            ]
        }

    ``metadata/uri-bindings.json`` participates exactly once as an ordinary
    artifact entry. The manifest artifact is excluded.
    """
    from spike_lib import PAYLOAD_HASH_SCHEMA_VERSION

    record = {
        "payload_hash_schema_version": PAYLOAD_HASH_SCHEMA_VERSION,
        "artifacts": payload_artifact_identities(entries),
    }
    return sha256_hex(canonical_json_bytes(record))


def closure_document_records(
    documents: Iterable[tuple[str, str, str]],
) -> list[bytes]:
    """Encode (canonical_uri, content_sha256, document_type) records."""
    records: list[bytes] = []
    for canonical_uri, content_sha256, document_type in documents:
        records.append(
            canonical_uri.encode("utf-8")
            + b"\x00"
            + content_sha256.lower().encode("ascii")
            + b"\x00"
            + document_type.encode("utf-8")
            + b"\n"
        )
    records.sort()
    return records


def closure_edge_records(
    edges: Iterable[tuple[str, str, str, str]],
) -> list[bytes]:
    """Encode (source_uri, discovery_type, target_uri, normalized_href) records."""
    records: list[bytes] = []
    for source_uri, discovery_type, target_uri, normalized_href in edges:
        records.append(
            source_uri.encode("utf-8")
            + b"\x00"
            + discovery_type.encode("utf-8")
            + b"\x00"
            + target_uri.encode("utf-8")
            + b"\x00"
            + normalized_href.encode("utf-8")
            + b"\n"
        )
    records.sort()
    return records


def closure_hash(
    documents: Iterable[tuple[str, str, str]],
    edges: Iterable[tuple[str, str, str, str]],
) -> str:
    doc_hash = sha256_hex(b"".join(closure_document_records(documents)))
    edge_hash = sha256_hex(b"".join(closure_edge_records(edges)))
    return sha256_hex(doc_hash.encode("ascii") + b"\x00" + edge_hash.encode("ascii"))


def _normalize_for_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {
            str(k): _normalize_for_json(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_for_json(v) for v in value]
    if isinstance(value, set):
        return sorted(_normalize_for_json(v) for v in value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def canonical_json_bytes(payload: Mapping[str, Any] | list[Any]) -> bytes:
    """UTF-8 JSON with sorted keys, no whitespace, decimals as strings."""
    if isinstance(payload, Mapping):
        normalized = _normalize_for_json(dict(payload))
    else:
        normalized = _normalize_for_json(list(payload))
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def inspection_hash(payload: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(payload))


def versioned_record_hash(serialization_version: str, record: Mapping[str, Any]) -> str:
    """SHA-256 over the canonical JSON of a version-stamped record."""
    versioned = {"serialization_version": serialization_version, **record}
    return sha256_hex(canonical_json_bytes(versioned))


def relationship_set_hash(records: Sequence[Mapping[str, Any]]) -> str:
    """Hash the canonical effective relationship set."""
    return sha256_hex(canonical_json_bytes(list(records)))
