"""Pure FilingBundle structural validation (no filesystem I/O)."""

from __future__ import annotations

from collections.abc import Mapping

from edgar.domain.bundle import BundleArtifact, FilingBundle, UriBinding
from edgar.domain.payload import compute_payload_hash
from edgar.domain.uri import UriIdentityError, assert_serialized_binding_uri


class BundleStructureError(ValueError):
    """Raised when a FilingBundle violates pure structural invariants."""


_HEX64 = frozenset("0123456789abcdef")


def _assert_digest(digest: str, *, label: str) -> None:
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in _HEX64 for c in digest):
        raise BundleStructureError(f"invalid {label}: {digest!r}")


def validate_bundle_structure(bundle: FilingBundle) -> None:
    """Cheap / pure structural checks for a FilingBundle."""
    _assert_digest(bundle.payload_hash, label="payload_hash")
    expected = compute_payload_hash(bundle.artifacts)
    if expected != bundle.payload_hash:
        raise BundleStructureError(
            f"payload_hash mismatch: stored={bundle.payload_hash} recomputed={expected}"
        )

    paths = [a.logical_path for a in bundle.artifacts]
    if len(paths) != len(set(paths)):
        raise BundleStructureError("duplicate artifact logical_path")

    artifact_by_path = {a.logical_path: a for a in bundle.artifacts}
    primary_uris: set[str] = set()
    alias_to_primary: dict[str, str] = {}

    for binding in bundle.uri_bindings:
        _validate_binding(binding, artifact_by_path, primary_uris, alias_to_primary)

    for report in bundle.report_inputs:
        for uri in report.document_uris:
            try:
                assert_serialized_binding_uri(uri)
            except UriIdentityError as exc:
                raise BundleStructureError(str(exc)) from exc
            if uri not in primary_uris:
                raise BundleStructureError(
                    f"report-input URI missing authoritative primary binding: {uri}"
                )


def _validate_binding(
    binding: UriBinding,
    artifact_by_path: Mapping[str, BundleArtifact],
    primary_uris: set[str],
    alias_to_primary: dict[str, str],
) -> None:
    try:
        assert_serialized_binding_uri(binding.document_uri)
    except UriIdentityError as exc:
        raise BundleStructureError(str(exc)) from exc
    _assert_digest(binding.content_sha256, label="binding content_sha256")
    if binding.document_uri in primary_uris:
        raise BundleStructureError(f"duplicate primary binding URI: {binding.document_uri}")
    if binding.document_uri in alias_to_primary:
        raise BundleStructureError(
            f"primary URI collides with alias of {alias_to_primary[binding.document_uri]}: "
            f"{binding.document_uri}"
        )
    primary_uris.add(binding.document_uri)

    artifact = artifact_by_path.get(binding.artifact_path)
    if artifact is None:
        raise BundleStructureError(f"binding artifact_path not in payload: {binding.artifact_path}")
    if artifact.content.sha256 != binding.content_sha256:
        raise BundleStructureError(
            f"binding SHA mismatch for {binding.document_uri}: "
            f"{binding.content_sha256} != {artifact.content.sha256}"
        )

    seen_aliases: set[str] = set()
    for alias in binding.replay_aliases:
        if alias in seen_aliases:
            raise BundleStructureError(f"duplicate replay alias within binding: {alias}")
        seen_aliases.add(alias)
        try:
            assert_serialized_binding_uri(alias)
        except UriIdentityError as exc:
            raise BundleStructureError(str(exc)) from exc
        if alias == binding.document_uri:
            raise BundleStructureError(f"alias equals primary URI: {alias}")
        if alias in primary_uris:
            raise BundleStructureError(f"alias collides with primary URI: {alias}")
        if alias in alias_to_primary:
            raise BundleStructureError(
                f"alias shared across bindings: {alias} "
                f"({alias_to_primary[alias]} and {binding.document_uri})"
            )
        alias_to_primary[alias] = binding.document_uri


def assert_canonical_serialized_cik(cik: object) -> str:
    """Reject noncanonical serialized CIKs before FilingIdentity can normalize."""
    if not isinstance(cik, str):
        raise BundleStructureError(f"cik must be a string, got {type(cik).__name__}")
    from edgar.domain.identifiers import validate_cik

    normalized = validate_cik(cik)
    if cik != normalized:
        raise BundleStructureError(f"noncanonical serialized CIK: {cik!r}")
    return cik


def assert_canonical_serialized_accession(accession: object) -> str:
    if not isinstance(accession, str):
        raise BundleStructureError(f"accession must be a string, got {type(accession).__name__}")
    from edgar.domain.identifiers import validate_accession

    normalized = validate_accession(accession)
    if accession != normalized:
        raise BundleStructureError(f"noncanonical serialized accession: {accession!r}")
    return accession
