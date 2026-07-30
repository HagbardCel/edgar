"""Subprocess worker entrypoints for isolated Arelle online/offline loads.

Invoked as:
  python -m spike_lib.worker --job /path/to/job.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from spike_lib.arelle_load import load_with_arelle
from spike_lib.hashing import sha256_hex
from spike_lib.storage import write_bytes_atomic, write_json_atomic


def _snapshot_dict(result: Any) -> dict[str, Any]:
    snap = result.snapshot
    return {
        "documents": snap.documents,
        "edges": snap.edges,
        "concept_count": snap.concept_count,
        "context_count": snap.context_count,
        "unit_count": snap.unit_count,
        "fact_count": snap.fact_count,
        "relationship_counts": snap.relationship_counts,
        "relationship_records": snap.relationship_records,
        "relationship_set_hash": snap.relationship_set_hash,
        "entry_points": snap.entry_points,
        "unresolved_uris": snap.unresolved_uris,
        "fact_locator_stats": snap.fact_locator_stats,
        "engine_name": snap.engine_name,
        "engine_version": snap.engine_version,
        "engine_config": snap.engine_config,
        "log_sha256": snap.log_sha256,
        "log_error_count": snap.log_error_count,
        "log_warning_count": snap.log_warning_count,
    }


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    from spike_lib.network_guard import NetworkDeniedError

    mode = job["mode"]  # "online" | "offline"
    entrypoint = Path(job["entrypoint"])
    cache_dir = Path(job["cache_dir"])
    catalog_path = Path(job["catalog_path"]) if job.get("catalog_path") else None
    user_agent = job.get("user_agent")
    uri_aliases = job.get("uri_aliases") or {}
    catalogued_uris = job.get("catalogued_uris") or list(uri_aliases.values())
    deny_network = bool(job.get("deny_network", mode == "offline"))
    offline_cache_started_empty = job.get("offline_cache_started_empty")
    offline_cache_populated_from_manifest = job.get("offline_cache_populated_from_manifest")
    log_path = Path(job["log_path"]) if job.get("log_path") else None
    result_path = Path(job["result_path"])

    try:
        result = load_with_arelle(
            entrypoint,
            offline=(mode == "offline"),
            cache_dir=cache_dir,
            catalog_path=catalog_path,
            user_agent=user_agent,
            deny_network=deny_network,
            uri_aliases=uri_aliases,
            catalogued_uris=catalogued_uris,
            offline_cache_started_empty=offline_cache_started_empty,
            offline_cache_populated_from_manifest=offline_cache_populated_from_manifest,
        )
    except NetworkDeniedError as exc:
        # Persist a measured failure so criterion 6 can fail without a silent crash.
        payload = {
            "mode": mode,
            "error": "network_denied",
            "snapshot": {
                "documents": [],
                "edges": [],
                "concept_count": 0,
                "context_count": 0,
                "unit_count": 0,
                "fact_count": 0,
                "relationship_counts": {},
                "relationship_records": [],
                "relationship_set_hash": "",
                "entry_points": [],
                "unresolved_uris": [],
                "fact_locator_stats": {},
                "engine_name": "arelle",
                "engine_version": "unknown",
                "engine_config": {
                    "cache_mode": "isolated-empty" if mode == "offline" else "isolated-online",
                    "work_offline": mode == "offline",
                    "deny_network": deny_network,
                    "validation_enabled": False,
                    "plugins": [],
                    "catalog_configured": catalog_path is not None,
                    "catalog_generator_version": None,
                },
                "log_sha256": None,
                "log_error_count": 1,
                "log_warning_count": 0,
            },
            "closure_documents": [],
            "closure_edges": [],
            "issues": [
                {
                    "severity": "fatal",
                    "code": "NETWORK_DENIED_DURING_OFFLINE_LOAD",
                    "message": str(exc),
                    "context": exc.attempt.to_dict(),
                }
            ],
            "network_attempts": [exc.attempt.to_dict()],
            "offline_cache_was_empty": True if mode == "offline" else None,
            "log_sha256": None,
        }
        write_json_atomic(result_path, payload)
        return payload

    if log_path is not None:
        write_bytes_atomic(log_path, result.raw_log.encode("utf-8"))

    payload = {
        "mode": mode,
        "snapshot": _snapshot_dict(result),
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
        "issues": [i.to_dict() for i in result.issues],
        "network_attempts": result.network_attempts,
        "offline_cache_was_empty": result.offline_cache_was_empty,
        "log_sha256": result.snapshot.log_sha256
        or (sha256_hex(result.raw_log.encode("utf-8")) if result.raw_log else None),
    }
    write_json_atomic(result_path, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, help="Path to job JSON")
    args = parser.parse_args(argv)
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    run_job(job)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
