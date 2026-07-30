"""Strict vs normalized online/offline comparison for Slice 0."""

from __future__ import annotations

from typing import Any

NORMALIZATION_RULES = {
    "ENTRYPOINT_LOCAL_PATH_NORMALIZED": "uri-alias-v1",
    "CACHE_PATH_EXCLUDED": "operational-path-v1",
    "HTTP_TO_CATALOG_PATH": "uri-alias-v1",
}


def _doc_set(snapshot: dict[str, Any]) -> set[tuple[str, str, str]]:
    return {
        (d["canonical_uri"], d["content_sha256"], d["document_type"])
        for d in snapshot.get("documents", [])
    }


def _edge_set(snapshot: dict[str, Any]) -> set[tuple[str, str, str, str]]:
    return {
        (
            e["source_uri"],
            e["discovery_type"],
            e["target_uri"],
            e["normalized_href"],
        )
        for e in snapshot.get("edges", [])
    }


def compare_snapshots(
    online: dict[str, Any],
    offline: dict[str, Any],
    *,
    closure_hash_online: str,
    closure_hash_offline: str,
    relationship_set_hash_online: str,
    relationship_set_hash_offline: str,
    offline_network_attempt_count: int,
    offline_cache_was_empty: bool,
) -> dict[str, Any]:
    """Compare online vs offline inspection cores.

    Returns strict_diffs (fail the spike) and allowed_diffs (must match a
    registered normalization rule). Free-form prose cannot waive strict diffs.
    """
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

    if relationship_set_hash_online != relationship_set_hash_offline:
        strict.append(
            {
                "code": "STRICT_RELATIONSHIP_SET_HASH_MISMATCH",
                "online": relationship_set_hash_online,
                "offline": relationship_set_hash_offline,
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

    online_edges = _edge_set(online)
    offline_edges = _edge_set(offline)
    if online_edges != offline_edges:
        strict.append(
            {
                "code": "STRICT_DISCOVERY_EDGE_SET_MISMATCH",
                "only_online_count": len(online_edges - offline_edges),
                "only_offline_count": len(offline_edges - online_edges),
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

    # Entry-point local path differences are allowed when content hashes match.
    online_eps = set(online.get("entry_points") or [])
    offline_eps = set(offline.get("entry_points") or [])
    if online_eps != offline_eps:
        # If the only difference is path form of the same document, allow.
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
