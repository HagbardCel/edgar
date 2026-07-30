"""Unit tests for uri-identity-v1 normalization (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib.uri_identity import (  # noqa: E402
    UriIdentityError,
    is_http_uri,
    normalize_uri,
    resolve_document_uri,
)


def test_normalize_lowercases_scheme_and_host() -> None:
    assert (
        normalize_uri("HTTPS://WWW.SEC.gov/Archives/edgar/data/1/x/a.htm")
        == "https://www.sec.gov/Archives/edgar/data/1/x/a.htm"
    )


def test_normalize_removes_default_ports_keeps_nonstandard() -> None:
    assert normalize_uri("https://example.com:443/a.xsd") == "https://example.com/a.xsd"
    assert normalize_uri("http://example.com:80/a.xsd") == "http://example.com/a.xsd"
    assert normalize_uri("https://example.com:8443/a.xsd") == "https://example.com:8443/a.xsd"


def test_normalize_removes_fragment_preserves_query_and_path_octets() -> None:
    assert normalize_uri("https://example.com/a.xsd#frag") == "https://example.com/a.xsd"
    assert normalize_uri("https://example.com/a.xsd?x=1&y=2") == "https://example.com/a.xsd?x=1&y=2"
    # Percent-encoding octets are preserved, not decoded or re-encoded.
    assert normalize_uri("https://example.com/a%20b.xsd") == "https://example.com/a%20b.xsd"


def test_normalize_rejects_relative_credentials_whitespace() -> None:
    with pytest.raises(UriIdentityError):
        normalize_uri("dei-2023.xsd")
    with pytest.raises(UriIdentityError):
        normalize_uri("https://user:pw@example.com/a.xsd")
    with pytest.raises(UriIdentityError):
        normalize_uri(" https://example.com/a.xsd")
    with pytest.raises(UriIdentityError):
        normalize_uri("ftp://example.com/a.xsd")


def test_trailing_slash_not_altered() -> None:
    assert normalize_uri("https://example.com/dir/") == "https://example.com/dir/"
    assert normalize_uri("https://example.com/dir") == "https://example.com/dir"


def test_resolve_document_uri_uses_base_then_normalizes() -> None:
    base = "https://www.sec.gov/Archives/edgar/data/1/x/ebay.htm"
    assert (
        resolve_document_uri(base, "ebay-2023.xsd")
        == "https://www.sec.gov/Archives/edgar/data/1/x/ebay-2023.xsd"
    )
    assert (
        resolve_document_uri(base, "ebay-2023.xsd#ex_Assets")
        == "https://www.sec.gov/Archives/edgar/data/1/x/ebay-2023.xsd"
    )


def test_is_http_uri() -> None:
    assert is_http_uri("https://example.com/a")
    assert is_http_uri("http://example.com/a")
    assert not is_http_uri("file:///tmp/a")
    assert not is_http_uri("/tmp/a")
