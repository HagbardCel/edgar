"""Production payload_hash construction (payload-hash-v1)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from edgar.domain.bundle import BundleArtifact

PAYLOAD_HASH_SCHEMA = "payload-hash-v1"


def payload_hash_bytes(
    artifacts: Sequence[BundleArtifact] | Sequence[tuple[str, str, int]],
) -> bytes:
    """Return the exact UTF-8 bytes hashed for payload-hash-v1."""
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in artifacts:
        if isinstance(item, BundleArtifact):
            path = item.logical_path
            digest = item.content.sha256.lower()
            size = item.content.byte_size
        else:
            path, digest, size = item
            digest = digest.lower()
            size = int(size)
        if path in seen:
            raise ValueError(f"duplicate logical_path in payload: {path!r}")
        seen.add(path)
        records.append({"byte_size": size, "logical_path": path, "sha256": digest})
    records.sort(key=lambda r: str(r["logical_path"]).encode("utf-8"))
    envelope = {"artifacts": records, "schema": PAYLOAD_HASH_SCHEMA}
    return json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def compute_payload_hash(
    artifacts: Sequence[BundleArtifact] | Sequence[tuple[str, str, int]],
) -> str:
    return hashlib.sha256(payload_hash_bytes(artifacts)).hexdigest()
