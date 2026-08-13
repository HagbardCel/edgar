"""Byte-immutability guard for frozen Slice-0 evidence files (no spike imports)."""

from __future__ import annotations

import hashlib
from pathlib import Path

EVIDENCE_DIR = Path("fixtures/manifests/0001065088-24-000036")

# SHA-256 of committed bytes at the evidence freeze boundary.
FROZEN_EVIDENCE_SHA256: dict[str, str] = {
    "acquisition-expectations.json": (
        "d8b67747bfda4e2b95257728cd8b276cdd8c08b26f45ab2c999ca26cb5d7b179"
    ),
    "bundle-manifest.json": "a5095b50192bb83a55290fe4b41651c9f5f01a945ee598b80463f486a1dcbbb5",
    "evidence-metadata.json": "8c114bca8db118f24fd0cfe67464ecd384c693c25516f18c0e506e86c3c1a683",
    "inspection-core.json": "be2d95a07b81191c537c684f7e0cffd8102c0e614e5e4583fa0ac59597de3896",
    "inspection-samples.json": "06a66b9b6598fcb28bd34e4cbffbc6e0da04a12c816dadef486a1dd894980db2",
    "parser-expectations.json": "dc64da29c99e491854baf6d640c0235b82c0bb440dff362e5bb07f5ad11db30c",
    "uri-bindings.json": "81bcfd869206e3c87ecc57818851675c52c07fe809f971833d327f1a83308b14",
}


def _sha256_hex(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_slice0_evidence_bytes_unchanged() -> None:
    assert EVIDENCE_DIR.is_dir(), f"missing evidence directory {EVIDENCE_DIR}"
    for name, expected in sorted(FROZEN_EVIDENCE_SHA256.items()):
        path = EVIDENCE_DIR / name
        assert path.is_file(), f"missing frozen evidence file {path}"
        actual = _sha256_hex(path)
        assert actual == expected, (
            f"{name} byte drift: expected {expected}, got {actual}. "
            "Update only through explicit evidence refresh workflow."
        )
