"""Unit tests for evidence-package privacy and verification (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib import SAMPLES_POLICY_VERSION  # noqa: E402
from spike_lib.hashing import sha256_hex  # noqa: E402
from spike_lib.manifest import build_sterile_manifest  # noqa: E402
from spike_lib.semantic import (  # noqa: E402
    build_semantic_run_identity,
    semantic_run_hash,
    strict_comparison_projection,
)
from spike_lib.uri_bindings import (  # noqa: E402
    URI_BINDINGS_LOGICAL_PATH,
    UriBinding,
    serialize_bindings,
)
from verify_evidence import check_privacy, verify  # noqa: E402

ENTRYPOINT_URI = "https://www.sec.gov/Archives/edgar/data/1/x/a.htm"


def _side() -> dict[str, object]:
    return {
        "concept_count": 1,
        "context_count": 1,
        "unit_count": 1,
        "fact_count": 1,
        "relationship_counts": {"presentation": 0},
        "resource_relationship_counts": {"concept_label": 0},
        "concept_relationship_occurrence_hash": "a" * 64,
        "resource_relationship_occurrence_hash": "b" * 64,
        "documents": [],
        "edges": [],
        "synthetic_documents": [],
        "synthetic_document_set_hash": "c" * 64,
        "synthetic_document_count": 0,
        "synthetic_edges": [],
        "synthetic_edge_set_hash": "d" * 64,
        "synthetic_edge_count": 0,
        "entry_points": [ENTRYPOINT_URI],
        "unresolved_uris": [],
        "unsupported_inventory": {},
        "extraction": {"extraction_complete": True},
        "document_edge_extraction": {
            "extraction_complete": True,
            "unstable_reference_occurrence_count": 0,
            "unresolved_reference_attribute_count": 0,
            "failure_records": [],
        },
        "error_summary": {
            "policy_passed": True,
            "arelle_error_policy_version": "arelle-error-policy-v2",
            "canonical_error_records": [],
            "recognized_nonblocking_error_count": 0,
            "unrecognized_error_count": 0,
        },
        "fact_locator_stats": {},
    }


def _package(evidence_dir: Path) -> dict[str, object]:
    bindings = [UriBinding(ENTRYPOINT_URI, "accession/a.htm", "aa" * 32)]
    bindings_bytes = serialize_bindings(bindings)
    bindings_sha = sha256_hex(bindings_bytes)

    artifacts = [
        SimpleNamespace(
            logical_path="accession/a.htm",
            sha256="aa" * 32,
            byte_size=100,
            source_url=ENTRYPOINT_URI,
            source_class="sec_edgar_accession",
            artifact_role="primary",
            sec_sequence=None,
            sec_document_type=None,
            sec_description=None,
            required=True,
            in_payload=True,
        ),
        SimpleNamespace(
            logical_path=URI_BINDINGS_LOGICAL_PATH,
            sha256=bindings_sha,
            byte_size=len(bindings_bytes),
            source_url=None,
            source_class="generated",
            artifact_role="uri_bindings",
            sec_sequence=None,
            sec_document_type=None,
            sec_description=None,
            required=True,
            in_payload=True,
        ),
    ]
    draft = SimpleNamespace(
        cik="0001065088",
        accession="0001065088-24-000036",
        artifacts=artifacts,
        artifact_by_path=lambda path: next((a for a in artifacts if a.logical_path == path), None),
    )
    manifest = build_sterile_manifest(
        draft, entrypoint_document_uri=ENTRYPOINT_URI, bindings_count=1
    )

    compare = {
        "strict_diffs": [],
        "allowed_diffs": [],
        "unexplained_diffs": [],
        "strict_ok": True,
        "criterion_10_ok": True,
    }
    criteria = [{"id": i, "name": f"c{i}", "passed": True, "detail": {}} for i in range(1, 11)]
    identity = build_semantic_run_identity(
        cik=manifest["cik"],
        accession=manifest["accession"],
        payload_hash=manifest["payload_hash"],
        closure_hash="2" * 64,
        engine={"name": "arelle", "version": "9.9.9", "config": {"work_offline": True}},
        online_snapshot=_side(),
        offline_snapshot=_side(),
        strict_comparison=strict_comparison_projection(compare),
        criteria=criteria,
    )
    sem_hash = semantic_run_hash(identity)

    inspection = {
        "spike": "arelle_offline_closure",
        "schema_versions": {"semantic_run_schema_version": "semantic-run-v2"},
        "cik": manifest["cik"],
        "accession": manifest["accession"],
        "payload_hash": manifest["payload_hash"],
        "closure_hash": "2" * 64,
        "semantic_run_hash": sem_hash,
        "engine": {"name": "arelle", "version": "9.9.9", "config": {"work_offline": True}},
        "online": _side(),
        "offline": _side(),
        "compare": strict_comparison_projection(compare),
        "success_criteria": criteria,
        "quality_issues": [],
    }
    samples = {
        "samples_policy_version": SAMPLES_POLICY_VERSION,
        "concept_samples": [],
        "resource_samples": [],
    }

    acquisition_expectations = {
        "manifest_schema_version": manifest["manifest_schema_version"],
        "acquisition_policy_version": manifest["acquisition_policy_version"],
        "payload_hash_schema_version": manifest["payload_hash_schema_version"],
        "cik": manifest["cik"],
        "accession": manifest["accession"],
        "payload_hash": manifest["payload_hash"],
        "artifact_count": len(manifest["artifacts"]),
        "payload_artifact_count": 2,
        "entrypoint": manifest["entrypoint"],
    }
    parser_expectations = {
        "semantic_run_schema_version": "semantic-run-v2",
        "payload_hash": manifest["payload_hash"],
        "closure_hash": "2" * 64,
        "semantic_run_hash": sem_hash,
        "concept_count": 1,
        "fact_count": 1,
        "context_count": 1,
        "unit_count": 1,
        "concept_relationship_occurrence_hash": "a" * 64,
        "resource_relationship_occurrence_hash": "b" * 64,
        "offline_concept_relationship_occurrence_hash": "a" * 64,
        "offline_resource_relationship_occurrence_hash": "b" * 64,
        "unsupported_inventory": {},
        "extraction": {"extraction_complete": True},
        "document_edge_extraction": _side()["document_edge_extraction"],
        "criteria_passed": {str(i): True for i in range(1, 11)},
    }

    evidence_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "bundle-manifest.json": json.dumps(manifest).encode("utf-8"),
        "uri-bindings.json": bindings_bytes,
        "inspection-core.json": json.dumps(inspection).encode("utf-8"),
        "inspection-samples.json": json.dumps(samples).encode("utf-8"),
        "acquisition-expectations.json": json.dumps(acquisition_expectations).encode("utf-8"),
        "parser-expectations.json": json.dumps(parser_expectations).encode("utf-8"),
    }
    for name, data in files.items():
        (evidence_dir / name).write_bytes(data)
    metadata = {
        "evidence_schema_version": "evidence-v2",
        "exporter_version": "evidence-export-v2",
        "samples_policy_version": SAMPLES_POLICY_VERSION,
        "source_commit": None,
        "cik": manifest["cik"],
        "accession": manifest["accession"],
        "payload_hash": manifest["payload_hash"],
        "semantic_run_hash": sem_hash,
        "evidence_file_sha256": {name: sha256_hex(data) for name, data in files.items()},
        "full_inspection": {
            "sha256": "f" * 64,
            "verification_scope": "verified_by_exporter_from_source_run_not_committed",
        },
    }
    (evidence_dir / "evidence-metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return {"manifest": manifest, "inspection": inspection, "sem_hash": sem_hash}


def test_valid_package_verifies(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    _package(evidence_dir)
    assert verify(evidence_dir) == []


def test_privacy_detects_local_paths_and_user_agent(tmp_path: Path) -> None:
    doc = {"entry_points": ["/Users/fabian/Projects/edgar/var/a.htm"]}
    problems = check_privacy(doc, path="root", label="test")
    assert any("absolute local path" in p for p in problems)

    doc2 = {"documents": [{"canonical_uri": "file:///tmp/a.htm"}]}
    problems = check_privacy(doc2, path="root", label="test")
    assert any("file: URI" in p for p in problems)

    doc3 = {"engine_config": {"user_agent": "someone@example.com"}}
    problems = check_privacy(doc3, path="root", label="test")
    assert any("user_agent" in p for p in problems)

    # Filed label text that looks like a path must NOT trigger privacy.
    filed = {"resource_content": {"text": "/looks/like/a/path but is filed text"}}
    assert check_privacy(filed, path="root", label="test") == []

    clean = {"documents": [{"canonical_uri": "https://www.sec.gov/a.htm"}]}
    assert check_privacy(clean, path="root", label="test") == []


def test_tampered_bindings_fail_verification(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    _package(evidence_dir)
    path = evidence_dir / "uri-bindings.json"
    path.write_bytes(path.read_bytes() + b" ")
    problems = verify(evidence_dir)
    assert any("digest" in p or "uri-bindings" in p for p in problems)


def test_tampered_manifest_payload_fails(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    pkg = _package(evidence_dir)
    manifest = pkg["manifest"]
    assert isinstance(manifest, dict)
    manifest["payload_hash"] = "00" * 32
    (evidence_dir / "bundle-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    # Update digest map so presence/digest checks don't short-circuit first.
    metadata = json.loads((evidence_dir / "evidence-metadata.json").read_text(encoding="utf-8"))
    metadata["evidence_file_sha256"]["bundle-manifest.json"] = sha256_hex(
        (evidence_dir / "bundle-manifest.json").read_bytes()
    )
    (evidence_dir / "evidence-metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    problems = verify(evidence_dir)
    assert any("payload_hash" in p for p in problems)
