"""Strict vs normalized online/offline comparison.

Strict diffs fail the spike; allowed diffs must match a registered
normalization rule. Free-form prose cannot waive strict diffs.

Edge comparison uses sorted canonical record lists retaining duplicates
(or Counter over canonical bytes) — never sets. Structured error identity
compares code + canonical document URI + multiplicity (source line is
evidence-only).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from spike_lib.hashing import canonical_json_bytes

NORMALIZATION_RULES = {
    "ENTRYPOINT_LOCAL_PATH_NORMALIZED": "uri-alias-v1",
    "CACHE_PATH_EXCLUDED": "operational-path-v1",
    "HTTP_TO_CATALOG_PATH": "uri-alias-v1",
}


def _canonical_edge_key(edge: dict[str, Any]) -> bytes:
    """Canonical compared form of one edge occurrence (no diagnostic fields)."""
    record = {
        "edge_occurrence": edge.get("edge_occurrence"),
        "source_document_uri": edge.get("source_document_uri") or edge.get("source_uri"),
        "target_document_uri": edge.get("target_document_uri") or edge.get("target_uri"),
        "reference_kind": edge.get("reference_kind") or edge.get("discovery_type"),
        "normalized_reference_uri": (
            edge.get("normalized_reference_uri") or edge.get("normalized_href")
        ),
        "reference_attribute_qname": edge.get("reference_attribute_qname"),
    }
    return canonical_json_bytes(record)


def _edge_multiset(snapshot: dict[str, Any]) -> Counter[bytes]:
    return Counter(_canonical_edge_key(e) for e in snapshot.get("edges", []))


def _doc_set(snapshot: dict[str, Any]) -> set[tuple[str, str, str]]:
    docs = snapshot.get("documents", [])
    result: set[tuple[str, str, str]] = set()
    for d in docs:
        uri = d.get("document_uri") or d.get("canonical_uri")
        result.add((uri, d["content_sha256"], d["document_type"]))
    return result


def _error_identity_records(error_summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Canonical error identity: code + document URI + multiplicity (no source line)."""
    if not error_summary:
        return []
    records = error_summary.get("canonical_error_records") or error_summary.get("errors") or []
    identity: dict[tuple[str, str | None], int] = {}
    for rec in records:
        code = rec.get("code") or rec.get("error_code")
        doc = rec.get("document_uri") or rec.get("canonical_document_uri")
        if code is None:
            continue
        key = (str(code), str(doc) if doc is not None else None)
        identity[key] = identity.get(key, 0) + int(rec.get("count") or rec.get("multiplicity") or 1)
    return [
        {"code": code, "document_uri": doc, "multiplicity": count}
        for (code, doc), count in sorted(identity.items())
    ]


def compare_snapshots(
    online: dict[str, Any],
    offline: dict[str, Any],
    *,
    closure_hash_online: str,
    closure_hash_offline: str,
    offline_network_attempt_count: int,
    offline_cache_was_empty: bool,
) -> dict[str, Any]:
    """Compare online vs offline inspection snapshots."""
    strict: list[dict[str, Any]] = []
    allowed: list[dict[str, Any]] = []

    for key in ("concept_count", "context_count", "unit_count", "fact_count"):
        if online.get(key) != offline.get(key):
            strict.append(
                {
                    "code": f"STRICT_{key.upper()}_MISMATCH",
                    "online": online.get(key),
                    "offline": offline.get(key),
                }
            )

    if closure_hash_online != closure_hash_offline:
        strict.append(
            {
                "code": "STRICT_CLOSURE_HASH_MISMATCH",
                "online": closure_hash_online,
                "offline": closure_hash_offline,
            }
        )

    for key in (
        "concept_relationship_occurrence_hash",
        "resource_relationship_occurrence_hash",
    ):
        if online.get(key) != offline.get(key):
            strict.append(
                {
                    "code": f"STRICT_{key.upper()}_MISMATCH",
                    "online": online.get(key),
                    "offline": offline.get(key),
                }
            )

    if online.get("relationship_counts") != offline.get("relationship_counts"):
        strict.append(
            {
                "code": "STRICT_RELATIONSHIP_COUNTS_MISMATCH",
                "online": online.get("relationship_counts"),
                "offline": offline.get("relationship_counts"),
            }
        )
    if online.get("resource_relationship_counts") != offline.get("resource_relationship_counts"):
        strict.append(
            {
                "code": "STRICT_RESOURCE_RELATIONSHIP_COUNTS_MISMATCH",
                "online": online.get("resource_relationship_counts"),
                "offline": offline.get("resource_relationship_counts"),
            }
        )

    online_docs = _doc_set(online)
    offline_docs = _doc_set(offline)
    if online_docs != offline_docs:
        strict.append(
            {
                "code": "STRICT_DOCUMENT_SET_MISMATCH",
                "only_online": sorted(online_docs - offline_docs),
                "only_offline": sorted(offline_docs - online_docs),
            }
        )

    online_edges = _edge_multiset(online)
    offline_edges = _edge_multiset(offline)
    if online_edges != offline_edges:
        only_online = sum((online_edges - offline_edges).values())
        only_offline = sum((offline_edges - online_edges).values())
        strict.append(
            {
                "code": "STRICT_DISCOVERY_EDGE_MULTISET_MISMATCH",
                "only_online_count": only_online,
                "only_offline_count": only_offline,
            }
        )

    if online.get("synthetic_document_set_hash") != offline.get("synthetic_document_set_hash"):
        strict.append(
            {
                "code": "STRICT_SYNTHETIC_DOCUMENT_SET_MISMATCH",
                "online": online.get("synthetic_document_set_hash"),
                "offline": offline.get("synthetic_document_set_hash"),
            }
        )
    if online.get("synthetic_edge_set_hash") != offline.get("synthetic_edge_set_hash"):
        strict.append(
            {
                "code": "STRICT_SYNTHETIC_EDGE_SET_MISMATCH",
                "online": online.get("synthetic_edge_set_hash"),
                "offline": offline.get("synthetic_edge_set_hash"),
            }
        )

    online_unresolved = set(online.get("unresolved_uris") or [])
    offline_unresolved = set(offline.get("unresolved_uris") or [])
    if online_unresolved != offline_unresolved:
        strict.append(
            {
                "code": "STRICT_UNRESOLVED_MISMATCH",
                "online": sorted(online_unresolved),
                "offline": sorted(offline_unresolved),
            }
        )

    online_errors = _error_identity_records(online.get("error_summary"))
    offline_errors = _error_identity_records(offline.get("error_summary"))
    if online_errors != offline_errors:
        strict.append(
            {
                "code": "STRICT_ERROR_IDENTITY_MISMATCH",
                "online": online_errors,
                "offline": offline_errors,
            }
        )

    online_edge_ext = online.get("document_edge_extraction") or {}
    offline_edge_ext = offline.get("document_edge_extraction") or {}
    if online_edge_ext.get("extraction_complete") != offline_edge_ext.get("extraction_complete"):
        strict.append(
            {
                "code": "STRICT_DOCUMENT_EDGE_EXTRACTION_MISMATCH",
                "online": online_edge_ext,
                "offline": offline_edge_ext,
            }
        )

    if offline_network_attempt_count != 0:
        strict.append(
            {
                "code": "STRICT_NETWORK_ATTEMPTS",
                "offline_network_attempt_count": offline_network_attempt_count,
            }
        )

    if not offline_cache_was_empty:
        strict.append(
            {
                "code": "STRICT_OFFLINE_CACHE_NOT_STARTED_EMPTY",
                "offline_cache_started_empty": offline_cache_was_empty,
            }
        )

    online_eps = set(online.get("entry_points") or [])
    offline_eps = set(offline.get("entry_points") or [])
    if online_eps != offline_eps:
        online_hashes = {d[1] for d in online_docs}
        offline_hashes = {d[1] for d in offline_docs}
        if online_hashes == offline_hashes:
            allowed.append(
                {
                    "code": "ENTRYPOINT_LOCAL_PATH_NORMALIZED",
                    "online": sorted(online_eps),
                    "offline": sorted(offline_eps),
                    "normalization_rule": NORMALIZATION_RULES["ENTRYPOINT_LOCAL_PATH_NORMALIZED"],
                }
            )
        else:
            strict.append(
                {
                    "code": "STRICT_ENTRYPOINT_MISMATCH",
                    "online": sorted(online_eps),
                    "offline": sorted(offline_eps),
                }
            )

    unexplained = [
        d
        for d in allowed
        if d.get("code") not in NORMALIZATION_RULES
        or d.get("normalization_rule") != NORMALIZATION_RULES.get(d["code"])
    ]

    return {
        "strict_diffs": strict,
        "allowed_diffs": allowed,
        "unexplained_diffs": unexplained,
        "strict_ok": not strict,
        "criterion_10_ok": not strict and not unexplained,
    }
