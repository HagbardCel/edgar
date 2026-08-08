"""Unit tests for payload-hash-v1 and uri-identity-v1."""

from __future__ import annotations

import hashlib

import pytest

from edgar.domain.bundle import BundleArtifact, ContentObject
from edgar.ingestion.payload import compute_payload_hash, payload_hash_bytes
from edgar.xbrl.uri import UriIdentityError, normalize_uri, resolve_document_uri


def test_payload_hash_order_independent() -> None:
    a = BundleArtifact(
        logical_path="accession/b.xml",
        content=ContentObject(sha256="b" * 64, byte_size=2),
        artifact_kind="attachment",
        required=True,
    )
    b = BundleArtifact(
        logical_path="accession/a.xml",
        content=ContentObject(sha256="a" * 64, byte_size=1),
        artifact_kind="attachment",
        required=True,
    )
    assert compute_payload_hash([a, b]) == compute_payload_hash([b, a])


def test_payload_hash_exact_bytes() -> None:
    raw = payload_hash_bytes([("accession/a.xml", "aa" * 32, 3)])
    assert not raw.endswith(b"\n")
    assert b'"schema":"payload-hash-v1"' in raw
    digest = compute_payload_hash([("accession/a.xml", "aa" * 32, 3)])
    assert digest == hashlib.sha256(raw).hexdigest()


def test_payload_hash_rejects_duplicate_paths() -> None:
    with pytest.raises(ValueError):
        compute_payload_hash(
            [
                ("accession/a.xml", "aa" * 32, 1),
                ("accession/a.xml", "bb" * 32, 2),
            ]
        )


def test_uri_identity_vectors() -> None:
    assert normalize_uri("HTTP://EXAMPLE.COM:80/a/../b/%7e") == "http://example.com/b/~"
    assert normalize_uri("https://example.com/a/%2E%2E/b") == "https://example.com/b"


def test_uri_empty_query_preserved() -> None:
    assert normalize_uri("https://example.com/a") == "https://example.com/a"
    assert normalize_uri("https://example.com/a?") == "https://example.com/a?"


def test_uri_rejects_credentials_and_non_ascii_host() -> None:
    with pytest.raises(UriIdentityError):
        normalize_uri("https://user:pass@example.com/a")
    with pytest.raises(UriIdentityError):
        normalize_uri("https://exämple.com/a")


def test_resolve_relative_against_base() -> None:
    base = "https://xbrl.sec.gov/dei/2024/dei-2024.xsd"
    assert resolve_document_uri(base, "./child.xsd") == "https://xbrl.sec.gov/dei/2024/child.xsd"
