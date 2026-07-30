"""URI bindings contract (uri-bindings-v1).

The bindings artifact is the sole authoritative replay input for the offline
worker: it maps canonical document URIs to payload object identities with
content SHA-256. Source classification stays in the manifest; bindings carry
no ``source_class``. The bindings artifact never binds itself: it covers the
XBRL-addressable source documents.

Binding rules:
- one ``logical_path`` + ``content_sha256`` pair per canonical document URI
- multiple URIs may map to the same content hash (legitimate aliases)
- the same canonical document URI must never map to conflicting object
  identities (fatal)
- ``replay_aliases`` cover only URIs that materially participate in Arelle's
  document/base URI resolution; intermediate HTTP redirect hops are excluded
- ``logical_path`` must be a safe manifest artifact path present in the
  manifest with a matching content hash
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from spike_lib import URI_BINDING_SCHEMA_VERSION
from spike_lib.sec import validate_logical_path
from spike_lib.storage import write_bytes_atomic
from spike_lib.uri_identity import UriIdentityError, normalize_uri

URI_BINDINGS_LOGICAL_PATH = "metadata/uri-bindings.json"


@dataclass
class UriBinding:
    document_uri: str
    logical_path: str
    content_sha256: str
    replay_aliases: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        return {
            "document_uri": self.document_uri,
            "logical_path": self.logical_path,
            "content_sha256": self.content_sha256,
            "replay_aliases": sorted(self.replay_aliases),
        }


def canonical_bindings_document(bindings: list[UriBinding]) -> dict[str, Any]:
    records = sorted((b.to_record() for b in bindings), key=lambda r: r["document_uri"])
    return {
        "uri_binding_schema_version": URI_BINDING_SCHEMA_VERSION,
        "bindings": records,
    }


def serialize_bindings(bindings: list[UriBinding]) -> bytes:
    """Deterministic serialized bindings bytes (sorted keys, UTF-8, LF end)."""
    doc = canonical_bindings_document(bindings)
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def parse_bindings(data: bytes) -> list[UriBinding]:
    doc = json.loads(data.decode("utf-8"))
    if doc.get("uri_binding_schema_version") != URI_BINDING_SCHEMA_VERSION:
        raise ValueError(f"uri bindings schema mismatch: {doc.get('uri_binding_schema_version')!r}")
    bindings = []
    for record in doc.get("bindings", []):
        bindings.append(
            UriBinding(
                document_uri=record["document_uri"],
                logical_path=record["logical_path"],
                content_sha256=record["content_sha256"],
                replay_aliases=list(record.get("replay_aliases") or []),
            )
        )
    return bindings


def validate_bindings(
    bindings: list[UriBinding],
    *,
    manifest_artifacts: dict[str, str],
    entrypoint_document_uri: str,
    bindings_logical_path: str = URI_BINDINGS_LOGICAL_PATH,
) -> list[str]:
    """Return a list of fatal binding-rule violations (empty when valid).

    ``manifest_artifacts`` maps logical_path -> expected content_sha256.
    """
    errors: list[str] = []
    uri_objects: dict[str, tuple[str, str]] = {}
    alias_owner: dict[str, str] = {}

    for binding in bindings:
        try:
            normalize_uri(binding.document_uri)
        except UriIdentityError as exc:
            errors.append(f"invalid document_uri {binding.document_uri!r}: {exc}")
            continue
        if binding.logical_path == bindings_logical_path:
            errors.append("uri-bindings artifact must not contain a binding for itself")
        try:
            validate_logical_path(binding.logical_path)
        except ValueError as exc:
            errors.append(f"unsafe logical_path {binding.logical_path!r}: {exc}")
        expected_sha = manifest_artifacts.get(binding.logical_path)
        if expected_sha is None:
            errors.append(f"binding logical_path absent from manifest: {binding.logical_path}")
        elif expected_sha != binding.content_sha256:
            errors.append(
                f"binding content hash mismatch for {binding.logical_path}: "
                f"manifest={expected_sha} binding={binding.content_sha256}"
            )
        prior = uri_objects.get(binding.document_uri)
        identity = (binding.logical_path, binding.content_sha256)
        if prior is not None and prior != identity:
            errors.append(
                f"conflicting object identities for document_uri {binding.document_uri!r}"
            )
        uri_objects[binding.document_uri] = identity
        if binding.document_uri in alias_owner:
            errors.append(f"URI is both a document_uri and replay_alias: {binding.document_uri!r}")
        for alias in binding.replay_aliases:
            try:
                normalize_uri(alias)
            except UriIdentityError as exc:
                errors.append(f"invalid replay_alias {alias!r}: {exc}")
                continue
            if alias in uri_objects or alias in {b.document_uri for b in bindings}:
                errors.append(f"replay_alias collides with a document_uri: {alias!r}")
            owner = alias_owner.get(alias)
            if owner is not None and owner != binding.document_uri:
                errors.append(
                    f"replay_alias {alias!r} claimed by multiple bindings: "
                    f"{owner!r} and {binding.document_uri!r}"
                )
            alias_owner[alias] = binding.document_uri

    if entrypoint_document_uri not in uri_objects:
        errors.append(f"entrypoint document_uri has no binding: {entrypoint_document_uri!r}")
    return errors


def covered_uris(bindings: list[UriBinding]) -> set[str]:
    """All URIs covered by bindings (document_uris + replay_aliases)."""
    covered: set[str] = set()
    for binding in bindings:
        covered.add(binding.document_uri)
        covered.update(binding.replay_aliases)
    return covered


def write_bindings(path: Any, bindings: list[UriBinding]) -> bytes:
    data = serialize_bindings(bindings)
    write_bytes_atomic(path, data)
    return data
