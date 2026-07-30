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
    DISCOVERY_EXTRACTION_POLICY_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    PAYLOAD_HASH_SCHEMA_VERSION,
    RELATIONSHIP_SERIALIZATION_VERSION,
    RESOURCE_SERIALIZATION_VERSION,
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
from spike_lib.hashing import closure_hash, sha256_hex  # noqa: E402
from spike_lib.manifest import (  # noqa: E402
    build_sterile_manifest,
    discard_candidate,
    promote_candidate,
    stage_candidate,
    validate_manifest,
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
    validate_bindings,
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
    "synthetic_document_serialization_version": SYNTHETIC_DOCUMENT_SERIALIZATION_VERSION,
    "semantic_run_schema_version": SEMANTIC_RUN_SCHEMA_VERSION,
    "arelle_error_policy_version": ARELLE_ERROR_POLICY_VERSION,
    "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
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
    """Capture external closure docs via stat-first bounded streaming."""
    archive_base = normalize_uri(draft.archive_base)
    accession_sha = {a.sha256 for a in draft.artifacts if a.logical_path.startswith("accession/")}
    missing: list[str] = []
    captured: list[str] = []
    skipped_accession: list[str] = []

    for doc in online.get("closure_documents", []):
        uri = doc["canonical_uri"]
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
        if draft.artifact_by_path(external_logical_path(uri)) is not None:
            captured.append(uri)
            continue
        if not local_path or not Path(local_path).is_file():
            missing.append(uri)
            continue
        acquisition.add_external_dependency_stream(
            draft,
            original_uri=uri,
            source_path=Path(local_path),
            expected_sha256=digest,
            max_external_bytes=max_external_bytes,
        )
        captured.append(uri)

    return {
        "captured": captured,
        "skipped_accession": skipped_accession,
        "missing": missing,
    }


def build_uri_bindings(draft: Any, online: dict[str, Any]) -> list[UriBinding]:
    """Serialize the authoritative URI→object bindings from manifest artifacts."""
    archive_base = normalize_uri(draft.archive_base)
    if not archive_base.endswith("/"):
        archive_base += "/"
    bindings: list[UriBinding] = []
    by_logical_path: dict[str, UriBinding] = {}

    for artifact in draft.artifacts:
        if not artifact.in_payload:
            continue
        if artifact.logical_path.startswith("accession/"):
            name = artifact.logical_path.split("/", 1)[1]
            document_uri = normalize_uri(archive_base + name)
        elif artifact.source_class == "external_taxonomy_dependency" and artifact.source_url:
            document_uri = normalize_uri(artifact.source_url)
        else:
            continue
        binding = UriBinding(
            document_uri=document_uri,
            logical_path=artifact.logical_path,
            content_sha256=artifact.sha256,
        )
        bindings.append(binding)
        by_logical_path[artifact.logical_path] = binding

    # Replay aliases: loaded closure URIs whose content matches a bound artifact
    # but whose canonical URI is not itself a primary binding document_uri.
    payload_by_sha = {a.sha256: a for a in draft.artifacts if a.in_payload}
    for doc in online.get("closure_documents", []):
        uri = doc["canonical_uri"]
        digest = doc.get("content_sha256") or ""
        if not digest or not is_http_uri(uri):
            continue
        artifact = payload_by_sha.get(digest)
        if artifact is None:
            continue
        binding = by_logical_path.get(artifact.logical_path)
        if binding is None:
            continue
        if uri != binding.document_uri and uri not in binding.replay_aliases:
            binding.replay_aliases.append(uri)

    return bindings


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
            d["canonical_uri"]
            for d in online.get("closure_documents", [])
            if is_http_uri(d["canonical_uri"]) and d["canonical_uri"] not in covered
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
                "documents or unallowlisted errors"
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
                "online_unallowlisted_error_count": online_errors.get("unallowlisted_error_count"),
                "offline_unallowlisted_error_count": offline_errors.get(
                    "unallowlisted_error_count"
                ),
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
                and bool(promotion and promotion.get("outcome"))
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


def _side_evidence(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Evidence projection of one load side (no operational/local fields)."""
    return {
        "concept_count": snapshot["concept_count"],
        "context_count": snapshot["context_count"],
        "unit_count": snapshot["unit_count"],
        "fact_count": snapshot["fact_count"],
        "relationship_counts": snapshot["relationship_counts"],
        "resource_relationship_counts": snapshot["resource_relationship_counts"],
        "concept_relationship_occurrence_hash": snapshot["concept_relationship_occurrence_hash"],
        "resource_relationship_occurrence_hash": snapshot["resource_relationship_occurrence_hash"],
        "concept_records": snapshot["concept_records"],
        "resource_records": snapshot["resource_records"],
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
        "error_summary": snapshot["error_summary"],
        "fact_locator_stats": snapshot["fact_locator_stats"],
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
        "online": _side_evidence(online_snap),
        "offline": _side_evidence(offline_snap),
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

        bindings = build_uri_bindings(draft, online)
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

        artifact_hashes = {a.logical_path: a.sha256 for a in draft.artifacts}
        binding_errors = validate_bindings(
            bindings,
            manifest_artifacts=artifact_hashes,
            entrypoint_document_uri=entrypoint_document_uri,
        )
        coverage = check_binding_coverage(online, bindings, entrypoint_document_uri)

        manifest = build_sterile_manifest(draft, entrypoint_document_uri=entrypoint_document_uri)
        manifest_errors = validate_manifest(manifest)
        manifest_errors.extend(binding_errors)
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
                discard_candidate(accession_root, staging_dir, reason="manifest invalid")
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

            offline_ok = "error" not in offline and not any(
                i.get("severity") == "fatal" for i in offline.get("issues", [])
            )
            if offline_ok:
                promotion = promote_candidate(accession_root, staging_dir, manifest)
                write_json_atomic(run_dir / "promotion.json", promotion)
            else:
                failed_dir = str(
                    discard_candidate(
                        accession_root, staging_dir, reason="offline replay validation failed"
                    )
                )

    online_snap = online.get("snapshot", {})
    offline_snap = offline.get("snapshot", {})

    online_docs = [
        (d["canonical_uri"], d["content_sha256"], d["document_type"])
        for d in online_snap.get("documents", [])
    ]
    online_edges = [
        (e["source_uri"], e["discovery_type"], e["target_uri"], e["normalized_href"])
        for e in online_snap.get("edges", [])
    ]
    closure_hash_online = closure_hash(online_docs, online_edges)
    offline_docs = [
        (d["canonical_uri"], d["content_sha256"], d["document_type"])
        for d in offline_snap.get("documents", [])
    ]
    offline_edges = [
        (e["source_uri"], e["discovery_type"], e["target_uri"], e["normalized_href"])
        for e in offline_snap.get("edges", [])
    ]
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

    inspection_core = build_inspection_core(
        draft=draft,
        online=first["online"],
        offline=first["offline"],
        payload_hash_value=first["payload_hash"],
        closure_hash_value=first["closure_hash_online"],
        criteria=criteria,
        compare=first["compare"],
        semantic_run_hash_value=sem_hash_1,
    )

    run_dir = Path(first["run_dir"])
    write_json_atomic(run_dir / "inspection-core.json", inspection_core)
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
        "failed_candidate_dir": first["failed_dir"],
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
    print(f"run:              {run_dir}")
    print(f"inspection:       {run_dir / 'inspection-core.json'}")

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
