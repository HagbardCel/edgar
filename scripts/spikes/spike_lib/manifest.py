"""Deterministic sterile bundle manifest (manifest-v3-spike) and promotion.

The sterile manifest contains only durable identity fields: schema/policy
versions, CIK/accession, payload hash, artifact inventory, the URI-bindings
artifact pointer (with binding count and schema/identity versions), and the
self-describing entrypoint. It contains no volatile retrieval/operational data.

Two manifests produced from identical inputs must serialize byte-identically.
Manifest bytes may change only when a schema/policy version changes or an
identity-bearing input changes.

Promotion identity = (acquisition_policy_version, manifest_schema_version,
entrypoint, payload_hash). A candidate is promoted only after the pre-promotion
validation gate passes; promotion installs the exact validated manifest bytes
via an atomic directory rename. Promotion certifies a single-run replay bundle,
not full Slice 0 repeat determinism (Criterion 9 runs afterward).
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any
from uuid import uuid4

from spike_lib import (
    ACQUISITION_POLICY_VERSION,
    MANIFEST_SCHEMA_VERSION,
    PAYLOAD_HASH_SCHEMA_VERSION,
    URI_BINDING_SCHEMA_VERSION,
    URI_IDENTITY_VERSION,
)
from spike_lib.hashing import payload_hash_v1, sha256_hex
from spike_lib.storage import write_json_atomic
from spike_lib.uri_bindings import URI_BINDINGS_LOGICAL_PATH, parse_bindings, validate_bindings
from spike_lib.uri_identity import UriIdentityError, assert_serialized_binding_uri

ENTRYPOINT_KIND_SINGLE_DOCUMENT = "single_document"

# Artifact record keys that belong to the sterile manifest. Volatile
# retrieval fields (content_type from HTTP headers, final_url redirect
# provenance, free-text notes) are deliberately excluded.
STERILE_ARTIFACT_KEYS = (
    "logical_path",
    "sha256",
    "byte_size",
    "source_url",
    "source_class",
    "artifact_role",
    "sec_sequence",
    "sec_document_type",
    "sec_description",
    "required",
    "in_payload",
)

# Stable failure codes for .failed/ candidates (enumerated vocabulary).
FAILURE_MANIFEST_INVALID = "MANIFEST_INVALID"
FAILURE_OFFLINE_REPLAY = "OFFLINE_REPLAY_FAILED"
FAILURE_PRE_PROMOTION_GATE = "PRE_PROMOTION_GATE_FAILED"
FAILURE_BUNDLE_INTEGRITY = "BUNDLE_INTEGRITY_CONFLICT"


def sterile_artifact_record(artifact: Any) -> dict[str, Any]:
    """Manifest artifact record: deterministic, no volatile retrieval fields."""
    record = {}
    for key in STERILE_ARTIFACT_KEYS:
        record[key] = getattr(artifact, key)
    return record


def payload_entries_from_manifest(manifest: dict[str, Any]) -> list[tuple[str, str, int]]:
    return [
        (a["logical_path"], a["sha256"], int(a["byte_size"]))
        for a in manifest.get("artifacts", [])
        if a.get("in_payload", True)
    ]


def compute_manifest_payload_hash(manifest: dict[str, Any]) -> str:
    entries = payload_entries_from_manifest(manifest)
    paths = [e[0] for e in entries]
    if "manifest.json" in paths:
        raise ValueError("manifest.json must never be a payload artifact")
    bindings_entries = [p for p in paths if p == URI_BINDINGS_LOGICAL_PATH]
    if len(bindings_entries) > 1:
        raise ValueError("uri-bindings artifact must participate in payload identity exactly once")
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate logical_path in payload artifacts")
    return payload_hash_v1(entries)


def build_sterile_manifest(
    draft: Any,
    *,
    entrypoint_document_uri: str,
    bindings_count: int | None = None,
) -> dict[str, Any]:
    """Build the deterministic sterile manifest for a bundle candidate."""
    artifacts = [
        sterile_artifact_record(a)
        for a in sorted(draft.artifacts, key=lambda x: x.logical_path.encode("utf-8"))
    ]
    manifest = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "acquisition_policy_version": ACQUISITION_POLICY_VERSION,
        "payload_hash_schema_version": PAYLOAD_HASH_SCHEMA_VERSION,
        "cik": draft.cik,
        "accession": draft.accession,
        "artifacts": artifacts,
        "uri_bindings_artifact": None,
        "entrypoint": {
            "kind": ENTRYPOINT_KIND_SINGLE_DOCUMENT,
            "document_uri": entrypoint_document_uri,
        },
    }
    manifest["payload_hash"] = compute_manifest_payload_hash(manifest)
    bindings = draft.artifact_by_path(URI_BINDINGS_LOGICAL_PATH)
    if bindings is not None:
        count = bindings_count if bindings_count is not None else 0
        manifest["uri_bindings_artifact"] = {
            "logical_path": URI_BINDINGS_LOGICAL_PATH,
            "sha256": bindings.sha256,
            "byte_size": bindings.byte_size,
            "binding_count": count,
            "schema_version": URI_BINDING_SCHEMA_VERSION,
            "uri_identity_version": URI_IDENTITY_VERSION,
        }
    return manifest


def validate_manifest_structure(manifest: dict[str, Any]) -> list[str]:
    """Structural validation of a sterile manifest (no binding bytes required)."""
    errors: list[str] = []
    for key in (
        "manifest_schema_version",
        "acquisition_policy_version",
        "payload_hash_schema_version",
        "cik",
        "accession",
        "payload_hash",
        "artifacts",
        "entrypoint",
    ):
        if key not in manifest:
            errors.append(f"missing manifest key: {key}")
    if errors:
        return errors
    if manifest["manifest_schema_version"] != MANIFEST_SCHEMA_VERSION:
        errors.append(
            f"unsupported manifest_schema_version: {manifest['manifest_schema_version']!r}"
        )
    if manifest["payload_hash_schema_version"] != PAYLOAD_HASH_SCHEMA_VERSION:
        errors.append(
            f"unsupported payload_hash_schema_version: {manifest['payload_hash_schema_version']!r}"
        )
    if not isinstance(manifest.get("artifacts"), list):
        errors.append("artifacts must be a list")
        return errors

    paths = [a.get("logical_path") for a in manifest["artifacts"] if isinstance(a, dict)]
    if len(paths) != len(set(paths)):
        errors.append("duplicate logical_path in artifact inventory")

    entrypoint = manifest.get("entrypoint") or {}
    if entrypoint.get("kind") != ENTRYPOINT_KIND_SINGLE_DOCUMENT:
        errors.append(f"unsupported entrypoint kind: {entrypoint.get('kind')!r}")
    entry_uri = entrypoint.get("document_uri")
    if not isinstance(entry_uri, str):
        errors.append("entrypoint.document_uri must be a string")
    else:
        try:
            assert_serialized_binding_uri(entry_uri)
        except UriIdentityError as exc:
            errors.append(f"entrypoint.document_uri is not canonical: {exc}")

    try:
        recomputed = compute_manifest_payload_hash(manifest)
    except ValueError as exc:
        errors.append(str(exc))
    else:
        if recomputed != manifest["payload_hash"]:
            errors.append(
                f"payload_hash mismatch: declared={manifest['payload_hash']} computed={recomputed}"
            )

    pointer = manifest.get("uri_bindings_artifact")
    artifact_by_path = {a["logical_path"]: a for a in manifest["artifacts"] if isinstance(a, dict)}
    if pointer is None:
        errors.append("missing uri_bindings_artifact pointer")
    elif not isinstance(pointer, dict):
        errors.append("uri_bindings_artifact must be an object")
    else:
        for required in (
            "logical_path",
            "sha256",
            "byte_size",
            "binding_count",
            "schema_version",
            "uri_identity_version",
        ):
            if required not in pointer:
                errors.append(f"uri_bindings_artifact missing field: {required}")
        artifact = artifact_by_path.get(pointer.get("logical_path", ""))
        if artifact is None:
            errors.append("uri-bindings pointer target absent from artifacts")
        else:
            if artifact["sha256"] != pointer.get("sha256"):
                errors.append("uri-bindings pointer hash differs from artifact entry")
            if int(artifact["byte_size"]) != int(pointer.get("byte_size", -1)):
                errors.append("uri-bindings pointer byte_size differs from artifact entry")
            if artifact.get("in_payload", True) is not True:
                errors.append("uri-bindings artifact must be a payload artifact")
        if pointer.get("schema_version") != URI_BINDING_SCHEMA_VERSION:
            errors.append(
                f"uri_bindings_artifact.schema_version mismatch: {pointer.get('schema_version')!r}"
            )
        if pointer.get("uri_identity_version") != URI_IDENTITY_VERSION:
            errors.append(
                "uri_bindings_artifact.uri_identity_version mismatch: "
                f"{pointer.get('uri_identity_version')!r}"
            )

    volatile_keys = {
        "generated_at",
        "replay_status",
        "quality_issues",
        "discovery",
        "issuer_provenance",
        "sgml_reconciliation",
        "sgml_documents",
        "closure_hash",
        "catalog_sha256",
        "relationship_set_hash",
        "run_id",
    }
    leaked = sorted(volatile_keys & set(manifest))
    if leaked:
        errors.append(f"volatile/non-identity keys in sterile manifest: {leaked}")
    return errors


def validate_uri_bindings_pointer(
    manifest: dict[str, Any],
    bindings_bytes: bytes,
) -> list[str]:
    """Validate pointer against binding artifact bytes (second validation layer)."""
    errors: list[str] = []
    pointer = manifest.get("uri_bindings_artifact")
    if not isinstance(pointer, dict):
        return ["missing uri_bindings_artifact pointer"]
    actual_sha = sha256_hex(bindings_bytes)
    if actual_sha != pointer.get("sha256"):
        errors.append(
            f"uri-bindings object hash mismatch: pointer={pointer.get('sha256')} "
            f"actual={actual_sha}"
        )
    if len(bindings_bytes) != int(pointer.get("byte_size", -1)):
        errors.append(
            f"uri-bindings object size mismatch: pointer={pointer.get('byte_size')} "
            f"actual={len(bindings_bytes)}"
        )
    try:
        bindings = parse_bindings(bindings_bytes)
    except ValueError as exc:
        errors.append(f"uri bindings parse failed: {exc}")
        return errors
    if len(bindings) != int(pointer.get("binding_count", -1)):
        errors.append(
            f"binding_count mismatch: pointer={pointer.get('binding_count')} parsed={len(bindings)}"
        )
    artifact_hashes = manifest_artifact_hashes(manifest)
    entrypoint_uri = (manifest.get("entrypoint") or {}).get("document_uri", "")
    errors.extend(
        validate_bindings(
            bindings,
            manifest_artifacts=artifact_hashes,
            entrypoint_document_uri=entrypoint_uri,
        )
    )
    return errors


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Backward-compatible alias for structural validation only."""
    return validate_manifest_structure(manifest)


def manifest_artifact_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {a["logical_path"]: a["sha256"] for a in manifest.get("artifacts", [])}


def promotion_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "acquisition_policy_version": manifest["acquisition_policy_version"],
        "manifest_schema_version": manifest["manifest_schema_version"],
        "entrypoint": manifest["entrypoint"],
        "payload_hash": manifest["payload_hash"],
    }


def stage_candidate(accession_root: Any, manifest: dict[str, Any]) -> Any:
    """Stage a candidate bundle under .staging/; never a final bundle path."""
    staging_dir = (
        accession_root
        / "bundles"
        / ACQUISITION_POLICY_VERSION
        / ".staging"
        / f"candidate-{manifest['payload_hash'][:12]}-{uuid4().hex[:8]}"
    )
    staging_dir.mkdir(parents=True, exist_ok=False)
    write_json_atomic(staging_dir / "manifest.json", manifest)
    return staging_dir


def promote_candidate(
    accession_root: Any, staging_dir: Any, manifest: dict[str, Any]
) -> dict[str, Any]:
    """Atomically promote a validated candidate to its final bundle path.

    Certifies a single-run replay bundle (acquisition + offline replay +
    strict equality + extraction/error-policy success). Does not certify
    Criterion 9 repeat determinism.

    Idempotent: an existing final bundle with identical promotion identity
    AND exact manifest bytes is reused; the staged candidate is then removed.
    Same promotion identity with different manifest bytes is a fatal integrity
    conflict. A reduced projection match is insufficient.
    """
    final_dir = accession_root / "bundles" / ACQUISITION_POLICY_VERSION / manifest["payload_hash"]
    manifest_bytes = (staging_dir / "manifest.json").read_bytes()

    if final_dir.exists():
        existing_path = final_dir / "manifest.json"
        if not existing_path.is_file():
            raise RuntimeError(f"bundle integrity conflict at {final_dir}: no manifest.json")
        existing_bytes = existing_path.read_bytes()
        if existing_bytes != manifest_bytes:
            raise RuntimeError(
                f"bundle integrity conflict at {final_dir}: "
                "same promotion identity but different manifest bytes"
            )
        existing = json.loads(existing_bytes.decode("utf-8"))
        if promotion_identity(existing) != promotion_identity(manifest):
            raise RuntimeError(
                f"bundle integrity conflict at {final_dir}: promotion identity differs"
            )
        # Exact-byte reuse: remove the staged candidate so .staging/ is clean.
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        outcome = "reused_existing"
    else:
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_dir, final_dir)
        outcome = "promoted"

    return {
        "outcome": outcome,
        "final_bundle_path": str(final_dir),
        "promotion_identity": promotion_identity(manifest),
        "manifest_sha256": sha256_hex(manifest_bytes),
        "certification": "single_run_replay_bundle",
    }


def discard_candidate(
    accession_root: Any,
    staging_dir: Any,
    *,
    reason: str,
    failure_code: str = FAILURE_PRE_PROMOTION_GATE,
) -> Any:
    """Move a failed candidate to .failed/ for diagnosis; no final bundle."""
    failed_dir = (
        accession_root / "bundles" / ACQUISITION_POLICY_VERSION / ".failed" / staging_dir.name
    )
    failed_dir.parent.mkdir(parents=True, exist_ok=True)
    if failed_dir.exists():
        shutil.rmtree(failed_dir)
    os.replace(staging_dir, failed_dir)
    write_json_atomic(
        failed_dir / "failure.json",
        {"failure_code": failure_code, "reason": reason},
    )
    return failed_dir
