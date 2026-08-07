#!/usr/bin/env python3
"""Export sanitized, versioned spike evidence for repository commit.

The exporter copies exact bytes (no reserialization) of the promoted bundle
manifest, the URI-bindings artifact, the compact inspection core, and the
inspection samples. It verifies the full inspection digest against the run's
inspection-full.json (local only; not committed). It refuses to run unless
HEAD equals the supplied source commit and the working tree is clean.

Usage:
  uv run python scripts/spikes/export_evidence.py \
      --run-dir var/spikes/0001065088-24-000036/runs/<run-id> \
      --output fixtures/manifests/0001065088-24-000036 \
      --source-commit <implementation-commit-sha>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SPIKE_DIR = Path(__file__).resolve().parent
if str(SPIKE_DIR) not in sys.path:
    sys.path.insert(0, str(SPIKE_DIR))

from spike_lib import (  # noqa: E402
    EVIDENCE_EXPORTER_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    SAMPLES_POLICY_VERSION,
)
from spike_lib.hashing import sha256_hex  # noqa: E402
from spike_lib.storage import write_json_atomic  # noqa: E402

# Files committed and listed in evidence_file_sha256 (metadata itself excluded).
EVIDENCE_HASHED_FILES = (
    "bundle-manifest.json",
    "uri-bindings.json",
    "inspection-core.json",
    "inspection-samples.json",
    "acquisition-expectations.json",
    "parser-expectations.json",
)


def _git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def acquisition_expectations(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_schema_version": manifest["manifest_schema_version"],
        "acquisition_policy_version": manifest["acquisition_policy_version"],
        "payload_hash_schema_version": manifest["payload_hash_schema_version"],
        "cik": manifest["cik"],
        "accession": manifest["accession"],
        "payload_hash": manifest["payload_hash"],
        "artifact_count": len(manifest["artifacts"]),
        "payload_artifact_count": sum(
            1 for a in manifest["artifacts"] if a.get("in_payload", True)
        ),
        "entrypoint": manifest["entrypoint"],
    }


def parser_expectations(inspection: dict[str, Any]) -> dict[str, Any]:
    online = inspection["online"]
    offline = inspection["offline"]
    return {
        "semantic_run_schema_version": inspection["schema_versions"]["semantic_run_schema_version"],
        "payload_hash": inspection["payload_hash"],
        "closure_hash": inspection["closure_hash"],
        "semantic_run_hash": inspection["semantic_run_hash"],
        "concept_count": online["concept_count"],
        "fact_count": online["fact_count"],
        "context_count": online["context_count"],
        "unit_count": online["unit_count"],
        "concept_relationship_occurrence_hash": online["concept_relationship_occurrence_hash"],
        "resource_relationship_occurrence_hash": online["resource_relationship_occurrence_hash"],
        "offline_concept_relationship_occurrence_hash": offline[
            "concept_relationship_occurrence_hash"
        ],
        "offline_resource_relationship_occurrence_hash": offline[
            "resource_relationship_occurrence_hash"
        ],
        "unsupported_inventory": online["unsupported_inventory"],
        "extraction": online["extraction"],
        "document_edge_extraction": online.get("document_edge_extraction"),
        "criteria_passed": {str(c["id"]): c["passed"] for c in inspection["success_criteria"]},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Permit a dirty working tree (recorded in metadata)",
    )
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    output = Path(args.output).resolve()
    repo_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )

    head = _git(repo_root, "rev-parse", "HEAD")
    if head != args.source_commit:
        print(
            f"ERROR: HEAD {head} != supplied source commit {args.source_commit}. "
            "Export evidence from the exact implementation commit.",
            file=sys.stderr,
        )
        return 2
    dirty = bool(_git(repo_root, "status", "--porcelain"))
    if dirty and not args.allow_dirty:
        print(
            "ERROR: working tree is not clean; commit or stash before exporting evidence.",
            file=sys.stderr,
        )
        return 2

    run_meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    promotion = run_meta.get("promotion") or {}
    final_bundle_path = promotion.get("final_bundle_path")
    if not final_bundle_path:
        print("ERROR: run has no promoted bundle (promotion failed?)", file=sys.stderr)
        return 1
    bundle_manifest_path = Path(final_bundle_path) / "manifest.json"
    manifest_bytes = bundle_manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))

    pointer = manifest["uri_bindings_artifact"]
    accession_root = run_dir.parents[1]
    bindings_bytes = (
        accession_root / "objects" / "sha256" / pointer["sha256"][:2] / pointer["sha256"]
    ).read_bytes()
    if sha256_hex(bindings_bytes) != pointer["sha256"]:
        print("ERROR: uri-bindings object hash mismatch", file=sys.stderr)
        return 1

    inspection_core_path = run_dir / "inspection-core.json"
    inspection_full_path = run_dir / "inspection-full.json"
    samples_path = run_dir / "inspection-samples.json"
    if not inspection_core_path.is_file():
        print("ERROR: missing inspection-core.json in run dir", file=sys.stderr)
        return 1
    if not inspection_full_path.is_file():
        print("ERROR: missing inspection-full.json in run dir", file=sys.stderr)
        return 1
    if not samples_path.is_file():
        print("ERROR: missing inspection-samples.json in run dir", file=sys.stderr)
        return 1

    inspection_bytes = inspection_core_path.read_bytes()
    inspection = json.loads(inspection_bytes.decode("utf-8"))
    samples_bytes = samples_path.read_bytes()

    full_bytes = inspection_full_path.read_bytes()
    full_sha = sha256_hex(full_bytes)
    run_full_sha = run_meta.get("full_inspection_sha256") or inspection.get(
        "full_inspection_sha256"
    )
    if run_full_sha and run_full_sha != full_sha:
        print(
            f"ERROR: inspection-full.json digest mismatch: run={run_full_sha} actual={full_sha}",
            file=sys.stderr,
        )
        return 1

    output.mkdir(parents=True, exist_ok=True)
    (output / "bundle-manifest.json").write_bytes(manifest_bytes)
    (output / "uri-bindings.json").write_bytes(bindings_bytes)
    (output / "inspection-core.json").write_bytes(inspection_bytes)
    (output / "inspection-samples.json").write_bytes(samples_bytes)
    write_json_atomic(output / "acquisition-expectations.json", acquisition_expectations(manifest))
    write_json_atomic(output / "parser-expectations.json", parser_expectations(inspection))

    metadata = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "exporter_version": EVIDENCE_EXPORTER_VERSION,
        "samples_policy_version": SAMPLES_POLICY_VERSION,
        "source_commit": args.source_commit,
        "source_run_id": run_meta["run_id"],
        "working_tree_was_dirty": dirty,
        "cik": manifest["cik"],
        "accession": manifest["accession"],
        "payload_hash": manifest["payload_hash"],
        "semantic_run_hash": inspection["semantic_run_hash"],
        "evidence_file_sha256": {
            name: sha256_hex((output / name).read_bytes()) for name in EVIDENCE_HASHED_FILES
        },
        "full_inspection": {
            "sha256": full_sha,
            "verification_scope": "verified_by_exporter_from_source_run_not_committed",
        },
    }
    write_json_atomic(output / "evidence-metadata.json", metadata)
    print(f"Evidence exported to {output}")
    print(f"  source_commit: {args.source_commit}")
    print(f"  payload_hash:  {manifest['payload_hash']}")
    print(f"  semantic_run:  {inspection['semantic_run_hash']}")
    print(f"  full_inspection (local): {full_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
