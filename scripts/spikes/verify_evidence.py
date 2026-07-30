#!/usr/bin/env python3
"""Verify a committed spike evidence package (CI-suitable, no network).

Checks, all fatal on failure:
1. all evidence files parse as JSON
2. the bundle manifest passes sterile structural validation
3. sha256(uri-bindings.json) matches the manifest pointer
4. binding rules hold against the manifest (incl. entrypoint as primary binding)
5. expectation files match deterministic projections of manifest/inspection
6. privacy: no user_agent keys, no file: URIs, no absolute local paths in
   persisted identity/evidence documents
7. semantic_run_hash recomputes from the inspection fields (non-circular)
8. provenance (when inside a git repository): source_commit exists, is an
   ancestor of HEAD, and every change after source_commit touches only
   allowlisted documentation/evidence paths

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

from spike_lib.hashing import sha256_hex  # noqa: E402
from spike_lib.manifest import manifest_artifact_hashes, validate_manifest  # noqa: E402
from spike_lib.semantic import build_semantic_run_identity, semantic_run_hash  # noqa: E402
from spike_lib.uri_bindings import parse_bindings, validate_bindings  # noqa: E402

# Deny-by-default: after the implementation commit, only these paths may change.
POST_IMPLEMENTATION_PATH_ALLOWLIST_PREFIXES = (
    "fixtures/manifests/",
    "docs/spikes/",
    "docs/adr/",
)

EVIDENCE_FILES = (
    "bundle-manifest.json",
    "uri-bindings.json",
    "inspection-core.json",
    "acquisition-expectations.json",
    "parser-expectations.json",
    "evidence-metadata.json",
)


class VerificationFailure(Exception):
    pass


def _failures(check: str, problems: list[str]) -> list[str]:
    return [f"[{check}] {p}" for p in problems]


def check_privacy(doc: Any, *, path: str, label: str) -> list[str]:
    problems: list[str] = []
    if isinstance(doc, dict):
        for key, value in doc.items():
            key_l = str(key).lower()
            if "user_agent" in key_l:
                problems.append(f"{label}: prohibited key {key!r} at {path}")
            problems.extend(check_privacy(value, path=f"{path}.{key}", label=label))
    elif isinstance(doc, list):
        for index, value in enumerate(doc):
            problems.extend(check_privacy(value, path=f"{path}[{index}]", label=label))
    elif isinstance(doc, str):
        if doc.startswith("file:"):
            problems.append(f"{label}: file: URI at {path}: {doc[:80]!r}")
        elif doc.startswith("/") and not doc.startswith("//"):
            problems.append(f"{label}: absolute local path at {path}: {doc[:80]!r}")
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

    docs: dict[str, Any] = {}
    raw: dict[str, bytes] = {}
    for name in EVIDENCE_FILES:
        path = evidence_dir / name
        if not path.is_file():
            problems.extend(_failures("presence", [f"missing evidence file: {name}"]))
            continue
        raw[name] = path.read_bytes()
        try:
            docs[name] = json.loads(raw[name].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.extend(_failures("json", [f"{name} does not parse as JSON: {exc}"]))
    if problems:
        return problems

    manifest = docs["bundle-manifest.json"]
    bindings_bytes = raw["uri-bindings.json"]
    inspection = docs["inspection-core.json"]
    metadata = docs["evidence-metadata.json"]

    # 2. sterile manifest structure + payload hash recomputation
    problems.extend(_failures("manifest", validate_manifest(manifest)))

    artifact_hashes = manifest_artifact_hashes(manifest)
    entrypoint_uri = manifest.get("entrypoint", {}).get("document_uri", "")

    # 3. pointer hash consistency
    pointer = manifest.get("uri_bindings_artifact") or {}
    actual_bindings_sha = sha256_hex(bindings_bytes)
    if pointer.get("sha256") != actual_bindings_sha:
        problems.extend(
            _failures(
                "uri-bindings",
                [
                    "sha256(uri-bindings.json) does not match manifest pointer: "
                    f"pointer={pointer.get('sha256')} actual={actual_bindings_sha}"
                ],
            )
        )

    # 4. binding rules
    try:
        bindings = parse_bindings(bindings_bytes)
    except ValueError as exc:
        problems.extend(_failures("uri-bindings", [f"bindings do not parse: {exc}"]))
        bindings = []
    if bindings:
        problems.extend(
            _failures(
                "uri-bindings",
                validate_bindings(
                    bindings,
                    manifest_artifacts=artifact_hashes,
                    entrypoint_document_uri=entrypoint_uri,
                ),
            )
        )

    # 5. expectation projections
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
        "criteria_passed": {str(c["id"]): c["passed"] for c in inspection["success_criteria"]},
    }
    if docs["parser-expectations.json"] != expected_parser:
        problems.extend(
            _failures("expectations", ["parser-expectations.json drifts from inspection core"])
        )

    # 6. privacy
    for name in ("bundle-manifest.json", "uri-bindings.json", "inspection-core.json"):
        problems.extend(_failures("privacy", check_privacy(docs[name], path=name, label=name)))

    # 7. non-circular semantic hash recomputation
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

    # 8. provenance (git)
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
