#!/usr/bin/env python3
"""Slice 0 reproducible spike: accession mirror → Arelle online/offline closure.

Spike code has no compatibility guarantees. Evidence under var/spikes/ is retained.

Offline replay and full repeats run in fresh subprocesses.
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
    CATALOG_GENERATOR_VERSION,
)
from spike_lib.acquisition import (  # noqa: E402
    AcquisitionService,
    ArtifactRecord,
    stage_and_commit_bundle,
)
from spike_lib.arelle_load import (  # noqa: E402
    build_accession_uri_map,
    build_oasis_catalog,
    external_logical_path,
    is_http_uri,
    materialize_arelle_web_cache,
    materialize_working_tree,
    normalize_uri_for_identity,
)
from spike_lib.compare import compare_snapshots  # noqa: E402
from spike_lib.hashing import (  # noqa: E402
    closure_hash,
    inspection_hash,
    sha256_hex,
)
from spike_lib.quality import QualityIssue  # noqa: E402
from spike_lib.sec import (  # noqa: E402
    SecClient,
    assert_cik_accession_consistent,
    assert_path_under,
    normalize_cik,
    validate_accession,
)
from spike_lib.storage import ObjectStore, write_json_atomic  # noqa: E402


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


def run_arelle_subprocess(
    *,
    mode: str,
    entrypoint: Path,
    cache_dir: Path,
    catalog_path: Path | None,
    user_agent: str,
    uri_aliases: dict[str, str],
    catalogued_uris: list[str] | None,
    deny_network: bool,
    run_dir: Path,
    offline_cache_started_empty: bool | None = None,
    offline_cache_populated_from_manifest: bool | None = None,
    reset_cache: bool = True,
) -> dict[str, Any]:
    jobs_dir = run_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    job_path = jobs_dir / f"{mode}-job.json"
    result_path = jobs_dir / f"{mode}-result.json"
    log_path = run_dir / f"arelle-{mode}.log"
    if reset_cache and cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    job = {
        "mode": mode,
        "entrypoint": str(entrypoint.resolve()),
        "cache_dir": str(cache_dir.resolve()),
        "catalog_path": str(catalog_path.resolve()) if catalog_path else None,
        "user_agent": user_agent,
        "uri_aliases": uri_aliases,
        "catalogued_uris": catalogued_uris or [],
        "deny_network": deny_network,
        "offline_cache_started_empty": offline_cache_started_empty,
        "offline_cache_populated_from_manifest": offline_cache_populated_from_manifest,
        "log_path": str(log_path.resolve()),
        "result_path": str(result_path.resolve()),
    }
    write_json_atomic(job_path, job)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(SPIKE_DIR) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    # Ensure offline subprocess does not inherit proxy config.
    if mode == "offline":
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
            "ALL_PROXY",
            "all_proxy",
        ):
            env.pop(key, None)
        env.pop("XML_CATALOG_FILES", None)
        if catalog_path is not None:
            env["XML_CATALOG_FILES"] = str(catalog_path.resolve())

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


def evaluate_success_criteria(
    *,
    draft: Any,
    online: dict[str, Any],
    offline: dict[str, Any],
    compare: dict[str, Any],
    payload_hash_1: str,
    payload_hash_2: str | None,
    inspection_hash_1: str,
    inspection_hash_2: str | None,
    closure_hash_online: str,
    closure_hash_offline: str,
    external_capture_ok: bool,
    external_capture_detail: dict[str, Any],
) -> list[dict[str, Any]]:
    fatal_codes = {i.code for i in draft.issues if i.severity == "fatal"}
    recon = draft.sgml_reconciliation or {}
    offline_snap = offline.get("snapshot", {})
    online_snap = online.get("snapshot", {})
    network_attempts = offline.get("network_attempts") or []

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
            "name": "Online Arelle load without unresolved required documents",
            "passed": not online_snap.get("unresolved_uris")
            and not any(
                i.get("code") == "UNRESOLVED_DTS_DOCUMENT" for i in online.get("issues", [])
            ),
            "detail": {"unresolved_uris": online_snap.get("unresolved_uris")},
        },
        {
            "id": 5,
            "name": "Every loaded external URI maps to captured content object",
            "passed": external_capture_ok,
            "detail": external_capture_detail,
        },
        {
            "id": 6,
            "name": "Offline load configured with network disabled",
            "passed": (
                len(network_attempts) == 0
                and bool(offline_snap.get("engine_config", {}).get("offline_cache_started_empty"))
                and bool(
                    offline_snap.get("engine_config", {}).get(
                        "offline_cache_populated_from_manifest"
                    )
                )
                and bool(offline_snap.get("engine_config", {}).get("work_offline"))
                and bool(offline_snap.get("engine_config", {}).get("deny_network"))
            ),
            "detail": {
                "offline_network_attempt_count": len(network_attempts),
                "offline_cache_started_empty": offline_snap.get("engine_config", {}).get(
                    "offline_cache_started_empty"
                ),
                "offline_cache_populated_from_manifest": offline_snap.get("engine_config", {}).get(
                    "offline_cache_populated_from_manifest"
                ),
                "work_offline": offline_snap.get("engine_config", {}).get("work_offline"),
                "deny_network": offline_snap.get("engine_config", {}).get("deny_network"),
                "network_attempts": network_attempts,
            },
        },
        {
            "id": 7,
            "name": "Online/offline counts and document sets match",
            "passed": compare["strict_ok"],
            "detail": {
                "strict_diffs": compare["strict_diffs"],
                "allowed_diffs": compare["allowed_diffs"],
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
            "name": "Repeat yields identical payload and inspection hashes",
            "passed": payload_hash_2 is not None
            and inspection_hash_2 is not None
            and payload_hash_1 == payload_hash_2
            and inspection_hash_1 == inspection_hash_2,
            "detail": {
                "payload_hash": payload_hash_1,
                "payload_hash_repeat": payload_hash_2,
                "inspection_hash": inspection_hash_1,
                "inspection_hash_repeat": inspection_hash_2,
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


def build_inspection_core(
    *,
    draft: Any,
    online: dict[str, Any],
    offline: dict[str, Any],
    payload_hash_value: str,
    closure_hash_value: str,
    catalog_sha256: str,
    criteria: list[dict[str, Any]],
    compare: dict[str, Any],
    online_log_sha256: str | None,
    offline_log_sha256: str | None,
) -> dict[str, Any]:
    online_snap = online["snapshot"]
    offline_snap = offline["snapshot"]
    return {
        "spike": "arelle_offline_closure",
        "acquisition_policy_version": ACQUISITION_POLICY_VERSION,
        "catalog_generator_version": CATALOG_GENERATOR_VERSION,
        "cik": draft.cik,
        "accession": draft.accession,
        "payload_hash": payload_hash_value,
        "closure_hash": closure_hash_value,
        "catalog_sha256": catalog_sha256,
        "catalog_excluded_from_payload_hash": True,
        "discovery": draft.discovery,
        "sgml_reconciliation": draft.sgml_reconciliation,
        "engine": {
            "name": online_snap["engine_name"],
            "version": online_snap["engine_version"],
            "config": online_snap["engine_config"],
        },
        "online": {
            "concept_count": online_snap["concept_count"],
            "context_count": online_snap["context_count"],
            "unit_count": online_snap["unit_count"],
            "fact_count": online_snap["fact_count"],
            "relationship_counts": online_snap["relationship_counts"],
            "relationship_set_hash": online_snap["relationship_set_hash"],
            "entry_points": online_snap["entry_points"],
            "documents": online_snap["documents"],
            "edges": online_snap["edges"],
            "fact_locator_stats": online_snap["fact_locator_stats"],
            "unresolved_uris": online_snap["unresolved_uris"],
            "log_sha256": online_log_sha256,
        },
        "offline": {
            "concept_count": offline_snap["concept_count"],
            "context_count": offline_snap["context_count"],
            "unit_count": offline_snap["unit_count"],
            "fact_count": offline_snap["fact_count"],
            "relationship_counts": offline_snap["relationship_counts"],
            "relationship_set_hash": offline_snap["relationship_set_hash"],
            "entry_points": offline_snap["entry_points"],
            "documents": offline_snap["documents"],
            "edges": offline_snap["edges"],
            "unresolved_uris": offline_snap["unresolved_uris"],
            "log_sha256": offline_log_sha256,
            "offline_cache_was_empty": offline.get("offline_cache_was_empty"),
            "network_attempt_count": len(offline.get("network_attempts") or []),
        },
        "compare": {
            "strict_diffs": compare["strict_diffs"],
            "allowed_diffs": compare["allowed_diffs"],
            "unexplained_diffs": compare["unexplained_diffs"],
        },
        "success_criteria": [
            {"id": c["id"], "name": c["name"], "passed": c["passed"], "detail": c.get("detail")}
            for c in criteria
        ],
        "quality_issues": [i.to_dict() for i in draft.issues],
    }


def capture_external_dependencies(
    draft: Any,
    acquisition: AcquisitionService,
    online: dict[str, Any],
    *,
    max_external_bytes: int,
    store: ObjectStore,
) -> dict[str, Any]:
    """Capture external closure docs; never re-add accession artifacts as externals."""
    archive_base = normalize_uri_for_identity(draft.archive_base)
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
        # Belonging to an accession artifact by hash or archive URI → never external.
        if digest in accession_sha or uri.startswith(archive_base):
            skipped_accession.append(uri)
            continue
        if not is_http_uri(uri):
            # Non-HTTP and not accession: should have been aliased; skip adding as external.
            skipped_accession.append(uri)
            continue
        if draft.artifact_by_path(external_logical_path(uri)) is not None:
            captured.append(uri)
            continue
        if not local_path or not Path(local_path).is_file():
            missing.append(uri)
            continue
        data = Path(local_path).read_bytes()
        if sha256_hex(data) != digest:
            missing.append(uri)
            continue
        acquisition.add_external_dependency(
            draft,
            original_uri=uri,
            data=data,
            final_url=uri,
            max_external_bytes=max_external_bytes,
        )
        captured.append(uri)

    # Criterion 5: every external HTTP closure URI maps to a payload external artifact.
    external_artifacts = {
        normalize_uri_for_identity(a.source_url or ""): a.sha256
        for a in draft.artifacts
        if a.source_class == "external_taxonomy_dependency" and a.source_url
    }
    expected_external = []
    for doc in online.get("closure_documents", []):
        uri = doc["canonical_uri"]
        digest = doc.get("content_sha256")
        if (
            is_http_uri(uri)
            and not uri.startswith(archive_base)
            and digest
            and digest not in accession_sha
        ):
            expected_external.append((uri, digest))

    mismatches = []
    for uri, digest in expected_external:
        art_digest = external_artifacts.get(normalize_uri_for_identity(uri))
        if art_digest != digest:
            mismatches.append(
                {
                    "uri": uri,
                    "expected_sha256": digest,
                    "artifact_sha256": art_digest,
                }
            )

    return {
        "ok": not mismatches and not missing,
        "captured": captured,
        "skipped_accession": skipped_accession,
        "missing": missing,
        "mismatches": mismatches,
        "expected_external_count": len(expected_external),
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
        # uri_aliases: local path → canonical SEC URI; also content-hash helpers later.
        uri_aliases: dict[str, str] = {}
        for local_path, (_artifact, canonical) in path_map.items():
            uri_aliases[local_path] = canonical

        online_cache = run_dir / "cache" / "online"
        print("Loading with Arelle (online subprocess, isolated cache) ...")
        online = run_arelle_subprocess(
            mode="online",
            entrypoint=entrypoint,
            cache_dir=online_cache,
            catalog_path=None,
            user_agent=user_agent,
            uri_aliases=uri_aliases,
            catalogued_uris=None,
            deny_network=False,
            run_dir=run_dir,
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
            store=store,
        )

        # Rematerialize with externals; regenerate catalog from manifest objects only.
        materialize_working_tree(store, draft.artifacts, working)
        entrypoint = find_entrypoint(draft, working)
        path_map = build_accession_uri_map(
            archive_base=draft.archive_base,
            artifacts=draft.artifacts,
            working=working,
        )
        uri_aliases = {local: canonical for local, (_a, canonical) in path_map.items()}

        uri_to_path: dict[str, Path] = {}
        for artifact in draft.artifacts:
            if not artifact.in_payload:
                continue
            local = working / artifact.logical_path
            if artifact.source_url:
                uri_to_path[normalize_uri_for_identity(artifact.source_url)] = local
            if artifact.final_url:
                uri_to_path[normalize_uri_for_identity(artifact.final_url)] = local
            if artifact.logical_path.startswith("accession/"):
                name = artifact.logical_path.split("/", 1)[1]
                uri_to_path[
                    normalize_uri_for_identity(draft.archive_base.rstrip("/") + "/" + name)
                ] = local

        # Map online-loaded URIs by content hash to payload files.
        sha_to_path = {a.sha256: working / a.logical_path for a in draft.artifacts if a.in_payload}
        for doc in online.get("closure_documents", []):
            digest = doc.get("content_sha256")
            if digest and digest in sha_to_path:
                uri_to_path[doc["canonical_uri"]] = sha_to_path[digest]
                # Also alias any local path from the online result.
                if doc.get("local_path"):
                    uri_aliases[doc["local_path"]] = doc["canonical_uri"]

        catalog_path = run_dir / "offline-catalog.xml"
        catalog_bytes = build_oasis_catalog(uri_to_path, catalog_path)
        catalog_obj = store.put_bytes(catalog_bytes)
        if draft.artifact_by_path("metadata/offline-catalog.xml") is None:
            draft.artifacts.append(
                ArtifactRecord(
                    logical_path="metadata/offline-catalog.xml",
                    sha256=catalog_obj.sha256,
                    byte_size=catalog_obj.byte_size,
                    source_url=None,
                    final_url=None,
                    source_class="generated",
                    artifact_role="offline_catalog",
                    content_type="application/xml",
                    required=False,
                    in_payload=False,
                    notes=f"generator={CATALOG_GENERATOR_VERSION}; excluded from payload_hash",
                )
            )
        (working / "metadata").mkdir(parents=True, exist_ok=True)
        (working / "metadata" / "offline-catalog.xml").write_bytes(catalog_bytes)

        # Discard online cache entirely before offline.
        if online_cache.exists():
            shutil.rmtree(online_cache)

        offline_cache = run_dir / "cache" / "offline"
        if offline_cache.exists():
            shutil.rmtree(offline_cache)
        offline_cache.mkdir(parents=True, exist_ok=True)
        web_cache = offline_cache / "arelle-web-cache"
        # Start empty, then seed ONLY from manifested payload objects.
        cache_started_empty = not web_cache.exists() or not any(web_cache.rglob("*"))
        seeded = materialize_arelle_web_cache(uri_to_path, web_cache)
        print(
            f"Seeded offline Arelle cache from manifest: {len(seeded)} URIs "
            f"(started_empty={cache_started_empty})"
        )

        print("Loading with Arelle (offline subprocess, manifest-seeded cache, network denied) ...")
        offline = run_arelle_subprocess(
            mode="offline",
            entrypoint=entrypoint,
            cache_dir=offline_cache,
            catalog_path=working / "metadata" / "offline-catalog.xml",
            user_agent=user_agent,
            uri_aliases=uri_aliases,
            catalogued_uris=list(uri_to_path.keys()),
            deny_network=True,
            run_dir=run_dir,
            offline_cache_started_empty=cache_started_empty,
            offline_cache_populated_from_manifest=bool(seeded),
            reset_cache=False,
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

    payload_hash_value = draft.compute_payload_hash()
    online_snap = online["snapshot"]
    offline_snap = offline["snapshot"]

    online_docs = [
        (d["canonical_uri"], d["content_sha256"], d["document_type"])
        for d in online_snap["documents"]
    ]
    online_edges = [
        (e["source_uri"], e["discovery_type"], e["target_uri"], e["normalized_href"])
        for e in online_snap["edges"]
    ]
    closure_hash_online = closure_hash(online_docs, online_edges)
    offline_docs = [
        (d["canonical_uri"], d["content_sha256"], d["document_type"])
        for d in offline_snap["documents"]
    ]
    offline_edges = [
        (e["source_uri"], e["discovery_type"], e["target_uri"], e["normalized_href"])
        for e in offline_snap["edges"]
    ]
    closure_hash_offline = closure_hash(offline_docs, offline_edges)

    compare = compare_snapshots(
        online_snap,
        offline_snap,
        closure_hash_online=closure_hash_online,
        closure_hash_offline=closure_hash_offline,
        relationship_set_hash_online=online_snap["relationship_set_hash"],
        relationship_set_hash_offline=offline_snap["relationship_set_hash"],
        offline_network_attempt_count=len(offline.get("network_attempts") or []),
        offline_cache_was_empty=bool(
            offline_snap.get("engine_config", {}).get("offline_cache_started_empty")
        ),
    )

    bundle_dir = stage_and_commit_bundle(
        accession_root,
        draft,
        payload_hash_value=payload_hash_value,
        extra={
            "closure_hash": closure_hash_online,
            "catalog_sha256": catalog_obj.sha256,
            "catalog_generator_version": CATALOG_GENERATOR_VERSION,
            "entrypoint": str(entrypoint.relative_to(working)),
            "relationship_set_hash": online_snap["relationship_set_hash"],
        },
    )

    return {
        "draft": draft,
        "online": online,
        "offline": offline,
        "compare": compare,
        "payload_hash": payload_hash_value,
        "closure_hash_online": closure_hash_online,
        "closure_hash_offline": closure_hash_offline,
        "catalog_sha256": catalog_obj.sha256,
        "capture_detail": capture_detail,
        "bundle_dir": str(bundle_dir),
        "run_dir": str(run_dir),
        "working": str(working),
        "entrypoint": str(entrypoint.relative_to(working)),
    }


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
        # Re-assert containment before deletion.
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

    payload_hash_repeat = None
    inspection_hash_repeat = None
    second: dict[str, Any] | None = None

    # Build first inspection core WITHOUT criterion 9 repeat fields; recompute after repeat.
    draft = first["draft"]
    criteria_partial = evaluate_success_criteria(
        draft=draft,
        online=first["online"],
        offline=first["offline"],
        compare=first["compare"],
        payload_hash_1=first["payload_hash"],
        payload_hash_2=None,
        inspection_hash_1="",
        inspection_hash_2=None,
        closure_hash_online=first["closure_hash_online"],
        closure_hash_offline=first["closure_hash_offline"],
        external_capture_ok=first["capture_detail"]["ok"],
        external_capture_detail=first["capture_detail"],
    )
    # Criterion 9 fails until repeat runs when --repeat is set.
    if not args.repeat:
        for item in criteria_partial:
            if item["id"] == 9:
                item["passed"] = False
                item["detail"] = {"reason": "repeat not requested; criterion 9 requires --repeat"}

    inspection_core = build_inspection_core(
        draft=draft,
        online=first["online"],
        offline=first["offline"],
        payload_hash_value=first["payload_hash"],
        closure_hash_value=first["closure_hash_online"],
        catalog_sha256=first["catalog_sha256"],
        criteria=criteria_partial,
        compare=first["compare"],
        online_log_sha256=first["online"].get("log_sha256"),
        offline_log_sha256=first["offline"].get("log_sha256"),
    )
    # Hash excludes criterion detail that embeds repeat results; use stable subset.
    hash_payload = {k: v for k, v in inspection_core.items() if k != "success_criteria"}
    hash_payload["success_criteria"] = [
        {"id": c["id"], "name": c["name"], "passed": c["passed"]}
        for c in criteria_partial
        if c["id"] != 9  # exclude repeat criterion from identity until after repeat
    ]
    insp_hash = inspection_hash(hash_payload)

    if args.repeat:
        print("Repeating full pipeline in a fresh run directory ...")
        repeat_id = run_id + "-repeat"
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
            run_id=repeat_id,
        )
        payload_hash_repeat = second["payload_hash"]
        # Build repeat inspection the same way and hash it.
        repeat_criteria = evaluate_success_criteria(
            draft=second["draft"],
            online=second["online"],
            offline=second["offline"],
            compare=second["compare"],
            payload_hash_1=second["payload_hash"],
            payload_hash_2=None,
            inspection_hash_1="",
            inspection_hash_2=None,
            closure_hash_online=second["closure_hash_online"],
            closure_hash_offline=second["closure_hash_offline"],
            external_capture_ok=second["capture_detail"]["ok"],
            external_capture_detail=second["capture_detail"],
        )
        repeat_core = build_inspection_core(
            draft=second["draft"],
            online=second["online"],
            offline=second["offline"],
            payload_hash_value=second["payload_hash"],
            closure_hash_value=second["closure_hash_online"],
            catalog_sha256=second["catalog_sha256"],
            criteria=repeat_criteria,
            compare=second["compare"],
            online_log_sha256=second["online"].get("log_sha256"),
            offline_log_sha256=second["offline"].get("log_sha256"),
        )
        repeat_hash_payload = {k: v for k, v in repeat_core.items() if k != "success_criteria"}
        repeat_hash_payload["success_criteria"] = [
            {"id": c["id"], "name": c["name"], "passed": c["passed"]}
            for c in repeat_criteria
            if c["id"] != 9
        ]
        inspection_hash_repeat = inspection_hash(repeat_hash_payload)

    # Final criteria after repeat results exist.
    criteria = evaluate_success_criteria(
        draft=draft,
        online=first["online"],
        offline=first["offline"],
        compare=first["compare"],
        payload_hash_1=first["payload_hash"],
        payload_hash_2=payload_hash_repeat if args.repeat else None,
        inspection_hash_1=insp_hash,
        inspection_hash_2=inspection_hash_repeat if args.repeat else None,
        closure_hash_online=first["closure_hash_online"],
        closure_hash_offline=first["closure_hash_offline"],
        external_capture_ok=first["capture_detail"]["ok"],
        external_capture_detail=first["capture_detail"],
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
        catalog_sha256=first["catalog_sha256"],
        criteria=criteria,
        compare=first["compare"],
        online_log_sha256=first["online"].get("log_sha256"),
        offline_log_sha256=first["offline"].get("log_sha256"),
    )
    # Final inspection hash includes all criteria except embedding the hash itself.
    final_hash_payload = {k: v for k, v in inspection_core.items() if k != "success_criteria"}
    final_hash_payload["success_criteria"] = [
        {"id": c["id"], "name": c["name"], "passed": c["passed"]} for c in criteria
    ]
    # For criterion 9 identity comparison we already computed insp_hash excluding id 9.
    # Persist both.
    inspection_core["inspection_hash"] = insp_hash
    inspection_core["inspection_hash_with_criteria"] = inspection_hash(final_hash_payload)

    run_dir = Path(first["run_dir"])
    write_json_atomic(run_dir / "inspection-core.json", inspection_core)
    write_json_atomic(
        run_dir / "quality-issues.json",
        [i.to_dict() for i in draft.issues],
    )
    run_meta = {
        "run_id": run_id,
        "started_at": run_id.split("-")[0] if "T" in run_id else run_id,
        "cik": cik,
        "accession": accession,
        "payload_hash": first["payload_hash"],
        "closure_hash": first["closure_hash_online"],
        "inspection_hash": insp_hash,
        "bundle_dir": first["bundle_dir"],
        "command": list(sys.argv),
        "python": sys.version,
        "repeat_run_id": (run_id + "-repeat") if args.repeat else None,
        "payload_hash_repeat": payload_hash_repeat,
        "inspection_hash_repeat": inspection_hash_repeat,
        "working_dir": first["working"],
        "entrypoint": first["entrypoint"],
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
            # Keep console detail short.
            if isinstance(detail, dict):
                keys = list(detail.keys())[:6]
                short = {k: detail[k] for k in keys}
                print(f"         detail={short}")
            else:
                print(f"         detail={detail}")

    print()
    print(f"payload_hash:     {first['payload_hash']}")
    print(f"closure_hash:     {first['closure_hash_online']}")
    print(f"inspection_hash:  {insp_hash}")
    print(f"catalog_sha256:   {first['catalog_sha256']} (excluded from payload_hash)")
    print(
        f"concepts/facts:   {first['online']['snapshot']['concept_count']}/"
        f"{first['online']['snapshot']['fact_count']}"
    )
    print(f"relationship_set: {first['online']['snapshot']['relationship_set_hash']}")
    print(f"bundle:           {first['bundle_dir']}")
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
        help="Re-run the full pipeline to verify payload and inspection hash stability",
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
