"""Subprocess worker entrypoints for isolated Arelle online/offline loads.

Invoked as:
  python -m spike_lib.worker --job /path/to/job.json

Modes:
- ``online``: load a local entrypoint path with network allowed.
- ``offline-manifest``: the only replay inputs are the sterile manifest bytes
  (verified against an expected SHA-256), the content-addressed object store,
  and the serialized URI-bindings artifact referenced by the manifest. No
  online state, cache, or environment is read.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from spike_lib.arelle_load import (
    build_oasis_catalog,
    load_and_inspect,
    materialize_arelle_web_cache,
)
from spike_lib.hashing import sha256_hex
from spike_lib.manifest import (
    manifest_artifact_hashes,
    validate_manifest,
)
from spike_lib.storage import ObjectStore, write_bytes_atomic, write_json_atomic
from spike_lib.uri_bindings import (
    parse_bindings,
    validate_bindings,
)


def _snapshot_dict(snapshot: Any) -> dict[str, Any]:
    return {
        "documents": snapshot.documents,
        "edges": snapshot.edges,
        "concept_count": snapshot.concept_count,
        "context_count": snapshot.context_count,
        "unit_count": snapshot.unit_count,
        "fact_count": snapshot.fact_count,
        "relationship_counts": snapshot.relationship_counts,
        "resource_relationship_counts": snapshot.resource_relationship_counts,
        "concept_records": snapshot.concept_records,
        "resource_records": snapshot.resource_records,
        "concept_relationship_occurrence_hash": snapshot.concept_relationship_occurrence_hash,
        "resource_relationship_occurrence_hash": snapshot.resource_relationship_occurrence_hash,
        "unsupported_inventory": snapshot.unsupported_inventory,
        "extraction": snapshot.extraction,
        "synthetic_documents": snapshot.synthetic_documents,
        "synthetic_document_set_hash": snapshot.synthetic_document_set_hash,
        "synthetic_document_count": snapshot.synthetic_document_count,
        "synthetic_edges": snapshot.synthetic_edges,
        "synthetic_edge_set_hash": snapshot.synthetic_edge_set_hash,
        "synthetic_edge_count": snapshot.synthetic_edge_count,
        "entry_points": snapshot.entry_points,
        "unresolved_uris": snapshot.unresolved_uris,
        "fact_locator_stats": snapshot.fact_locator_stats,
        "error_summary": snapshot.error_summary,
        "engine_name": snapshot.engine_name,
        "engine_version": snapshot.engine_version,
        "engine_config": snapshot.engine_config,
        "log_sha256": snapshot.log_sha256,
        "log_error_count": snapshot.log_error_count,
        "log_warning_count": snapshot.log_warning_count,
    }


def _result_payload(mode: str, result: Any) -> dict[str, Any]:
    return {
        "mode": mode,
        "snapshot": _snapshot_dict(result.snapshot),
        "closure_documents": [
            {
                "canonical_uri": d.canonical_uri,
                "content_sha256": d.content_sha256,
                "document_type": d.document_type,
                "local_path": d.local_path,
                "byte_size": d.byte_size,
            }
            for d in result.closure_documents
        ],
        "closure_edges": [
            {
                "source_uri": e.source_uri,
                "discovery_type": e.discovery_type,
                "target_uri": e.target_uri,
                "normalized_href": e.normalized_href,
            }
            for e in result.closure_edges
        ],
        "reference_uris": result.reference_uris,
        "issues": [i.to_dict() for i in result.issues],
        "network_attempts": result.network_attempts,
        "offline_cache_was_empty": result.offline_cache_was_empty,
        "log_sha256": result.snapshot.log_sha256
        or (sha256_hex(result.raw_log.encode("utf-8")) if result.raw_log else None),
    }


def _failed_payload(mode: str, code: str, message: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": mode,
        "error": code,
        "snapshot": {
            "documents": [],
            "edges": [],
            "concept_count": 0,
            "context_count": 0,
            "unit_count": 0,
            "fact_count": 0,
            "relationship_counts": {},
            "resource_relationship_counts": {},
            "concept_records": [],
            "resource_records": [],
            "concept_relationship_occurrence_hash": "",
            "resource_relationship_occurrence_hash": "",
            "unsupported_inventory": {},
            "extraction": {"extraction_complete": False},
            "synthetic_documents": [],
            "synthetic_document_set_hash": "",
            "synthetic_document_count": 0,
            "synthetic_edges": [],
            "synthetic_edge_set_hash": "",
            "synthetic_edge_count": 0,
            "entry_points": [],
            "unresolved_uris": [],
            "fact_locator_stats": {},
            "error_summary": {},
            "engine_name": "arelle",
            "engine_version": "unknown",
            "engine_config": {},
            "log_sha256": None,
            "log_error_count": 1,
            "log_warning_count": 0,
        },
        "closure_documents": [],
        "closure_edges": [],
        "reference_uris": [],
        "issues": [{"severity": "fatal", "code": code, "message": message, "context": context}],
        "network_attempts": [],
        "offline_cache_was_empty": True if mode == "offline-manifest" else None,
        "log_sha256": None,
    }


def run_online_job(job: dict[str, Any]) -> dict[str, Any]:
    from spike_lib.network_guard import NetworkDeniedError

    entrypoint = job["entrypoint"]
    cache_dir = Path(job["cache_dir"])
    log_path = Path(job["log_path"]) if job.get("log_path") else None
    result_path = Path(job["result_path"])

    try:
        result = load_and_inspect(
            entrypoint,
            offline=False,
            cache_dir=cache_dir,
            catalog_path=None,
            user_agent=job.get("user_agent"),
            deny_network=False,
            uri_aliases=job.get("uri_aliases") or {},
            catalogued_uris=None,
        )
    except NetworkDeniedError as exc:
        payload = _failed_payload("online", "NETWORK_DENIED", str(exc), exc.attempt.to_dict())
        write_json_atomic(result_path, payload)
        return payload

    if log_path is not None:
        write_bytes_atomic(log_path, result.raw_log.encode("utf-8"))
    payload = _result_payload("online", result)
    write_json_atomic(result_path, payload)
    return payload


def run_offline_manifest_job(job: dict[str, Any]) -> dict[str, Any]:
    """Replay strictly from manifest + object store + serialized bindings."""
    from spike_lib.network_guard import NetworkDeniedError

    manifest_path = Path(job["manifest_path"])
    store = ObjectStore(Path(job["object_store_root"]))
    expected_sha = job["expected_manifest_sha256"]
    cache_dir = Path(job["cache_dir"])
    work_dir = Path(job["work_dir"])
    log_path = Path(job["log_path"]) if job.get("log_path") else None
    result_path = Path(job["result_path"])

    manifest_bytes = manifest_path.read_bytes()
    actual_sha = sha256_hex(manifest_bytes)
    if actual_sha != expected_sha:
        payload = _failed_payload(
            "offline-manifest",
            "MANIFEST_HASH_MISMATCH",
            "manifest bytes do not match expected SHA-256",
            {"expected": expected_sha, "actual": actual_sha},
        )
        write_json_atomic(result_path, payload)
        return payload

    manifest = json.loads(manifest_bytes.decode("utf-8"))
    structure_errors = validate_manifest(manifest)
    if structure_errors:
        payload = _failed_payload(
            "offline-manifest",
            "MANIFEST_INVALID",
            "sterile manifest failed structural validation",
            {"errors": structure_errors},
        )
        write_json_atomic(result_path, payload)
        return payload

    artifact_hashes = manifest_artifact_hashes(manifest)

    # Object-store integrity: every payload artifact object must exist.
    missing_objects = [path for path, sha in artifact_hashes.items() if not store.exists(sha)]
    if missing_objects:
        payload = _failed_payload(
            "offline-manifest",
            "OBJECT_STORE_INCOMPLETE",
            "payload artifact objects missing from object store",
            {"missing": missing_objects},
        )
        write_json_atomic(result_path, payload)
        return payload

    pointer = manifest["uri_bindings_artifact"]
    bindings_bytes = store.open_bytes(pointer["sha256"])
    if sha256_hex(bindings_bytes) != pointer["sha256"]:
        payload = _failed_payload(
            "offline-manifest",
            "URI_BINDINGS_HASH_MISMATCH",
            "uri-bindings object does not match manifest pointer",
            {"pointer": pointer["sha256"]},
        )
        write_json_atomic(result_path, payload)
        return payload

    entrypoint_uri = manifest["entrypoint"]["document_uri"]
    try:
        bindings = parse_bindings(bindings_bytes)
    except ValueError as exc:
        payload = _failed_payload("offline-manifest", "URI_BINDINGS_INVALID", str(exc), {})
        write_json_atomic(result_path, payload)
        return payload

    binding_errors = validate_bindings(
        bindings,
        manifest_artifacts=artifact_hashes,
        entrypoint_document_uri=entrypoint_uri,
    )
    if binding_errors:
        payload = _failed_payload(
            "offline-manifest",
            "URI_BINDINGS_INVALID",
            "uri bindings failed validation",
            {"errors": binding_errors},
        )
        write_json_atomic(result_path, payload)
        return payload

    # Materialize exactly the bound documents from verified objects.
    work_dir.mkdir(parents=True, exist_ok=True)
    uri_to_path: dict[str, Path] = {}
    uri_aliases: dict[str, str] = {}
    for binding in bindings:
        data = store.open_bytes(binding.content_sha256)
        if sha256_hex(data) != binding.content_sha256:
            payload = _failed_payload(
                "offline-manifest",
                "OBJECT_INTEGRITY_FAILURE",
                "object bytes do not match binding content hash",
                {"logical_path": binding.logical_path},
            )
            write_json_atomic(result_path, payload)
            return payload
        target = work_dir / binding.logical_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        uri_to_path[binding.document_uri] = target
        uri_aliases[binding.document_uri] = binding.document_uri
        uri_aliases[str(target.resolve())] = binding.document_uri
        for alias in binding.replay_aliases:
            uri_to_path[alias] = target
            uri_aliases[alias] = binding.document_uri

    # Seed an empty Arelle web cache from the serialized bindings only.
    web_cache_dir = cache_dir / "arelle-web-cache"
    seeded = materialize_arelle_web_cache(uri_to_path, web_cache_dir)

    catalog_path = work_dir / "metadata" / "offline-catalog.xml"
    build_oasis_catalog(uri_to_path, catalog_path)

    try:
        result = load_and_inspect(
            entrypoint_uri,
            offline=True,
            cache_dir=cache_dir,
            catalog_path=catalog_path,
            user_agent=job.get("user_agent"),
            deny_network=True,
            uri_aliases=uri_aliases,
            catalogued_uris=list(uri_to_path.keys()),
            offline_cache_started_empty=True,
            offline_cache_populated_from_manifest=bool(seeded),
        )
    except NetworkDeniedError as exc:
        payload = _failed_payload(
            "offline-manifest",
            "NETWORK_DENIED_DURING_OFFLINE_LOAD",
            str(exc),
            exc.attempt.to_dict(),
        )
        write_json_atomic(result_path, payload)
        return payload

    if log_path is not None:
        write_bytes_atomic(log_path, result.raw_log.encode("utf-8"))
    payload = _result_payload("offline-manifest", result)
    write_json_atomic(result_path, payload)
    return payload


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    mode = job["mode"]
    if mode == "online":
        return run_online_job(job)
    if mode == "offline-manifest":
        return run_offline_manifest_job(job)
    raise ValueError(f"unknown worker mode: {mode!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, help="Path to job JSON")
    args = parser.parse_args(argv)
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    run_job(job)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
