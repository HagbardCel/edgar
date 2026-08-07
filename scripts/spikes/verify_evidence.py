#!/usr/bin/env python3
"""Verify a committed spike evidence package (CI-suitable, no network).

Checks, all fatal on failure:
1. exact evidence file set (hashed files + evidence-metadata.json only)
2. all evidence files parse as JSON
3. every digest in evidence_file_sha256 verifies (metadata itself excluded)
4. the bundle manifest passes structural validation
5. uri-bindings pointer validates against binding bytes (shared validators)
6. expectation files match deterministic projections of manifest/inspection
7. schema-aware privacy on known identity/operational fields
8. semantic_run_hash recomputes from the compact inspection (non-circular)
9. provenance (when inside a git repository): source_commit exists, is an
   ancestor of HEAD, and every change after source_commit touches only
   allowlisted documentation/evidence paths
10. full_inspection digest is provenance-only (not CI-reproducible)

Usage:
  uv run python scripts/spikes/verify_evidence.py fixtures/manifests/0001065088-24-000036
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

from spike_lib import SAMPLES_POLICY_VERSION  # noqa: E402
from spike_lib.hashing import sha256_hex  # noqa: E402
from spike_lib.manifest import (  # noqa: E402
    validate_manifest_structure,
    validate_uri_bindings_pointer,
)
from spike_lib.semantic import build_semantic_run_identity, semantic_run_hash  # noqa: E402

# Deny-by-default: after the implementation commit, only these paths may change.
POST_IMPLEMENTATION_PATH_ALLOWLIST_PREFIXES = (
    "fixtures/manifests/",
    "docs/spikes/",
    "docs/adr/",
)

EVIDENCE_HASHED_FILES = (
    "bundle-manifest.json",
    "uri-bindings.json",
    "inspection-core.json",
    "inspection-samples.json",
    "acquisition-expectations.json",
    "parser-expectations.json",
)

# Known identity/operational fields subject to local-path / file: privacy checks.
_PRIVACY_URI_KEYS = frozenset(
    {
        "document_uri",
        "canonical_uri",
        "source_document_uri",
        "target_document_uri",
        "source_uri",
        "target_uri",
        "normalized_href",
        "normalized_reference_uri",
        "arc_document_uri",
        "entrypoint",
    }
)
_PRIVACY_LIST_KEYS = frozenset({"entry_points", "unresolved_uris"})


class VerificationFailure(Exception):
    pass


def _failures(check: str, problems: list[str]) -> list[str]:
    return [f"[{check}] {p}" for p in problems]


def _check_string_privacy(value: str, *, path: str, label: str) -> list[str]:
    problems: list[str] = []
    if value.startswith("file:"):
        problems.append(f"{label}: file: URI at {path}: {value[:80]!r}")
    elif value.startswith("/") and not value.startswith("//"):
        problems.append(f"{label}: absolute local path at {path}: {value[:80]!r}")
    return problems


def check_privacy(doc: Any, *, path: str = "root", label: str = "doc") -> list[str]:
    """Schema-aware privacy: inspect known identity/operational fields only.

    Filed resource text (labels/references) is never subject to local-path
    heuristics. Prohibited ``user_agent`` keys are still rejected wherever found.
    """
    problems: list[str] = []
    if isinstance(doc, dict):
        for key, value in doc.items():
            key_l = str(key).lower()
            child_path = f"{path}.{key}"
            if "user_agent" in key_l:
                problems.append(f"{label}: prohibited key {key!r} at {path}")
            if key in _PRIVACY_URI_KEYS:
                if isinstance(value, str):
                    problems.extend(_check_string_privacy(value, path=child_path, label=label))
                elif isinstance(value, dict) and "document_uri" in value:
                    problems.extend(
                        _check_string_privacy(
                            value["document_uri"],
                            path=f"{child_path}.document_uri",
                            label=label,
                        )
                    )
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        if isinstance(item, str):
                            problems.extend(
                                _check_string_privacy(
                                    item, path=f"{child_path}[{index}]", label=label
                                )
                            )
            elif key in _PRIVACY_LIST_KEYS and isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, str):
                        problems.extend(
                            _check_string_privacy(item, path=f"{child_path}[{index}]", label=label)
                        )
            elif (key == "engine_config" and isinstance(value, dict)) or isinstance(
                value, (dict, list)
            ):
                problems.extend(check_privacy(value, path=child_path, label=label))
    elif isinstance(doc, list):
        for index, value in enumerate(doc):
            problems.extend(check_privacy(value, path=f"{path}[{index}]", label=label))
    return problems


def _git(repo_root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip()


def verify(evidence_dir: Path) -> list[str]:
    problems: list[str] = []

    json_files = sorted(p.name for p in evidence_dir.glob("*.json") if p.is_file())
    expected_files = set(EVIDENCE_HASHED_FILES) | {"evidence-metadata.json"}
    if set(json_files) != expected_files:
        problems.extend(
            _failures(
                "presence",
                [
                    f"evidence file set mismatch: found={sorted(json_files)} "
                    f"expected={sorted(expected_files)}"
                ],
            )
        )
        return problems

    docs: dict[str, Any] = {}
    raw: dict[str, bytes] = {}
    for name in sorted(expected_files):
        path = evidence_dir / name
        raw[name] = path.read_bytes()
        try:
            docs[name] = json.loads(raw[name].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.extend(_failures("json", [f"{name} does not parse as JSON: {exc}"]))
    if problems:
        return problems

    metadata = docs["evidence-metadata.json"]
    file_hashes = metadata.get("evidence_file_sha256") or {}
    if set(file_hashes) != set(EVIDENCE_HASHED_FILES):
        problems.extend(
            _failures(
                "digests",
                [
                    "evidence_file_sha256 keys mismatch: "
                    f"got={sorted(file_hashes)} expected={sorted(EVIDENCE_HASHED_FILES)}"
                ],
            )
        )
    for name, expected in file_hashes.items():
        actual = sha256_hex(raw[name])
        if actual != expected:
            problems.extend(
                _failures(
                    "digests",
                    [f"{name} digest mismatch: declared={expected} actual={actual}"],
                )
            )
    if "evidence-metadata.json" in file_hashes:
        problems.extend(
            _failures("digests", ["evidence-metadata.json must not be in evidence_file_sha256"])
        )

    full = metadata.get("full_inspection") or {}
    if not full.get("sha256"):
        problems.extend(_failures("digests", ["missing full_inspection.sha256 provenance"]))
    if full.get("verification_scope") != "verified_by_exporter_from_source_run_not_committed":
        problems.extend(
            _failures(
                "digests",
                ["full_inspection.verification_scope must mark non-CI provenance"],
            )
        )
    if metadata.get("samples_policy_version") != SAMPLES_POLICY_VERSION:
        problems.extend(
            _failures(
                "samples",
                [f"samples_policy_version mismatch: {metadata.get('samples_policy_version')!r}"],
            )
        )
    samples = docs["inspection-samples.json"]
    if samples.get("samples_policy_version") != SAMPLES_POLICY_VERSION:
        problems.extend(
            _failures(
                "samples",
                ["inspection-samples.json samples_policy_version mismatch"],
            )
        )

    manifest = docs["bundle-manifest.json"]
    bindings_bytes = raw["uri-bindings.json"]
    inspection = docs["inspection-core.json"]

    problems.extend(_failures("manifest", validate_manifest_structure(manifest)))
    problems.extend(
        _failures("uri-bindings", validate_uri_bindings_pointer(manifest, bindings_bytes))
    )

    expected_acq = {
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
    if docs["acquisition-expectations.json"] != expected_acq:
        problems.extend(
            _failures("expectations", ["acquisition-expectations.json drifts from bundle manifest"])
        )

    online = inspection["online"]
    offline = inspection["offline"]
    expected_parser = {
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
    if docs["parser-expectations.json"] != expected_parser:
        problems.extend(
            _failures("expectations", ["parser-expectations.json drifts from inspection core"])
        )

    for name in ("bundle-manifest.json", "uri-bindings.json", "inspection-core.json"):
        problems.extend(_failures("privacy", check_privacy(docs[name], path=name, label=name)))

    try:
        identity = build_semantic_run_identity(
            cik=inspection["cik"],
            accession=inspection["accession"],
            payload_hash=inspection["payload_hash"],
            closure_hash=inspection["closure_hash"],
            engine=inspection["engine"],
            online_snapshot=online,
            offline_snapshot=offline,
            strict_comparison=inspection["compare"],
            criteria=inspection["success_criteria"],
        )
        recomputed = semantic_run_hash(identity)
        if recomputed != inspection["semantic_run_hash"]:
            problems.extend(
                _failures(
                    "semantic-hash",
                    [
                        "semantic_run_hash does not recompute: "
                        f"declared={inspection['semantic_run_hash']} computed={recomputed}"
                    ],
                )
            )
    except (KeyError, TypeError) as exc:
        problems.extend(_failures("semantic-hash", [f"cannot rebuild semantic identity: {exc}"]))

    source_commit = metadata.get("source_commit")
    rc, toplevel = _git(evidence_dir, "rev-parse", "--show-toplevel")
    if source_commit and rc == 0:
        repo_root = Path(toplevel)
        rc, _ = _git(repo_root, "cat-file", "-e", f"{source_commit}^{{commit}}")
        if rc != 0:
            problems.extend(_failures("provenance", [f"source_commit {source_commit} not found"]))
        else:
            rc, _ = _git(repo_root, "merge-base", "--is-ancestor", source_commit, "HEAD")
            if rc != 0:
                problems.extend(
                    _failures(
                        "provenance",
                        [f"source_commit {source_commit} is not an ancestor of HEAD"],
                    )
                )
            rc, names = _git(repo_root, "diff", "--name-only", f"{source_commit}..HEAD")
            if rc == 0:
                disallowed = [
                    name
                    for name in names.splitlines()
                    if name and not name.startswith(POST_IMPLEMENTATION_PATH_ALLOWLIST_PREFIXES)
                ]
                if disallowed:
                    problems.extend(
                        _failures(
                            "provenance",
                            [
                                "post-implementation changes outside allowlist: "
                                + ", ".join(sorted(disallowed))
                            ],
                        )
                    )
    elif source_commit:
        problems.extend(
            _failures("provenance", ["not inside a git repository; provenance skipped"])
        )

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_dir")
    args = parser.parse_args(argv)

    problems = verify(Path(args.evidence_dir).resolve())
    if problems:
        print("Evidence verification FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"Evidence verification passed: {args.evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
