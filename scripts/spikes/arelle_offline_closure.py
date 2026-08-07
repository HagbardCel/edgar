#!/usr/bin/env python3
"""Slice 0 reproducible spike: accession mirror → Arelle online/offline closure.

Spike code has no compatibility guarantees. Evidence under var/spikes/ is retained.

Replay contract: the offline run is a subprocess whose only inputs are the
sterile manifest (verified by SHA-256), the content-addressed object store,
and the serialized URI-bindings artifact. A bundle candidate is promoted to
its final immutable path only after successful offline replay validation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Allow running as `uv run python scripts/spikes/arelle_offline_closure.py`
SPIKE_DIR = Path(__file__).resolve().parent
if str(SPIKE_DIR) not in sys.path:
    sys.path.insert(0, str(SPIKE_DIR))

from spike_lib import (  # noqa: E402
    ACQUISITION_POLICY_VERSION,
    ARELLE_ERROR_POLICY_VERSION,
    CATALOG_GENERATOR_VERSION,
    CLOSURE_SERIALIZATION_VERSION,
    DISCOVERY_EXTRACTION_POLICY_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    PAYLOAD_HASH_SCHEMA_VERSION,
    RELATIONSHIP_SERIALIZATION_VERSION,
    RESOURCE_SERIALIZATION_VERSION,
    SAMPLES_POLICY_VERSION,
    SEMANTIC_RUN_SCHEMA_VERSION,
    SYNTHETIC_DOCUMENT_SERIALIZATION_VERSION,
    URI_BINDING_SCHEMA_VERSION,
    URI_IDENTITY_VERSION,
)
from spike_lib.acquisition import (  # noqa: E402
    AcquisitionService,
    ArtifactRecord,
)
from spike_lib.arelle_load import (  # noqa: E402
    build_accession_uri_map,
    external_logical_path,
    is_http_uri,
    materialize_working_tree,
)
from spike_lib.compare import compare_snapshots  # noqa: E402
from spike_lib.hashing import canonical_json_bytes, closure_hash, sha256_hex  # noqa: E402
from spike_lib.manifest import (  # noqa: E402
    FAILURE_MANIFEST_INVALID,
    FAILURE_OFFLINE_REPLAY,
    FAILURE_PRE_PROMOTION_GATE,
    build_sterile_manifest,
    discard_candidate,
    promote_candidate,
    stage_candidate,
    validate_manifest_structure,
    validate_uri_bindings_pointer,
)
from spike_lib.quality import QualityIssue  # noqa: E402
from spike_lib.sec import (  # noqa: E402
    SecClient,
    assert_cik_accession_consistent,
    assert_path_under,
    normalize_cik,
    validate_accession,
)
from spike_lib.semantic import (  # noqa: E402
    build_semantic_run_identity,
    semantic_run_hash,
    strict_comparison_projection,
)
from spike_lib.storage import ObjectStore, write_json_atomic  # noqa: E402
from spike_lib.uri_bindings import (  # noqa: E402
    URI_BINDINGS_LOGICAL_PATH,
    UriBinding,
    covered_uris,
    serialize_bindings,
)
from spike_lib.uri_identity import normalize_uri  # noqa: E402

SCHEMA_VERSIONS = {
    "acquisition_policy_version": ACQUISITION_POLICY_VERSION,
    "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
    "payload_hash_schema_version": PAYLOAD_HASH_SCHEMA_VERSION,
    "uri_binding_schema_version": URI_BINDING_SCHEMA_VERSION,
    "uri_identity_version": URI_IDENTITY_VERSION,
    "resource_serialization_version": RESOURCE_SERIALIZATION_VERSION,
    "relationship_serialization_version": RELATIONSHIP_SERIALIZATION_VERSION,
    "closure_serialization_version": CLOSURE_SERIALIZATION_VERSION,
    "synthetic_document_serialization_version": SYNTHETIC_DOCUMENT_SERIALIZATION_VERSION,
    "semantic_run_schema_version": SEMANTIC_RUN_SCHEMA_VERSION,
    "arelle_error_policy_version": ARELLE_ERROR_POLICY_VERSION,
    "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
    "samples_policy_version": SAMPLES_POLICY_VERSION,
    "catalog_generator_version": CATALOG_GENERATOR_VERSION,
    "discovery_extraction_policy_version": DISCOVERY_EXTRACTION_POLICY_VERSION,
}


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def find_entrypoint(draft: Any, working: Path) -> Path:
    primary = draft.primary_document
    if primary:
        candidate = working / "accession" / primary
        if candidate.is_file():
            return candidate
    accession_dir = working / "accession"
    html_candidates = sorted(accession_dir.glob("*.htm")) + sorted(accession_dir.glob("*.html"))
    for path in html_candidates:
        if path.name.lower().endswith(("-index.html", "-index.htm")):
            continue
        return path
    xml_candidates = [
        p
        for p in sorted(accession_dir.glob("*.xml"))
        if not p.name.lower().endswith(("_pre.xml", "_cal.xml", "_def.xml", "_lab.xml", "_ref.xml"))
    ]
    if xml_candidates:
        return xml_candidates[0]
    raise RuntimeError("could not locate XBRL entrypoint in accession directory")


def _run_worker(job: dict[str, Any], run_dir: Path, mode: str) -> dict[str, Any]:
    jobs_dir = run_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    job_path = jobs_dir / f"{mode}-job.json"
    result_path = jobs_dir / f"{mode}-result.json"
    job["result_path"] = str(result_path.resolve())
    job["log_path"] = str((run_dir / f"arelle-{mode}.log").resolve())
    write_json_atomic(job_path, job)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(SPIKE_DIR) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    if mode == "offline-manifest":
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
            "ALL_PROXY",
            "all_proxy",
            "XML_CATALOG_FILES",
        ):
            env.pop(key, None)

    proc = subprocess.run(
        [sys.executable, "-m", "spike_lib.worker", "--job", str(job_path)],
        cwd=str(SPIKE_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Arelle {mode} subprocess failed (exit {proc.returncode}):\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return json.loads(result_path.read_text(encoding="utf-8"))


def capture_external_dependencies(
    draft: Any,
    acquisition: AcquisitionService,
    online: dict[str, Any],
    *,
    max_external_bytes: int,
) -> dict[str, Any]:
    """Capture external closure docs via stat-first bounded streaming.

    Returns artifact association by resolved online local path (no URIs):
    ``captured_artifact_by_local_path[resolved_path] = {logical_path, content_sha256}``.
    """
    archive_base = normalize_uri(draft.archive_base)
    accession_sha = {a.sha256 for a in draft.artifacts if a.logical_path.startswith("accession/")}
    missing: list[str] = []
    captured: list[str] = []
    skipped_accession: list[str] = []
    captured_artifact_by_local_path: dict[str, dict[str, str]] = {}

    def _record_local_association(local_path: str | None, artifact: ArtifactRecord) -> None:
        if not local_path:
            return
        try:
            resolved = str(Path(local_path).resolve())
        except (OSError, ValueError):
            return
        captured_artifact_by_local_path[resolved] = {
            "logical_path": artifact.logical_path,
            "content_sha256": artifact.sha256,
        }

    for doc in online.get("closure_documents", []):
        uri = doc.get("document_uri") or doc["canonical_uri"]
        digest = doc.get("content_sha256") or ""
        local_path = doc.get("local_path")
        if not digest:
            if is_http_uri(uri) and not uri.startswith(archive_base):
                missing.append(uri)
            continue
        if digest in accession_sha or uri.startswith(archive_base):
            skipped_accession.append(uri)
            continue
        if not is_http_uri(uri):
            skipped_accession.append(uri)
            continue
        existing = draft.artifact_by_path(external_logical_path(uri))
        if existing is not None:
            captured.append(uri)
            _record_local_association(local_path, existing)
            continue
        if not local_path or not Path(local_path).is_file():
            missing.append(uri)
            continue
        artifact = acquisition.add_external_dependency_stream(
            draft,
            original_uri=uri,
            source_path=Path(local_path),
            expected_sha256=digest,
            max_external_bytes=max_external_bytes,
        )
        captured.append(uri)
        _record_local_association(local_path, artifact)

    return {
        "captured": captured,
        "skipped_accession": skipped_accession,
        "missing": missing,
        "captured_artifact_by_local_path": captured_artifact_by_local_path,
    }


def _closure_doc_uri(doc: dict[str, Any]) -> str:
    return doc.get("document_uri") or doc["canonical_uri"]


def build_uri_bindings(
    draft: Any,
    online: dict[str, Any],
    *,
    path_map: dict[str, tuple[Any, str]],
    captured_artifact_by_local_path: dict[str, dict[str, str]],
) -> list[UriBinding]:
    """Build bindings only for replay-addressable online closure documents.

    Digest verifies artifact association; it never selects the artifact.
    Primary URI policy is deterministic (accession archive URI / capture
    source_url); additional observations become replay_aliases.
    """
    archive_base = normalize_uri(draft.archive_base)
    if not archive_base.endswith("/"):
        archive_base += "/"
    bindings_by_path: dict[str, UriBinding] = {}

    for doc in online.get("closure_documents", []):
        uri = _closure_doc_uri(doc)
        if not is_http_uri(uri):
            continue
        local_path = doc.get("local_path")
        if not local_path:
            continue
        try:
            resolved = str(Path(local_path).resolve())
        except (OSError, ValueError):
            continue

        digest = doc.get("content_sha256") or ""
        artifact: Any | None = None
        captured = captured_artifact_by_local_path.get(resolved)
        if captured is not None:
            artifact = draft.artifact_by_path(captured["logical_path"])
        elif resolved in path_map:
            artifact, _canonical = path_map[resolved]
        if artifact is None or not artifact.in_payload:
            continue
        if digest and digest != artifact.sha256:
            continue

        if artifact.logical_path.startswith("accession/"):
            name = artifact.logical_path.split("/", 1)[1]
            primary = normalize_uri(archive_base + name)
        elif artifact.source_class == "external_taxonomy_dependency" and artifact.source_url:
            primary = normalize_uri(artifact.source_url)
        else:
            # Images, index pages, complete-submission .txt, discovery metadata,
            # uri-bindings, and other non-XBRL artifacts are never bound.
            continue

        binding = bindings_by_path.get(artifact.logical_path)
        if binding is None:
            binding = UriBinding(
                document_uri=primary,
                logical_path=artifact.logical_path,
                content_sha256=artifact.sha256,
            )
            bindings_by_path[artifact.logical_path] = binding

        observed = normalize_uri(uri)
        if observed != binding.document_uri and observed not in binding.replay_aliases:
            binding.replay_aliases.append(observed)

    return list(bindings_by_path.values())


def check_binding_coverage(
    online: dict[str, Any],
    bindings: list[UriBinding],
    entrypoint_document_uri: str,
) -> dict[str, Any]:
    """Criterion 5: every replay-required URI has a validated binding."""
    covered = covered_uris(bindings)
    primary_uris = {b.document_uri for b in bindings}
    uncovered_documents = sorted(
        {
            _closure_doc_uri(d)
            for d in online.get("closure_documents", [])
            if is_http_uri(_closure_doc_uri(d)) and _closure_doc_uri(d) not in covered
        }
    )
    uncovered_references = sorted({u for u in online.get("reference_uris", []) if u not in covered})
    entrypoint_primary = entrypoint_document_uri in primary_uris
    return {
        "ok": not uncovered_documents and not uncovered_references and entrypoint_primary,
        "uncovered_documents": uncovered_documents,
        "uncovered_references": uncovered_references,
        "entrypoint_is_primary_binding": entrypoint_primary,
        "binding_count": len(bindings),
        "covered_uri_count": len(covered),
    }


def pre_promotion_gate(
    online: dict[str, Any],
    offline: dict[str, Any],
    compare: dict[str, Any],
    draft: Any,
    coverage: dict[str, Any],
    manifest_errors: list[str],
    *,
    closure_hash_online: str,
    closure_hash_offline: str,
) -> dict[str, Any]:
    """Independent gate: promote only after offline replay + strict equality."""
    reasons: list[str] = []
    failure_code = FAILURE_PRE_PROMOTION_GATE
    online_snap = online.get("snapshot") or {}
    offline_snap = offline.get("snapshot") or {}
    engine_config = offline_snap.get("engine_config") or {}
    online_errors = online_snap.get("error_summary") or {}
    offline_errors = offline_snap.get("error_summary") or {}
    network_attempts = offline.get("network_attempts") or []

    if manifest_errors:
        reasons.append(f"manifest/bindings validation failed: {manifest_errors}")
        failure_code = FAILURE_MANIFEST_INVALID

    if offline.get("error"):
        reasons.append(f"offline worker top-level error: {offline['error']}")
        if failure_code == FAILURE_PRE_PROMOTION_GATE:
            failure_code = FAILURE_OFFLINE_REPLAY

    fatal_issues = [i for i in draft.issues if i.severity == "fatal"]
    if fatal_issues:
        reasons.append(
            "fatal draft issues present: " + ", ".join(sorted({i.code for i in fatal_issues}))
        )
        if failure_code == FAILURE_PRE_PROMOTION_GATE:
            failure_code = FAILURE_OFFLINE_REPLAY

    if network_attempts:
        reasons.append(f"offline network attempts: {len(network_attempts)}")

    if not engine_config.get("offline_cache_started_empty"):
        reasons.append("offline cache did not start empty")
    if not engine_config.get("offline_cache_populated_from_manifest"):
        reasons.append("offline cache was not populated from manifest")

    if online_snap.get("unresolved_uris"):
        reasons.append(f"online unresolved documents: {online_snap.get('unresolved_uris')}")
    if offline_snap.get("unresolved_uris"):
        reasons.append(f"offline unresolved documents: {offline_snap.get('unresolved_uris')}")

    if not online_errors.get("policy_passed", True):
        reasons.append("online error policy failed")
    if not offline_errors.get("policy_passed", True):
        reasons.append("offline error policy failed")

    if not bool(online_snap.get("extraction", {}).get("extraction_complete")):
        reasons.append("online relationship extraction incomplete")
    if not bool(offline_snap.get("extraction", {}).get("extraction_complete")):
        reasons.append("offline relationship extraction incomplete")

    online_edge_ext = online_snap.get("document_edge_extraction") or {}
    offline_edge_ext = offline_snap.get("document_edge_extraction") or {}
    if not bool(online_edge_ext.get("extraction_complete")):
        reasons.append("online document-edge extraction incomplete")
    if not bool(offline_edge_ext.get("extraction_complete")):
        reasons.append("offline document-edge extraction incomplete")

    if not compare.get("strict_ok"):
        reasons.append(f"strict comparison failed: {compare.get('strict_diffs')}")

    if closure_hash_online != closure_hash_offline:
        reasons.append(
            f"closure hash mismatch: online={closure_hash_online} offline={closure_hash_offline}"
        )

    if not coverage.get("ok"):
        reasons.append("binding coverage incomplete for replay-required URIs")

    return {
        "ok": not reasons,
        "failure_code": failure_code if reasons else FAILURE_PRE_PROMOTION_GATE,
        "reasons": reasons,
    }


def evaluate_success_criteria(
    *,
    draft: Any,
    online: dict[str, Any],
    offline: dict[str, Any],
    compare: dict[str, Any],
    payload_hash_1: str,
    payload_hash_2: str | None,
    semantic_hash_1: str,
    semantic_hash_2: str | None,
    closure_hash_online: str,
    closure_hash_offline: str,
    coverage: dict[str, Any],
    promotion: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    fatal_codes = {i.code for i in draft.issues if i.severity == "fatal"}
    recon = draft.sgml_reconciliation or {}
    offline_snap = offline.get("snapshot", {})
    online_snap = online.get("snapshot", {})
    network_attempts = offline.get("network_attempts") or []
    engine_config = offline_snap.get("engine_config", {})

    online_errors = online_snap.get("error_summary", {})
    offline_errors = offline_snap.get("error_summary", {})

    criteria = [
        {
            "id": 1,
            "name": "Accession directory fully enumerated",
            "passed": bool(draft.index_entries),
            "detail": {"index_entry_count": len(draft.index_entries)},
        },
        {
            "id": 2,
            "name": "Required accession files downloaded and verified",
            "passed": "MISSING_COMPLETE_SUBMISSION" not in fatal_codes
            and "MISSING_PRIMARY_DOCUMENT" not in fatal_codes
            and "FILE_SIZE_LIMIT_EXCEEDED" not in fatal_codes
            and "BUNDLE_SIZE_LIMIT_EXCEEDED" not in fatal_codes,
            "detail": {"fatal_codes": sorted(fatal_codes)},
        },
        {
            "id": 3,
            "name": "Complete-submission inventory reconciles with index",
            "passed": bool(recon.get("passed")),
            "detail": recon,
        },
        {
            "id": 4,
            "name": (
                "Online and offline Arelle loads complete without unresolved "
                "documents or unrecognized errors (recognized diagnostics reported)"
            ),
            "passed": not online_snap.get("unresolved_uris")
            and not offline_snap.get("unresolved_uris")
            and not any(
                i.get("code") == "UNRESOLVED_DTS_DOCUMENT" for i in online.get("issues", [])
            )
            and bool(online_errors.get("policy_passed", True))
            and bool(offline_errors.get("policy_passed", True)),
            "detail": {
                "online_unresolved_uris": online_snap.get("unresolved_uris"),
                "offline_unresolved_uris": offline_snap.get("unresolved_uris"),
                "online_recognized_nonblocking_error_count": online_errors.get(
                    "recognized_nonblocking_error_count"
                ),
                "offline_recognized_nonblocking_error_count": offline_errors.get(
                    "recognized_nonblocking_error_count"
                ),
                "online_unrecognized_error_count": online_errors.get("unrecognized_error_count"),
                "offline_unrecognized_error_count": offline_errors.get("unrecognized_error_count"),
            },
        },
        {
            "id": 5,
            "name": "Every replay-required URI has a validated payload binding",
            "passed": bool(coverage.get("ok")),
            "detail": coverage,
        },
        {
            "id": 6,
            "name": "Offline replay configured from manifest only, network disabled",
            "passed": (
                len(network_attempts) == 0
                and bool(engine_config.get("offline_cache_started_empty"))
                and bool(engine_config.get("offline_cache_populated_from_manifest"))
                and bool(engine_config.get("work_offline"))
                and bool(engine_config.get("deny_network"))
                and "error" not in offline
            ),
            "detail": {
                "offline_network_attempt_count": len(network_attempts),
                "offline_cache_started_empty": engine_config.get("offline_cache_started_empty"),
                "offline_cache_populated_from_manifest": engine_config.get(
                    "offline_cache_populated_from_manifest"
                ),
                "work_offline": engine_config.get("work_offline"),
                "deny_network": engine_config.get("deny_network"),
                "network_attempts": network_attempts,
                "offline_completed_without_error": "error" not in offline,
                "promotion_outcome": (promotion or {}).get("outcome"),
            },
        },
        {
            "id": 7,
            "name": (
                "Online/offline counts, document sets, relationship/resource "
                "occurrences match; extraction complete"
            ),
            "passed": compare["strict_ok"]
            and bool(online_snap.get("extraction", {}).get("extraction_complete"))
            and bool(offline_snap.get("extraction", {}).get("extraction_complete")),
            "detail": {
                "strict_diffs": compare["strict_diffs"],
                "allowed_diffs": compare["allowed_diffs"],
                "online_extraction": online_snap.get("extraction"),
                "offline_extraction": offline_snap.get("extraction"),
            },
        },
        {
            "id": 8,
            "name": "Closure hash matches",
            "passed": closure_hash_online == closure_hash_offline,
            "detail": {"online": closure_hash_online, "offline": closure_hash_offline},
        },
        {
            "id": 9,
            "name": "Repeat yields identical payload and semantic run hashes",
            "passed": payload_hash_2 is not None
            and semantic_hash_2 is not None
            and payload_hash_1 == payload_hash_2
            and semantic_hash_1 == semantic_hash_2,
            "detail": {
                "payload_hash": payload_hash_1,
                "payload_hash_repeat": payload_hash_2,
                "semantic_run_hash": semantic_hash_1,
                "semantic_run_hash_repeat": semantic_hash_2,
            },
        },
        {
            "id": 10,
            "name": "Differences explicitly explained",
            "passed": compare["criterion_10_ok"],
            "detail": {
                "strict_diffs": compare["strict_diffs"],
                "allowed_diffs": compare["allowed_diffs"],
                "unexplained_diffs": compare["unexplained_diffs"],
            },
        },
    ]
    return criteria


def _side_evidence(snapshot: dict[str, Any], *, include_records: bool = False) -> dict[str, Any]:
    """Evidence projection of one load side (no operational/local fields)."""
    side = {
        "concept_count": snapshot["concept_count"],
        "context_count": snapshot["context_count"],
        "unit_count": snapshot["unit_count"],
        "fact_count": snapshot["fact_count"],
        "relationship_counts": snapshot["relationship_counts"],
        "resource_relationship_counts": snapshot["resource_relationship_counts"],
        "concept_relationship_occurrence_hash": snapshot["concept_relationship_occurrence_hash"],
        "resource_relationship_occurrence_hash": snapshot["resource_relationship_occurrence_hash"],
        "documents": snapshot["documents"],
        "edges": snapshot["edges"],
        "synthetic_documents": snapshot["synthetic_documents"],
        "synthetic_document_set_hash": snapshot["synthetic_document_set_hash"],
        "synthetic_document_count": snapshot["synthetic_document_count"],
        "synthetic_edges": snapshot["synthetic_edges"],
        "synthetic_edge_set_hash": snapshot["synthetic_edge_set_hash"],
        "synthetic_edge_count": snapshot["synthetic_edge_count"],
        "entry_points": snapshot["entry_points"],
        "unresolved_uris": snapshot["unresolved_uris"],
        "unsupported_inventory": snapshot["unsupported_inventory"],
        "extraction": snapshot["extraction"],
        "document_edge_extraction": snapshot.get("document_edge_extraction"),
        "error_summary": snapshot["error_summary"],
        "fact_locator_stats": snapshot["fact_locator_stats"],
    }
    if include_records:
        side["concept_records"] = snapshot["concept_records"]
        side["resource_records"] = snapshot["resource_records"]
    return side


def _sample_records(records: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    """Deterministic small samples ordered by canonical_json_bytes of canonical_record."""
    ordered = sorted(
        records,
        key=lambda r: canonical_json_bytes(r.get("canonical_record") or r),
    )
    return ordered[:limit]


def build_inspection_samples(
    *,
    online_snap: dict[str, Any],
    offline_snap: dict[str, Any],
) -> dict[str, Any]:
    """Non-authoritative review samples; excluded from semantic_run_hash."""
    return {
        "samples_policy_version": SAMPLES_POLICY_VERSION,
        "online": {
            "concept_records": _sample_records(online_snap.get("concept_records") or []),
            "resource_records": _sample_records(online_snap.get("resource_records") or []),
        },
        "offline": {
            "concept_records": _sample_records(offline_snap.get("concept_records") or []),
            "resource_records": _sample_records(offline_snap.get("resource_records") or []),
        },
    }


def build_inspection_core(
    *,
    draft: Any,
    online: dict[str, Any],
    offline: dict[str, Any],
    payload_hash_value: str,
    closure_hash_value: str,
    criteria: list[dict[str, Any]],
    compare: dict[str, Any],
    semantic_run_hash_value: str,
    include_records: bool = False,
) -> dict[str, Any]:
    online_snap = online["snapshot"]
    offline_snap = offline["snapshot"]
    return {
        "spike": "arelle_offline_closure",
        "schema_versions": SCHEMA_VERSIONS,
        "cik": draft.cik,
        "accession": draft.accession,
        "payload_hash": payload_hash_value,
        "closure_hash": closure_hash_value,
        "semantic_run_hash": semantic_run_hash_value,
        "engine": {
            "name": online_snap["engine_name"],
            "version": online_snap["engine_version"],
            "config": online_snap["engine_config"],
        },
        "online": _side_evidence(online_snap, include_records=include_records),
        "offline": _side_evidence(offline_snap, include_records=include_records),
        "compare": strict_comparison_projection(compare),
        "success_criteria": criteria,
        "quality_issues": [i.to_dict() for i in draft.issues],
    }


def run_pipeline_once(
    *,
    cik: str,
    accession: str,
    accession_root: Path,
    user_agent: str,
    max_file: int,
    max_bundle: int,
    max_external: int,
    max_redirects: int,
    min_interval: float,
    run_id: str,
) -> dict[str, Any]:
    run_dir = accession_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    store = ObjectStore(accession_root)

    with SecClient(
        user_agent,
        min_interval_seconds=min_interval,
        max_redirects=max_redirects,
    ) as client:
        acquisition = AcquisitionService(
            client,
            store,
            max_file_bytes=max_file,
            max_bundle_bytes=max_bundle,
        )
        draft = acquisition.acquire(cik, accession)

        working = run_dir / "working"
        materialize_working_tree(store, draft.artifacts, working)
        entrypoint = find_entrypoint(draft, working)
        print(f"Entrypoint: {entrypoint.relative_to(working)}")

        path_map = build_accession_uri_map(
            archive_base=draft.archive_base,
            artifacts=draft.artifacts,
            working=working,
        )
        uri_aliases: dict[str, str] = {
            local: canonical for local, (_artifact, canonical) in path_map.items()
        }
        entrypoint_document_uri = uri_aliases.get(str(entrypoint.resolve()))
        if entrypoint_document_uri is None:
            raise RuntimeError("entrypoint has no canonical URI identity")

        online_cache = run_dir / "cache" / "online"
        print("Loading with Arelle (online subprocess, isolated cache) ...")
        online = _run_worker(
            {
                "mode": "online",
                "entrypoint": str(entrypoint.resolve()),
                "cache_dir": str(online_cache.resolve()),
                "user_agent": user_agent,
                "uri_aliases": uri_aliases,
            },
            run_dir,
            "online",
        )
        for issue in online.get("issues", []):
            draft.issues.append(
                QualityIssue(
                    severity=issue["severity"],
                    code=issue["code"],
                    message=issue["message"],
                    context=issue.get("context") or {},
                )
            )

        capture_detail = capture_external_dependencies(
            draft,
            acquisition,
            online,
            max_external_bytes=max_external,
        )

        bindings = build_uri_bindings(
            draft,
            online,
            path_map=path_map,
            captured_artifact_by_local_path=capture_detail["captured_artifact_by_local_path"],
        )
        bindings_bytes = serialize_bindings(bindings)
        bindings_obj = store.put_bytes(bindings_bytes)
        if draft.artifact_by_path(URI_BINDINGS_LOGICAL_PATH) is None:
            draft.artifacts.append(
                ArtifactRecord(
                    logical_path=URI_BINDINGS_LOGICAL_PATH,
                    sha256=bindings_obj.sha256,
                    byte_size=bindings_obj.byte_size,
                    source_url=None,
                    final_url=None,
                    source_class="generated",
                    artifact_role="uri_bindings",
                    content_type="application/json",
                    required=True,
                    in_payload=True,
                    notes="authoritative offline replay bindings; never binds itself",
                )
            )

        coverage = check_binding_coverage(online, bindings, entrypoint_document_uri)

        manifest = build_sterile_manifest(
            draft,
            entrypoint_document_uri=entrypoint_document_uri,
            bindings_count=len(bindings),
        )
        manifest_errors = validate_manifest_structure(manifest)
        manifest_errors.extend(validate_uri_bindings_pointer(manifest, bindings_bytes))
        payload_hash_value = manifest["payload_hash"]

        staging_dir = stage_candidate(accession_root, manifest)
        staged_manifest_path = staging_dir / "manifest.json"
        manifest_sha256 = sha256_hex(staged_manifest_path.read_bytes())

        # Destroy online state before offline replay.
        if online_cache.exists():
            shutil.rmtree(online_cache)

        promotion: dict[str, Any] | None = None
        failed_dir: str | None = None
        if manifest_errors:
            offline = {
                "mode": "offline-manifest",
                "error": "MANIFEST_INVALID",
                "snapshot": {},
                "closure_documents": [],
                "closure_edges": [],
                "reference_uris": [],
                "issues": [
                    {
                        "severity": "fatal",
                        "code": "MANIFEST_INVALID",
                        "message": "manifest/bindings validation failed",
                        "context": {"errors": manifest_errors},
                    }
                ],
                "network_attempts": [],
            }
            failed_dir = str(
                discard_candidate(
                    accession_root,
                    staging_dir,
                    reason="manifest invalid",
                    failure_code=FAILURE_MANIFEST_INVALID,
                )
            )
        else:
            print(
                "Loading with Arelle (offline subprocess, manifest+bindings only, "
                "network denied) ..."
            )
            offline = _run_worker(
                {
                    "mode": "offline-manifest",
                    "manifest_path": str(staged_manifest_path.resolve()),
                    "object_store_root": str(accession_root.resolve()),
                    "expected_manifest_sha256": manifest_sha256,
                    "cache_dir": str((run_dir / "cache" / "offline").resolve()),
                    "work_dir": str((run_dir / "offline-working").resolve()),
                    "user_agent": user_agent,
                },
                run_dir,
                "offline-manifest",
            )
            for issue in offline.get("issues", []):
                draft.issues.append(
                    QualityIssue(
                        severity=issue["severity"],
                        code=issue["code"],
                        message=issue["message"],
                        context=issue.get("context") or {},
                    )
                )

    online_snap = online.get("snapshot", {})
    offline_snap = offline.get("snapshot", {})

    online_docs = [
        {
            "document_uri": d.get("document_uri") or d["canonical_uri"],
            "content_sha256": d["content_sha256"],
            "document_type": d["document_type"],
        }
        for d in online_snap.get("documents", [])
    ]
    online_edges = list(online_snap.get("edges", []))
    closure_hash_online = closure_hash(online_docs, online_edges)
    offline_docs = [
        {
            "document_uri": d.get("document_uri") or d["canonical_uri"],
            "content_sha256": d["content_sha256"],
            "document_type": d["document_type"],
        }
        for d in offline_snap.get("documents", [])
    ]
    offline_edges = list(offline_snap.get("edges", []))
    closure_hash_offline = closure_hash(offline_docs, offline_edges)

    compare = compare_snapshots(
        online_snap,
        offline_snap,
        closure_hash_online=closure_hash_online,
        closure_hash_offline=closure_hash_offline,
        offline_network_attempt_count=len(offline.get("network_attempts") or []),
        offline_cache_was_empty=bool(
            offline_snap.get("engine_config", {}).get("offline_cache_started_empty")
        ),
    )

    gate = pre_promotion_gate(
        online,
        offline,
        compare,
        draft,
        coverage,
        manifest_errors,
        closure_hash_online=closure_hash_online,
        closure_hash_offline=closure_hash_offline,
    )

    # Promote only after the pre-promotion gate; never before compare/extraction.
    if failed_dir is None:
        if gate["ok"]:
            promotion = promote_candidate(accession_root, staging_dir, manifest)
            write_json_atomic(Path(run_dir) / "promotion.json", promotion)
        else:
            failed_dir = str(
                discard_candidate(
                    accession_root,
                    staging_dir,
                    reason="; ".join(gate["reasons"]) or "pre-promotion gate failed",
                    failure_code=gate["failure_code"],
                )
            )

    return {
        "draft": draft,
        "online": online,
        "offline": offline,
        "compare": compare,
        "payload_hash": payload_hash_value,
        "closure_hash_online": closure_hash_online,
        "closure_hash_offline": closure_hash_offline,
        "capture_detail": capture_detail,
        "coverage": coverage,
        "promotion": promotion,
        "gate": gate,
        "failed_dir": failed_dir,
        "manifest_errors": manifest_errors,
        "run_dir": str(run_dir),
        "working": str(working),
        "entrypoint": str(entrypoint.relative_to(working)),
        "entrypoint_document_uri": entrypoint_document_uri,
    }


def _partial_criteria(run: dict[str, Any]) -> list[dict[str, Any]]:
    return evaluate_success_criteria(
        draft=run["draft"],
        online=run["online"],
        offline=run["offline"],
        compare=run["compare"],
        payload_hash_1=run["payload_hash"],
        payload_hash_2=None,
        semantic_hash_1="",
        semantic_hash_2=None,
        closure_hash_online=run["closure_hash_online"],
        closure_hash_offline=run["closure_hash_offline"],
        coverage=run["coverage"],
        promotion=run["promotion"],
    )


def _semantic_hash_for(run: dict[str, Any], criteria: list[dict[str, Any]]) -> str:
    identity = build_semantic_run_identity(
        cik=run["draft"].cik,
        accession=run["draft"].accession,
        payload_hash=run["payload_hash"],
        closure_hash=run["closure_hash_online"],
        engine={
            "name": run["online"]["snapshot"]["engine_name"],
            "version": run["online"]["snapshot"]["engine_version"],
            "config": run["online"]["snapshot"]["engine_config"],
        },
        online_snapshot=run["online"]["snapshot"],
        offline_snapshot=run["offline"]["snapshot"],
        strict_comparison=strict_comparison_projection(run["compare"]),
        criteria=criteria,
    )
    return semantic_run_hash(identity)


def run_spike(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    _load_dotenv(repo_root / ".env")

    user_agent = os.environ.get("SEC_USER_AGENT", "").strip()
    if not user_agent:
        print(
            "ERROR: SEC_USER_AGENT is required (set in environment or .env). "
            'Example: SEC_USER_AGENT="Name email@example.com"',
            file=sys.stderr,
        )
        return 2

    try:
        assert_cik_accession_consistent(args.cik, args.accession)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    cik = normalize_cik(args.cik)
    accession = validate_accession(args.accession)
    data_root = Path(args.data_root).resolve()
    spikes_root = data_root / "spikes"
    spikes_root.mkdir(parents=True, exist_ok=True)
    accession_root = assert_path_under(spikes_root / accession, spikes_root)

    if args.clean and accession_root.exists():
        assert_path_under(accession_root, spikes_root)
        shutil.rmtree(accession_root)
    accession_root.mkdir(parents=True, exist_ok=True)

    max_file = _env_int("MAX_FILE_BYTES", args.max_file_bytes)
    max_bundle = _env_int("MAX_BUNDLE_BYTES", args.max_bundle_bytes)
    max_external = _env_int("MAX_EXTERNAL_DEPENDENCY_BYTES", args.max_external_bytes)
    max_redirects = _env_int("MAX_REDIRECTS", args.max_redirects)
    min_interval = _env_float("SEC_MIN_INTERVAL_SECONDS", args.min_interval)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    print(f"Spike accession root: {accession_root}")
    print(f"Run id: {run_id}")
    print(f"Acquiring {cik} / {accession} ...")

    first = run_pipeline_once(
        cik=cik,
        accession=accession,
        accession_root=accession_root,
        user_agent=user_agent,
        max_file=max_file,
        max_bundle=max_bundle,
        max_external=max_external,
        max_redirects=max_redirects,
        min_interval=min_interval,
        run_id=run_id,
    )

    criteria_partial = _partial_criteria(first)
    sem_hash_1 = _semantic_hash_for(first, criteria_partial)

    payload_hash_repeat = None
    semantic_hash_repeat = None
    second: dict[str, Any] | None = None

    if args.repeat:
        if not (first.get("gate") or {}).get("ok"):
            print(
                "Aborting repeat: first run failed pre-promotion gate "
                f"({(first.get('gate') or {}).get('failure_code')})"
            )
        else:
            print("Repeating full pipeline in a fresh run directory ...")
            second = run_pipeline_once(
                cik=cik,
                accession=accession,
                accession_root=accession_root,
                user_agent=user_agent,
                max_file=max_file,
                max_bundle=max_bundle,
                max_external=max_external,
                max_redirects=max_redirects,
                min_interval=min_interval,
                run_id=run_id + "-repeat",
            )
            repeat_partial = _partial_criteria(second)
            payload_hash_repeat = second["payload_hash"]
            semantic_hash_repeat = _semantic_hash_for(second, repeat_partial)

    draft = first["draft"]
    criteria = evaluate_success_criteria(
        draft=draft,
        online=first["online"],
        offline=first["offline"],
        compare=first["compare"],
        payload_hash_1=first["payload_hash"],
        payload_hash_2=payload_hash_repeat if args.repeat else None,
        semantic_hash_1=sem_hash_1,
        semantic_hash_2=semantic_hash_repeat if args.repeat else None,
        closure_hash_online=first["closure_hash_online"],
        closure_hash_offline=first["closure_hash_offline"],
        coverage=first["coverage"],
        promotion=first["promotion"],
    )
    if not args.repeat:
        for item in criteria:
            if item["id"] == 9:
                item["passed"] = False
                item["detail"] = {"reason": "repeat not requested; criterion 9 requires --repeat"}

    # Finalization: gates → semantic hashes → criterion 9 → write compact core.
    inspection_core = build_inspection_core(
        draft=draft,
        online=first["online"],
        offline=first["offline"],
        payload_hash_value=first["payload_hash"],
        closure_hash_value=first["closure_hash_online"],
        criteria=criteria,
        compare=first["compare"],
        semantic_run_hash_value=sem_hash_1,
        include_records=False,
    )
    inspection_full = build_inspection_core(
        draft=draft,
        online=first["online"],
        offline=first["offline"],
        payload_hash_value=first["payload_hash"],
        closure_hash_value=first["closure_hash_online"],
        criteria=criteria,
        compare=first["compare"],
        semantic_run_hash_value=sem_hash_1,
        include_records=True,
    )
    inspection_samples = build_inspection_samples(
        online_snap=first["online"]["snapshot"],
        offline_snap=first["offline"]["snapshot"],
    )

    run_dir = Path(first["run_dir"])
    write_json_atomic(run_dir / "inspection-core.json", inspection_core)
    full_bytes = write_json_atomic(run_dir / "inspection-full.json", inspection_full)
    write_json_atomic(run_dir / "inspection-samples.json", inspection_samples)
    full_inspection_sha256 = sha256_hex(full_bytes)
    write_json_atomic(
        run_dir / "quality-issues.json",
        [i.to_dict() for i in draft.issues],
    )
    run_meta = {
        "run_id": run_id,
        "cik": cik,
        "accession": accession,
        "payload_hash": first["payload_hash"],
        "closure_hash": first["closure_hash_online"],
        "semantic_run_hash": sem_hash_1,
        "promotion": first["promotion"],
        "pre_promotion_gate": first.get("gate"),
        "failed_candidate_dir": first["failed_dir"],
        "full_inspection_sha256": full_inspection_sha256,
        "command": list(sys.argv),
        "python": sys.version,
        "repeat_run_id": (run_id + "-repeat") if args.repeat else None,
        "payload_hash_repeat": payload_hash_repeat,
        "semantic_run_hash_repeat": semantic_hash_repeat,
        "working_dir": first["working"],
        "entrypoint": first["entrypoint"],
        "entrypoint_document_uri": first["entrypoint_document_uri"],
        "online_log_sha256": first["online"].get("log_sha256"),
        "offline_log_sha256": first["offline"].get("log_sha256"),
    }
    write_json_atomic(run_dir / "run.json", run_meta)

    print()
    print("=== Slice 0 success criteria ===")
    all_passed = True
    for item in criteria:
        status = "PASS" if item["passed"] else "FAIL"
        if not item["passed"]:
            all_passed = False
        print(f"[{status}] {item['id']:2d}. {item['name']}")
        if not item["passed"] and item.get("detail"):
            detail = item["detail"]
            if isinstance(detail, dict):
                keys = list(detail.keys())[:6]
                short = {k: detail[k] for k in keys}
                print(f"         detail={short}")
            else:
                print(f"         detail={detail}")

    online_snap = first["online"]["snapshot"]
    print()
    print(f"payload_hash:     {first['payload_hash']}")
    print(f"closure_hash:     {first['closure_hash_online']}")
    print(f"semantic_run:     {sem_hash_1}")
    print(f"concepts/facts:   {online_snap['concept_count']}/{online_snap['fact_count']}")
    print(f"concept_rels:     {online_snap['concept_relationship_occurrence_hash']}")
    print(f"resource_rels:    {online_snap['resource_relationship_occurrence_hash']}")
    print(f"promotion:        {(first['promotion'] or {}).get('outcome')}")
    print(f"gate:             {(first.get('gate') or {}).get('ok')}")
    print(f"run:              {run_dir}")
    print(f"inspection:       {run_dir / 'inspection-core.json'}")
    print(f"inspection-full:  {run_dir / 'inspection-full.json'}")
    print(f"samples:          {run_dir / 'inspection-samples.json'}")

    return 0 if all_passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cik", default="0001065088")
    parser.add_argument("--accession", default="0001065088-24-000036")
    parser.add_argument("--data-root", default="var")
    parser.add_argument("--clean", action="store_true", help="Remove prior spike output first")
    parser.add_argument(
        "--repeat",
        action="store_true",
        help="Re-run the full pipeline to verify payload and semantic run hash stability",
    )
    parser.add_argument("--max-file-bytes", type=int, default=100 * 1024 * 1024)
    parser.add_argument("--max-bundle-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--max-external-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--max-redirects", type=int, default=5)
    parser.add_argument("--min-interval", type=float, default=0.2)
    args = parser.parse_args()
    raise SystemExit(run_spike(args))


if __name__ == "__main__":
    main()
