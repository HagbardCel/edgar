"""URI bindings contract (uri-bindings-v2).

The bindings artifact is the sole authoritative replay input for the offline
worker: it maps canonical document URIs to payload object identities with
content SHA-256. Source classification stays in the manifest; bindings carry
no ``source_class``. The bindings artifact never binds itself: it covers the
XBRL-addressable source documents required for replay.

Binding rules:
- one ``logical_path`` + ``content_sha256`` pair per canonical document URI
- multiple URIs may map to the same content hash (legitimate aliases)
- the same canonical document URI must never map to conflicting object
  identities (fatal)
- ``replay_aliases`` cover only URIs that materially participate in Arelle's
  document/base URI resolution; intermediate HTTP redirect hops are excluded
- ``logical_path`` must be a safe manifest artifact path present in the
  manifest with a matching content hash
- every serialized document_uri and replay_alias must already be canonical
  under uri-identity-v1
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from spike_lib import URI_BINDING_SCHEMA_VERSION, URI_IDENTITY_VERSION
from spike_lib.sec import validate_logical_path
from spike_lib.storage import write_bytes_atomic
from spike_lib.uri_identity import UriIdentityError, assert_serialized_binding_uri

URI_BINDINGS_LOGICAL_PATH = "metadata/uri-bindings.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_TOP_LEVEL = frozenset({"uri_binding_schema_version", "uri_identity_version", "bindings"})
_ALLOWED_RECORD_KEYS = frozenset(
    {"document_uri", "logical_path", "content_sha256", "replay_aliases"}
)


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
        "uri_identity_version": URI_IDENTITY_VERSION,
        "bindings": records,
    }


def serialize_bindings(bindings: list[UriBinding]) -> bytes:
    """Deterministic serialized bindings bytes (sorted keys, UTF-8, LF end)."""
    doc = canonical_bindings_document(bindings)
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _require_str(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string, got {type(value).__name__}")
    return value


def parse_bindings(data: bytes) -> list[UriBinding]:
    """Strict uri-bindings-v2 parser. Rejects unknown keys and malformed values."""
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"uri bindings are not valid JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("uri bindings document must be an object")
    unknown = sorted(set(doc) - _ALLOWED_TOP_LEVEL)
    if unknown:
        raise ValueError(f"unknown top-level uri-bindings keys: {unknown}")
    if "uri_binding_schema_version" not in doc:
        raise ValueError("missing uri_binding_schema_version")
    if "uri_identity_version" not in doc:
        raise ValueError("missing uri_identity_version")
    if doc["uri_binding_schema_version"] != URI_BINDING_SCHEMA_VERSION:
        raise ValueError(f"uri bindings schema mismatch: {doc['uri_binding_schema_version']!r}")
    if doc["uri_identity_version"] != URI_IDENTITY_VERSION:
        raise ValueError(f"uri identity version mismatch: {doc['uri_identity_version']!r}")
    raw_bindings = doc.get("bindings")
    if not isinstance(raw_bindings, list):
        raise ValueError("bindings must be a list")
    bindings: list[UriBinding] = []
    for index, record in enumerate(raw_bindings):
        if not isinstance(record, dict):
            raise ValueError(f"bindings[{index}] must be an object")
        unknown_rec = sorted(set(record) - _ALLOWED_RECORD_KEYS)
        if unknown_rec:
            raise ValueError(f"bindings[{index}] unknown keys: {unknown_rec}")
        for required in ("document_uri", "logical_path", "content_sha256"):
            if required not in record:
                raise ValueError(f"bindings[{index}] missing field {required}")
        document_uri = _require_str(record["document_uri"], field_name="document_uri")
        logical_path = _require_str(record["logical_path"], field_name="logical_path")
        content_sha256 = _require_str(record["content_sha256"], field_name="content_sha256")
        if not _SHA256_RE.fullmatch(content_sha256):
            raise ValueError(f"bindings[{index}] malformed content_sha256: {content_sha256!r}")
        raw_aliases = record.get("replay_aliases", [])
        if not isinstance(raw_aliases, list):
            raise ValueError(f"bindings[{index}] replay_aliases must be a list")
        aliases: list[str] = []
        seen_aliases: set[str] = set()
        for alias in raw_aliases:
            alias_s = _require_str(alias, field_name="replay_alias")
            if alias_s in seen_aliases:
                raise ValueError(f"bindings[{index}] duplicate replay_alias: {alias_s!r}")
            seen_aliases.add(alias_s)
            aliases.append(alias_s)
        bindings.append(
            UriBinding(
                document_uri=document_uri,
                logical_path=logical_path,
                content_sha256=content_sha256,
                replay_aliases=aliases,
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

    Collision maps are built from canonical (normalized) URIs. Every serialized
    document_uri and replay_alias must already be canonical.
    """
    errors: list[str] = []
    uri_objects: dict[str, tuple[str, str]] = {}
    alias_owner: dict[str, str] = {}
    primary_uris: set[str] = set()

    try:
        entrypoint_canonical = assert_serialized_binding_uri(entrypoint_document_uri)
    except UriIdentityError as exc:
        errors.append(f"invalid entrypoint document_uri {entrypoint_document_uri!r}: {exc}")
        entrypoint_canonical = entrypoint_document_uri

    for binding in bindings:
        try:
            canonical_uri = assert_serialized_binding_uri(binding.document_uri)
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
        identity = (binding.logical_path, binding.content_sha256)
        prior = uri_objects.get(canonical_uri)
        if prior is not None and prior != identity:
            errors.append(f"conflicting object identities for document_uri {canonical_uri!r}")
        if canonical_uri in uri_objects and prior == identity:
            errors.append(f"duplicate primary document_uri {canonical_uri!r}")
        uri_objects[canonical_uri] = identity
        primary_uris.add(canonical_uri)
        if canonical_uri in alias_owner:
            errors.append(f"URI is both a document_uri and replay_alias: {canonical_uri!r}")
        for alias in binding.replay_aliases:
            try:
                canonical_alias = assert_serialized_binding_uri(alias)
            except UriIdentityError as exc:
                errors.append(f"invalid replay_alias {alias!r}: {exc}")
                continue
            if canonical_alias in primary_uris or canonical_alias in uri_objects:
                errors.append(f"replay_alias collides with a document_uri: {canonical_alias!r}")
            owner = alias_owner.get(canonical_alias)
            if owner is not None and owner != canonical_uri:
                errors.append(
                    f"replay_alias {canonical_alias!r} claimed by multiple bindings: "
                    f"{owner!r} and {canonical_uri!r}"
                )
            alias_owner[canonical_alias] = canonical_uri

    if entrypoint_canonical not in uri_objects:
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
