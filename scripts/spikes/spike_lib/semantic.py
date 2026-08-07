"""Semantic run identity (semantic-run-v2): non-circular, independently comparable.

``semantic_run_hash`` covers the semantic identity only: payload identity,
engine identity, canonical closure documents/edges (source-backed partition),
concept/resource relationship occurrence collections, counts, unsupported
inventory, entrypoint, structured error identity, document-edge extraction,
and criterion outcomes *excluding* the repeat criterion (id 9) and all
repeat-derived fields. Operational data (paths, logs, timings, promotion
state), samples, and the full-inspection digest never participate.

``build_semantic_run_identity`` constructs the hash input by explicit
inclusion keyed to SEMANTIC_RUN_SCHEMA_VERSION. It never embeds
``semantic_run_hash`` itself, so verification is non-circular.
"""

from __future__ import annotations

from typing import Any

from spike_lib import (
    ACQUISITION_POLICY_VERSION,
    CLOSURE_SERIALIZATION_VERSION,
    MANIFEST_SCHEMA_VERSION,
    PAYLOAD_HASH_SCHEMA_VERSION,
    RELATIONSHIP_SERIALIZATION_VERSION,
    RESOURCE_SERIALIZATION_VERSION,
    SEMANTIC_RUN_SCHEMA_VERSION,
    URI_BINDING_SCHEMA_VERSION,
    URI_IDENTITY_VERSION,
)
from spike_lib.arelle_errors import canonical_error_identity_records
from spike_lib.hashing import canonical_json_bytes, sha256_hex

REPEAT_CRITERION_ID = 9


def _side_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Semantic projection of one (online or offline) inspection snapshot."""
    error_summary = snapshot.get("error_summary") or {}
    return {
        "concept_count": snapshot["concept_count"],
        "context_count": snapshot["context_count"],
        "unit_count": snapshot["unit_count"],
        "fact_count": snapshot["fact_count"],
        "relationship_counts": snapshot["relationship_counts"],
        "resource_relationship_counts": snapshot["resource_relationship_counts"],
        "concept_relationship_occurrence_hash": snapshot["concept_relationship_occurrence_hash"],
        "resource_relationship_occurrence_hash": snapshot["resource_relationship_occurrence_hash"],
        "source_backed_documents": snapshot["documents"],
        "source_backed_edges": snapshot["edges"],
        "synthetic_document_set_hash": snapshot["synthetic_document_set_hash"],
        "synthetic_document_count": snapshot["synthetic_document_count"],
        "synthetic_edge_set_hash": snapshot["synthetic_edge_set_hash"],
        "synthetic_edge_count": snapshot["synthetic_edge_count"],
        "entry_points": snapshot["entry_points"],
        "unresolved_uris": snapshot["unresolved_uris"],
        "unsupported_inventory": snapshot["unsupported_inventory"],
        "extraction": snapshot["extraction"],
        "document_edge_extraction": snapshot.get("document_edge_extraction"),
        "error_identity": {
            "arelle_error_policy_version": error_summary.get("arelle_error_policy_version"),
            "canonical_error_records": error_summary.get("canonical_error_records")
            or canonical_error_identity_records(error_summary.get("errors") or []),
            "recognized_nonblocking_error_count": error_summary.get(
                "recognized_nonblocking_error_count"
            ),
            "unrecognized_error_count": error_summary.get("unrecognized_error_count"),
            "policy_passed": error_summary.get("policy_passed"),
        },
    }


def build_semantic_run_identity(
    *,
    cik: str,
    accession: str,
    payload_hash: str,
    closure_hash: str,
    engine: dict[str, Any],
    online_snapshot: dict[str, Any],
    offline_snapshot: dict[str, Any],
    strict_comparison: dict[str, Any],
    criteria: list[dict[str, Any]],
) -> dict[str, Any]:
    """Hash input by explicit inclusion. Excludes criterion 9 and repeat fields."""
    return {
        "semantic_run_schema_version": SEMANTIC_RUN_SCHEMA_VERSION,
        "schema_versions": {
            "acquisition_policy_version": ACQUISITION_POLICY_VERSION,
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "payload_hash_schema_version": PAYLOAD_HASH_SCHEMA_VERSION,
            "uri_binding_schema_version": URI_BINDING_SCHEMA_VERSION,
            "uri_identity_version": URI_IDENTITY_VERSION,
            "relationship_serialization_version": RELATIONSHIP_SERIALIZATION_VERSION,
            "resource_serialization_version": RESOURCE_SERIALIZATION_VERSION,
            "closure_serialization_version": CLOSURE_SERIALIZATION_VERSION,
        },
        "cik": cik,
        "accession": accession,
        "payload_hash": payload_hash,
        "closure_hash": closure_hash,
        "engine": {
            "name": engine["name"],
            "version": engine["version"],
            "config": engine["config"],
        },
        "online": _side_projection(online_snapshot),
        "offline": _side_projection(offline_snapshot),
        "strict_comparison": strict_comparison,
        "success_criteria": [
            {"id": c["id"], "name": c["name"], "passed": c["passed"]}
            for c in criteria
            if c["id"] != REPEAT_CRITERION_ID
        ],
    }


def semantic_run_hash(identity: dict[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(identity))


def strict_comparison_projection(compare: dict[str, Any]) -> dict[str, Any]:
    """Stable projection of the comparison result for semantic identity."""
    return {
        "strict_diffs": compare["strict_diffs"],
        "allowed_diffs": compare["allowed_diffs"],
        "unexplained_diffs": compare["unexplained_diffs"],
        "strict_ok": compare["strict_ok"],
        "criterion_10_ok": compare["criterion_10_ok"],
    }
