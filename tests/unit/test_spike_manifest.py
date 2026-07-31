"""Unit tests for payload-v1, sterile manifest, and staged promotion (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib import (  # noqa: E402
    ACQUISITION_POLICY_VERSION,
)
from spike_lib.manifest import (  # noqa: E402
    build_sterile_manifest,
    compute_manifest_payload_hash,
    discard_candidate,
    manifest_artifact_hashes,
    promote_candidate,
    promotion_identity,
    stage_candidate,
    validate_manifest,
)
from spike_lib.uri_bindings import URI_BINDINGS_LOGICAL_PATH  # noqa: E402

ENTRYPOINT_URI = "https://www.sec.gov/Archives/edgar/data/1/x/a.htm"


def _artifact(
    logical_path: str,
    sha: str,
    size: int = 1,
    *,
    in_payload: bool = True,
    source_class: str = "sec_edgar_accession",
    artifact_role: str = "primary",
) -> SimpleNamespace:
    return SimpleNamespace(
        logical_path=logical_path,
        sha256=sha,
        byte_size=size,
        source_url="https://www.sec.gov/x",
        source_class=source_class,
        artifact_role=artifact_role,
        sec_sequence=None,
        sec_document_type=None,
        sec_description=None,
        required=True,
        in_payload=in_payload,
    )


def _draft() -> SimpleNamespace:
    artifacts = [
        _artifact("accession/a.htm", "aa" * 32, 100),
        _artifact("accession/a.xsd", "bb" * 32, 200),
        _artifact(
            "metadata/discovery.json",
            "cc" * 32,
            50,
            source_class="generated",
            artifact_role="metadata",
        ),
        _artifact(
            URI_BINDINGS_LOGICAL_PATH,
            "dd" * 32,
            10,
            source_class="generated",
            artifact_role="uri_bindings",
        ),
    ]
    return SimpleNamespace(
        cik="0001065088",
        accession="0001065088-24-000036",
        artifacts=artifacts,
        artifact_by_path=lambda path: next((a for a in artifacts if a.logical_path == path), None),
    )


def test_payload_hash_explicit_and_stable() -> None:
    draft = _draft()
    manifest = build_sterile_manifest(draft, entrypoint_document_uri=ENTRYPOINT_URI)
    declared = manifest["payload_hash"]
    assert declared == compute_manifest_payload_hash(manifest)
    # Round-trip via JSON does not change the payload hash.
    roundtripped = json.loads(json.dumps(manifest))
    assert compute_manifest_payload_hash(roundtripped) == declared


def test_manifest_never_participates_in_payload() -> None:
    draft = _draft()
    draft.artifacts.append(_artifact("manifest.json", "ee" * 32))
    with pytest.raises(ValueError, match="manifest.json"):
        build_sterile_manifest(draft, entrypoint_document_uri=ENTRYPOINT_URI)


def test_uri_bindings_participate_exactly_once() -> None:
    draft = _draft()
    draft.artifacts.append(
        _artifact(
            URI_BINDINGS_LOGICAL_PATH,
            "ff" * 32,
            20,
            source_class="generated",
            artifact_role="uri_bindings",
        )
    )
    with pytest.raises(ValueError, match="exactly once"):
        build_sterile_manifest(draft, entrypoint_document_uri=ENTRYPOINT_URI)


def test_sterile_manifest_has_no_volatile_fields() -> None:
    draft = _draft()
    manifest = build_sterile_manifest(draft, entrypoint_document_uri=ENTRYPOINT_URI)
    for key in (
        "generated_at",
        "replay_status",
        "quality_issues",
        "discovery",
        "issuer_provenance",
        "sgml_reconciliation",
        "sgml_documents",
        "closure_hash",
        "catalog_sha256",
        "relationship_set_hash",
        "run_id",
    ):
        assert key not in manifest
    for artifact in manifest["artifacts"]:
        assert "notes" not in artifact
        assert "content_type" not in artifact
        assert "final_url" not in artifact
    assert validate_manifest(manifest) == []


def test_validate_manifest_detects_payload_mismatch() -> None:
    draft = _draft()
    manifest = build_sterile_manifest(draft, entrypoint_document_uri=ENTRYPOINT_URI)
    manifest["payload_hash"] = "00" * 32
    errors = validate_manifest(manifest)
    assert any("payload_hash mismatch" in e for e in errors)


def test_validate_manifest_rejects_volatile_leak() -> None:
    draft = _draft()
    manifest = build_sterile_manifest(draft, entrypoint_document_uri=ENTRYPOINT_URI)
    manifest["generated_at"] = "2026-01-01T00:00:00Z"
    errors = validate_manifest(manifest)
    assert any("volatile" in e for e in errors)


def test_validate_manifest_pointer_consistency() -> None:
    draft = _draft()
    manifest = build_sterile_manifest(draft, entrypoint_document_uri=ENTRYPOINT_URI)
    manifest["uri_bindings_artifact"]["sha256"] = "11" * 32
    errors = validate_manifest(manifest)
    assert any("pointer hash" in e for e in errors)


def _stage(accession_root: Path) -> tuple[Path, dict[str, object]]:
    draft = _draft()
    manifest = build_sterile_manifest(draft, entrypoint_document_uri=ENTRYPOINT_URI)
    staging = stage_candidate(accession_root, manifest)
    return staging, manifest


def test_stage_never_final_path(tmp_path: Path) -> None:
    staging, manifest = _stage(tmp_path)
    assert ".staging" in str(staging)
    final = tmp_path / "bundles" / ACQUISITION_POLICY_VERSION / str(manifest["payload_hash"])
    assert not final.exists()
    assert (staging / "manifest.json").is_file()


def test_promote_reuses_identical_identity(tmp_path: Path) -> None:
    staging1, manifest1 = _stage(tmp_path)
    record1 = promote_candidate(tmp_path, staging1, manifest1)
    assert record1["outcome"] == "promoted"
    assert not staging1.exists()

    staging2, manifest2 = _stage(tmp_path)
    record2 = promote_candidate(tmp_path, staging2, manifest2)
    assert record2["outcome"] == "reused_existing"
    assert record1["final_bundle_path"] == record2["final_bundle_path"]
    # Manifest bytes at the final path are exactly the validated staging bytes.
    final_manifest = json.loads(
        (Path(record2["final_bundle_path"]) / "manifest.json").read_text(encoding="utf-8")
    )
    assert promotion_identity(final_manifest) == promotion_identity(manifest2)


def test_promote_conflict_is_fatal(tmp_path: Path) -> None:
    staging1, manifest1 = _stage(tmp_path)
    promote_candidate(tmp_path, staging1, manifest1)

    draft = _draft()
    manifest2 = build_sterile_manifest(draft, entrypoint_document_uri=ENTRYPOINT_URI)
    manifest2["entrypoint"] = {
        "kind": "single_document",
        "document_uri": "https://example.com/other.htm",
    }
    staging2 = stage_candidate(tmp_path, manifest2)
    # Same payload hash (final path), different promotion identity → conflict.
    with pytest.raises(RuntimeError, match="integrity conflict"):
        promote_candidate(tmp_path, staging2, manifest2)


def test_discard_moves_candidate_to_failed(tmp_path: Path) -> None:
    staging, _manifest = _stage(tmp_path)
    failed = discard_candidate(
        tmp_path, staging, reason="replay failed", failure_code="PRE_PROMOTION_GATE_FAILED"
    )
    assert ".failed" in str(failed)
    assert not staging.exists()
    assert (failed / "failure.json").is_file()
    failure = json.loads((failed / "failure.json").read_text())
    assert failure["reason"] == "replay failed"
    assert failure["failure_code"] == "PRE_PROMOTION_GATE_FAILED"


def test_duplicate_logical_path_rejected() -> None:
    draft = _draft()
    draft.artifacts.append(
        _artifact("accession/a.htm", "ff" * 32, 50),
    )
    with pytest.raises(ValueError, match="duplicate logical_path"):
        build_sterile_manifest(draft, entrypoint_document_uri=ENTRYPOINT_URI)


def test_promote_exact_bytes_required_on_reuse(tmp_path: Path) -> None:
    staging1, manifest1 = _stage(tmp_path)
    promote_candidate(tmp_path, staging1, manifest1)

    # Same promotion identity projection but different sterile artifact notes would
    # not apply; instead mutate a non-identity-affecting field that still changes
    # bytes while keeping the same payload_hash path key by forcing write.
    staging2, manifest2 = _stage(tmp_path)
    # Corrupt staged bytes while keeping JSON-parseable structure with same
    # promotion identity keys but different whitespace / key order is hard;
    # instead change an artifact description (sterile field) which changes bytes
    # without changing promotion_identity or payload entries.
    manifest2["artifacts"][0]["sec_description"] = "tampered"
    # Recompute would change payload hash only if in_payload entries change;
    # sec_description is not in payload identity, so payload_hash stays same.
    write_path = staging2 / "manifest.json"
    write_path.write_text(json.dumps(manifest2, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="different manifest bytes"):
        promote_candidate(tmp_path, staging2, manifest2)


def test_manifest_artifact_hashes(tmp_path: Path) -> None:
    draft = _draft()
    manifest = build_sterile_manifest(draft, entrypoint_document_uri=ENTRYPOINT_URI)
    hashes = manifest_artifact_hashes(manifest)
    assert hashes["accession/a.htm"] == "aa" * 32
    assert hashes[URI_BINDINGS_LOGICAL_PATH] == "dd" * 32
    pointer = manifest["uri_bindings_artifact"]
    assert pointer["schema_version"] == "uri-bindings-v2"
    assert pointer["uri_identity_version"] == "uri-identity-v1"
    assert "binding_count" in pointer
