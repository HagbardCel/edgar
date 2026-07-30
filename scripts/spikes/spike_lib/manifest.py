"""Deterministic sterile bundle manifest (manifest-v2-spike) and promotion.

The sterile manifest contains only durable identity fields: schema/policy
versions, CIK/accession, payload hash, artifact inventory, the URI-bindings
artifact pointer, and the self-describing entrypoint. It contains no volatile
retrieval/operational data: no timestamps, paths, logs, replay status, parser
output, engine versions, HTTP redirect history, environment data, run IDs, or
policy results.

Two manifests produced from identical inputs must serialize byte-identically.
Manifest bytes may change only when a schema/policy version changes or an
identity-bearing input changes.

Promotion identity = (acquisition_policy_version, manifest_schema_version,
entrypoint, payload_hash). A candidate is promoted only after successful
offline replay validation; promotion installs the exact validated manifest
bytes via an atomic directory rename.
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
)
from spike_lib.hashing import payload_hash_v1, sha256_hex
from spike_lib.storage import write_json_atomic
from spike_lib.uri_bindings import URI_BINDINGS_LOGICAL_PATH

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
    return payload_hash_v1(entries)


def build_sterile_manifest(
    draft: Any,
    *,
    entrypoint_document_uri: str,
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
        manifest["uri_bindings_artifact"] = {
            "logical_path": URI_BINDINGS_LOGICAL_PATH,
            "sha256": bindings.sha256,
            "byte_size": bindings.byte_size,
        }
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Structural validation of a sterile manifest (errors as strings)."""
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
    entrypoint = manifest.get("entrypoint") or {}
    if entrypoint.get("kind") != ENTRYPOINT_KIND_SINGLE_DOCUMENT:
        errors.append(f"unsupported entrypoint kind: {entrypoint.get('kind')!r}")
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
    artifact_by_path = {a["logical_path"]: a for a in manifest["artifacts"]}
    if pointer is None:
        errors.append("missing uri_bindings_artifact pointer")
    else:
        artifact = artifact_by_path.get(pointer.get("logical_path", ""))
        if artifact is None:
            errors.append("uri-bindings pointer target absent from artifacts")
        elif artifact["sha256"] != pointer.get("sha256"):
            errors.append("uri-bindings pointer hash differs from artifact entry")
        elif artifact.get("in_payload", True) is not True:
            errors.append("uri-bindings artifact must be a payload artifact")
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

    Returns the promotion record (operational; stored in run metadata, not in
    the bundle manifest). Idempotent: an existing final bundle with identical
    promotion identity is reused. A conflict at the final path is fatal.
    """
    final_dir = accession_root / "bundles" / ACQUISITION_POLICY_VERSION / manifest["payload_hash"]
    manifest_bytes = (staging_dir / "manifest.json").read_bytes()

    if final_dir.exists():
        existing_path = final_dir / "manifest.json"
        if not existing_path.is_file():
            raise RuntimeError(f"bundle integrity conflict at {final_dir}: no manifest.json")
        existing = json.loads(existing_path.read_text(encoding="utf-8"))
        if promotion_identity(existing) != promotion_identity(manifest):
            raise RuntimeError(
                f"bundle integrity conflict at {final_dir}: promotion identity differs"
            )
        if sorted(payload_entries_from_manifest(existing)) != sorted(
            payload_entries_from_manifest(manifest)
        ):
            raise RuntimeError(
                f"bundle integrity conflict at {final_dir}: payload artifacts differ"
            )
        outcome = "reused_existing"
    else:
        # Atomic promotion: rename the exact validated staging directory.
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_dir, final_dir)
        outcome = "promoted"

    return {
        "outcome": outcome,
        "final_bundle_path": str(final_dir),
        "promotion_identity": promotion_identity(manifest),
        "manifest_sha256": sha256_hex(manifest_bytes),
    }


def discard_candidate(accession_root: Any, staging_dir: Any, *, reason: str) -> Any:
    """Move a failed candidate to .failed/ for diagnosis; no final bundle."""
    failed_dir = (
        accession_root / "bundles" / ACQUISITION_POLICY_VERSION / ".failed" / staging_dir.name
    )
    failed_dir.parent.mkdir(parents=True, exist_ok=True)
    if failed_dir.exists():
        shutil.rmtree(failed_dir)
    os.replace(staging_dir, failed_dir)
    write_json_atomic(failed_dir / "failure.json", {"reason": reason})
    return failed_dir
