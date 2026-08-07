"""Unit tests for uri-bindings-v2 construction and validation (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib.uri_bindings import (  # noqa: E402
    URI_BINDINGS_LOGICAL_PATH,
    UriBinding,
    covered_uris,
    parse_bindings,
    serialize_bindings,
    validate_bindings,
)

ENTRYPOINT = "https://www.sec.gov/Archives/edgar/data/1/x/a.htm"


def _artifacts() -> dict[str, str]:
    return {
        "accession/a.htm": "aa" * 32,
        "accession/a.xsd": "bb" * 32,
        "external/cc/d.xsd": "cc" * 32,
    }


def test_serialize_parse_roundtrip_deterministic() -> None:
    bindings = [
        UriBinding(ENTRYPOINT, "accession/a.htm", "aa" * 32),
        UriBinding("https://example.com/d.xsd", "external/cc/d.xsd", "cc" * 32),
    ]
    data1 = serialize_bindings(bindings)
    data2 = serialize_bindings(list(reversed(bindings)))
    assert data1 == data2
    parsed = parse_bindings(data1)
    assert [b.document_uri for b in parsed] == sorted(b.document_uri for b in bindings)


def test_validate_accepts_valid_bindings() -> None:
    bindings = [
        UriBinding(ENTRYPOINT, "accession/a.htm", "aa" * 32),
        UriBinding(
            "https://example.com/d.xsd",
            "external/cc/d.xsd",
            "cc" * 32,
            replay_aliases=["https://mirror.example.com/d.xsd"],
        ),
    ]
    errors = validate_bindings(
        bindings, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert errors == []


def test_multiple_uris_may_share_one_content_hash() -> None:
    bindings = [
        UriBinding(ENTRYPOINT, "accession/a.htm", "aa" * 32),
        UriBinding("https://example.com/copy.htm", "accession/a.htm", "aa" * 32),
    ]
    errors = validate_bindings(
        bindings, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert errors == []


def test_conflicting_object_identity_for_same_uri_is_fatal() -> None:
    bindings = [
        UriBinding(ENTRYPOINT, "accession/a.htm", "aa" * 32),
        UriBinding(ENTRYPOINT, "accession/a.xsd", "bb" * 32),
    ]
    errors = validate_bindings(
        bindings, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert any("conflicting object identities" in e for e in errors)


def test_alias_collisions_are_fatal() -> None:
    alias = "https://mirror.example.com/d.xsd"
    bindings = [
        UriBinding(ENTRYPOINT, "accession/a.htm", "aa" * 32, replay_aliases=[alias]),
        UriBinding(
            "https://example.com/d.xsd", "external/cc/d.xsd", "cc" * 32, replay_aliases=[alias]
        ),
    ]
    errors = validate_bindings(
        bindings, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert any("claimed by multiple bindings" in e for e in errors)

    alias_as_primary = [
        UriBinding(ENTRYPOINT, "accession/a.htm", "aa" * 32, replay_aliases=[alias]),
        UriBinding(alias, "external/cc/d.xsd", "cc" * 32),
    ]
    errors = validate_bindings(
        alias_as_primary, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert any("document_uri and replay_alias" in e or "collides" in e for e in errors)


def test_self_binding_is_rejected() -> None:
    bindings = [
        UriBinding(ENTRYPOINT, "accession/a.htm", "aa" * 32),
        UriBinding("https://example.com/bindings.json", URI_BINDINGS_LOGICAL_PATH, "dd" * 32),
    ]
    errors = validate_bindings(
        bindings, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert any("binding for itself" in e for e in errors)


def test_binding_requires_manifest_artifact_and_hash_match() -> None:
    bindings = [UriBinding(ENTRYPOINT, "accession/missing.htm", "aa" * 32)]
    errors = validate_bindings(
        bindings, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert any("absent from manifest" in e for e in errors)

    bindings = [UriBinding(ENTRYPOINT, "accession/a.htm", "ff" * 32)]
    errors = validate_bindings(
        bindings, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert any("content hash mismatch" in e for e in errors)


def test_entrypoint_must_be_primary_binding() -> None:
    bindings = [
        UriBinding(
            "https://example.com/d.xsd",
            "external/cc/d.xsd",
            "cc" * 32,
            replay_aliases=[ENTRYPOINT],
        ),
    ]
    errors = validate_bindings(
        bindings, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert any("entrypoint" in e for e in errors)


def test_unsafe_logical_path_rejected() -> None:
    bindings = [UriBinding(ENTRYPOINT, "../escape.htm", "aa" * 32)]
    errors = validate_bindings(
        bindings, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert any("unsafe logical_path" in e for e in errors)


def test_covered_uris_includes_aliases() -> None:
    bindings = [
        UriBinding(
            ENTRYPOINT, "accession/a.htm", "aa" * 32, replay_aliases=["https://a.example/x"]
        ),
    ]
    assert covered_uris(bindings) == {ENTRYPOINT, "https://a.example/x"}


def test_noncanonical_serialized_uri_rejected() -> None:
    bindings = [
        UriBinding(
            "HTTPS://WWW.SEC.GOV/Archives/edgar/data/1/x/a.htm",
            "accession/a.htm",
            "aa" * 32,
        ),
    ]
    errors = validate_bindings(
        bindings, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert any("not canonical" in e or "invalid document_uri" in e for e in errors)


def test_canonical_equivalent_alias_collision() -> None:
    bindings = [
        UriBinding(
            ENTRYPOINT,
            "accession/a.htm",
            "aa" * 32,
            replay_aliases=["https://example.com:443/d.xsd"],
        ),
        UriBinding(
            "https://example.com/d.xsd",
            "external/cc/d.xsd",
            "cc" * 32,
        ),
    ]
    # Alias https://example.com:443/d.xsd canonicalizes to https://example.com/d.xsd
    # which is a primary — but alias itself must already be canonical, so reject.
    errors = validate_bindings(
        bindings, manifest_artifacts=_artifacts(), entrypoint_document_uri=ENTRYPOINT
    )
    assert errors  # non-canonical alias and/or collision


def test_parse_requires_uri_identity_version() -> None:
    import json

    from spike_lib import URI_BINDING_SCHEMA_VERSION

    doc = {
        "uri_binding_schema_version": URI_BINDING_SCHEMA_VERSION,
        "bindings": [],
    }
    with pytest.raises(ValueError, match="uri_identity_version"):
        parse_bindings(json.dumps(doc).encode("utf-8"))
