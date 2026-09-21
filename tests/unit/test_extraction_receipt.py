"""Unit tests for M1A-1 extraction receipt validation."""

from __future__ import annotations

import hashlib
import uuid
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.domain.report_key import report_key
from edgar.ingestion.payload import compute_payload_hash
from edgar.provenance import (
    ImplementationIdentity,
    gather_implementation_identity,
    resolve_edgar_repo_root,
)
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from edgar.xbrl.config import SemanticConfig, build_semantic_config
from edgar.xbrl.extraction_receipt import (
    BundleRef,
    ExtractionReceipt,
    PersistedReportRow,
    ProvenanceEvidence,
    ReceiptValidationError,
    build_extraction_receipt,
    decode_extraction_receipt,
    filing_identity_semantically_equal,
    load_bundle_ref,
    receipt_verified,
    validate_persisted_receipt_semantics,
    validate_receipt_binding,
    verify_extraction_config_chain,
    verify_provenance_evidence,
)
from edgar.xbrl.worker import WORKER_PROTOCOL_VERSION, WorkerJob


def _sample_filing() -> FilingIdentity:
    return FilingIdentity(
        cik="0000320193",
        accession="0000320193-24-000123",
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        accepted_at=datetime(2024, 11, 1, 12, 0, tzinfo=UTC),
        report_period_end=date(2024, 9, 28),
        primary_document="aapl-20240928.htm",
    )


def _sample_bundle(*, store: ObjectStore | None = None) -> FilingBundle:
    filing = _sample_filing()
    path = "accession/instance.xml"
    payload = b"<xbrl>test</xbrl>"
    if store is None:
        digest = "a" * 64
        byte_size = len(payload)
    else:
        obj = store.put_bytes(payload)
        digest = obj.sha256
        byte_size = obj.byte_size
    artifacts = (
        BundleArtifact(
            logical_path=path,
            content=ContentObject(sha256=digest, byte_size=byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
    )
    uri = "https://example.test/instance.xml"
    return FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(InstanceReportInput(document_uris=(uri,)),),
        uri_bindings=(
            UriBinding(
                document_uri=uri,
                artifact_path=path,
                content_sha256=digest,
                replay_aliases=(),
            ),
        ),
    )


def _sample_receipt() -> ExtractionReceipt:
    bundle = _sample_bundle()
    report_input = bundle.report_inputs[0].to_dict()
    bundle_ref = BundleRef(
        descriptor_relative_path=(
            "bundles/0000320193/0000320193-24-000123/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bundle.json"
        ),
        descriptor_sha256="b" * 64,
        manifest=bundle.to_dict(),
    )
    return build_extraction_receipt(
        bundle_ref=bundle_ref,
        report_input=report_input,
        semantic_config=build_semantic_config().to_dict(),
        arelle_version="test-arelle",
        worker_protocol_version=WORKER_PROTOCOL_VERSION,
        implementation=ImplementationIdentity(revision="abc", tree_state="clean"),
        dependency_lock_sha256="c" * 64,
    )


def test_verify_extraction_config_chain_requires_equality() -> None:
    cfg = build_semantic_config().to_dict()
    verify_extraction_config_chain(
        job_semantic_config=cfg,
        worker_effective_semantic_config=cfg,
        receipt_semantic_config=cfg,
        worker_protocol_version=WORKER_PROTOCOL_VERSION,
        expected_worker_protocol_version=WORKER_PROTOCOL_VERSION,
        receipt_worker_protocol_version=WORKER_PROTOCOL_VERSION,
    )


def test_verify_extraction_config_chain_rejects_protocol_mismatch() -> None:
    cfg = build_semantic_config().to_dict()
    with pytest.raises(ReceiptValidationError, match="protocol_version"):
        verify_extraction_config_chain(
            job_semantic_config=cfg,
            worker_effective_semantic_config=cfg,
            receipt_semantic_config=cfg,
            worker_protocol_version="wrong",
            expected_worker_protocol_version=WORKER_PROTOCOL_VERSION,
            receipt_worker_protocol_version=WORKER_PROTOCOL_VERSION,
        )


def test_validate_receipt_binding_filing_identity_full_metadata() -> None:
    receipt = _sample_receipt()
    filing = _sample_filing()
    row = PersistedReportRow(
        report_input=receipt.report_input,
        report_key=report_key(receipt.report_input),
        extractor_version=receipt.extractor_version,
        arelle_version=receipt.arelle_version,
        filing=filing,
    )
    validate_receipt_binding(row, receipt)
    validate_persisted_receipt_semantics(receipt)


def test_filing_identity_compares_accepted_at_by_instant() -> None:
    left = _sample_filing()
    right = FilingIdentity(
        cik=left.cik,
        accession=left.accession,
        form_type=left.form_type,
        filing_date=left.filing_date,
        accepted_at=datetime.fromisoformat("2024-11-01T07:00:00-05:00"),
        report_period_end=left.report_period_end,
        primary_document=left.primary_document,
    )
    assert filing_identity_semantically_equal(left, right)


def test_semantic_config_from_dict_round_trip() -> None:
    cfg = build_semantic_config()
    assert SemanticConfig.from_dict(cfg.to_dict()).to_dict() == cfg.to_dict()


def test_decode_historical_receipt_after_extractor_schema_bump() -> None:
    from edgar.xbrl.source_records import EXTRACTOR_VERSION, SOURCE_RECORDS_SCHEMA_VERSION

    receipt = _sample_receipt()
    payload = receipt.to_dict()
    payload["extractor_version"] = "source-extract-v3"
    payload["source_records_schema_version"] = 2
    payload["worker_protocol_version"] = WORKER_PROTOCOL_VERSION
    decoded = decode_extraction_receipt(payload)
    assert decoded.extractor_version == "source-extract-v3"
    assert decoded.source_records_schema_version == 2
    assert decoded.worker_protocol_version == WORKER_PROTOCOL_VERSION
    assert EXTRACTOR_VERSION != "source-extract-v3"
    assert SOURCE_RECORDS_SCHEMA_VERSION != 2
    assert WORKER_PROTOCOL_VERSION == "arelle-worker-v2"


def test_decode_rejects_traversal_in_descriptor_relative_path() -> None:
    receipt = _sample_receipt()
    payload = receipt.to_dict()
    payload["bundle_ref"]["descriptor_relative_path"] = (
        "bundles/0000320193/../0000320193-24-000123/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bundle.json"
    )
    with pytest.raises(ReceiptValidationError, match=r"\.\."):
        decode_extraction_receipt(payload)


def test_dirty_without_digest_not_verifiable() -> None:
    receipt = _sample_receipt()
    dirty = ImplementationIdentity(
        revision="abc",
        tree_state="dirty",
        dirty_tree_digest=None,
    )
    expected = ProvenanceEvidence(implementation=dirty, dependency_lock_sha256="c" * 64)
    dirty_receipt = ExtractionReceipt(
        receipt_version=receipt.receipt_version,
        bundle_ref=receipt.bundle_ref,
        report_input=receipt.report_input,
        semantic_config=receipt.semantic_config,
        semantic_config_sha256=receipt.semantic_config_sha256,
        extractor_version=receipt.extractor_version,
        source_records_schema_version=receipt.source_records_schema_version,
        worker_protocol_version=receipt.worker_protocol_version,
        arelle_version=receipt.arelle_version,
        implementation=dirty,
        dependency_lock_sha256=receipt.dependency_lock_sha256,
    )
    with pytest.raises(ReceiptValidationError, match="unverifiable"):
        verify_provenance_evidence(dirty_receipt, expected, require_clean=False)


def test_worker_extract_job_rejects_unknown_keys() -> None:
    cfg = build_semantic_config().to_dict()
    job = {
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "mode": "offline",
        "operation": "extract",
        "report_input": {"kind": "instance", "document_uris": ["https://example.test/a.xml"]},
        "object_store_root": "/tmp",
        "uri_bindings": [],
        "semantic_config": cfg,
        "uri_objects": {},
    }
    with pytest.raises(ValueError, match="unknown"):
        WorkerJob.from_dict(job)


def test_worker_extract_job_requires_protocol_version() -> None:
    cfg = build_semantic_config().to_dict()
    job = {
        "mode": "offline",
        "operation": "extract",
        "report_input": {"kind": "instance", "document_uris": ["https://example.test/a.xml"]},
        "object_store_root": "/tmp",
        "uri_bindings": [],
        "semantic_config": cfg,
    }
    with pytest.raises(ValueError, match="missing"):
        WorkerJob.from_dict(job)


def test_worker_extract_job_rejects_non_string_object_store_root() -> None:
    cfg = build_semantic_config().to_dict()
    job = {
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "mode": "offline",
        "operation": "extract",
        "report_input": {"kind": "instance", "document_uris": ["https://example.test/a.xml"]},
        "object_store_root": Path("/tmp"),
        "uri_bindings": [],
        "semantic_config": cfg,
    }
    with pytest.raises(ValueError):
        WorkerJob.from_dict(job)


def test_load_bundle_ref_accepts_relative_var_bundles_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "var"
    data_root.mkdir()
    store = ObjectStore(data_root)
    bundle = _sample_bundle(store=store)
    published = BundleRepository(data_root, store).publish(bundle)
    monkeypatch.chdir(tmp_path)
    relative = Path("var") / published.bundle_dir.relative_to(data_root)
    captured = load_bundle_ref(data_root=data_root, bundle_dir=relative)
    assert captured.bundle.filing.accession == bundle.filing.accession
    assert captured.bundle_ref.descriptor_relative_path.endswith("/bundle.json")
    assert len(captured.bundle_ref.descriptor_sha256) == 64


def test_resolve_repo_root_rejects_unrelated_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    foreign = tmp_path / "other-checkout"
    (foreign / "src" / "edgar").mkdir(parents=True)
    (foreign / "pyproject.toml").write_text("[project]\nname='other'\n", encoding="utf-8")
    (foreign / "src" / "edgar" / "__init__.py").write_text("# foreign\n", encoding="utf-8")
    monkeypatch.setenv("EDGAR_REPO_ROOT", str(foreign))
    assert resolve_edgar_repo_root() is None
    identity = gather_implementation_identity()
    assert identity.tree_state == "unknown"
    assert identity.revision is None


def _published_receipt_verified_context(tmp_path: Path) -> dict[str, Any]:
    data_root = tmp_path
    store = ObjectStore(data_root)
    bundle = _sample_bundle(store=store)
    published = BundleRepository(data_root, store).publish(bundle)
    loaded = load_bundle_ref(data_root=data_root, bundle_dir=published.bundle_dir)
    report_input = bundle.report_inputs[0].to_dict()
    implementation = ImplementationIdentity(revision="abc", tree_state="clean")
    lock_sha = "c" * 64
    receipt = build_extraction_receipt(
        bundle_ref=loaded.bundle_ref,
        report_input=report_input,
        semantic_config=build_semantic_config().to_dict(),
        arelle_version="test-arelle",
        worker_protocol_version=WORKER_PROTOCOL_VERSION,
        implementation=implementation,
        dependency_lock_sha256=lock_sha,
    )
    payload = decode_extraction_receipt(receipt.to_dict()).to_dict()
    row = PersistedReportRow(
        report_input=report_input,
        report_key=report_key(report_input),
        extractor_version=receipt.extractor_version,
        arelle_version=receipt.arelle_version,
        filing=bundle.filing,
    )
    evidence = ProvenanceEvidence(implementation=implementation, dependency_lock_sha256=lock_sha)
    return {
        "data_root": data_root,
        "store": store,
        "payload": payload,
        "row": row,
        "evidence": evidence,
        "real_sha": loaded.bundle_ref.descriptor_sha256,
        "published_dir": published.bundle_dir,
        "bundle": bundle,
    }


@pytest.mark.parametrize(
    ("case_id", "expected"),
    [
        ("valid", True),
        ("wrong_descriptor_sha", False),
        ("missing_cas", False),
        ("noncanonical_logical_path", False),
        ("wrong_publication_directory", False),
        ("wrong_lock", False),
        ("wrong_implementation", False),
        ("dirty_require_clean", False),
    ],
)
def test_receipt_verified_matrix(tmp_path: Path, case_id: str, expected: bool) -> None:
    ctx = _published_receipt_verified_context(tmp_path)
    payload = deepcopy(ctx["payload"])
    row = ctx["row"]
    evidence = ctx["evidence"]
    require_clean = False

    if case_id == "wrong_descriptor_sha":
        payload["bundle_ref"]["descriptor_sha256"] = "0" * 64
        assert payload["bundle_ref"]["descriptor_sha256"] != ctx["real_sha"]
    elif case_id == "missing_cas":
        artifact_sha = ctx["bundle"].artifacts[0].content.sha256
        ctx["store"].path_for(artifact_sha).unlink()
    elif case_id == "noncanonical_logical_path":
        descriptor = ctx["published_dir"] / "bundle.json"
        copy_path = ctx["published_dir"] / "arbitrary-copy.json"
        copy_path.write_bytes(descriptor.read_bytes())
        payload["bundle_ref"]["descriptor_relative_path"] = copy_path.relative_to(
            ctx["data_root"]
        ).as_posix()
    elif case_id == "wrong_publication_directory":
        wrong_uuid = uuid.uuid4().hex
        wrong_dir = ctx["data_root"] / "bundles/0000000001/0000000001-24-000001" / wrong_uuid
        wrong_dir.mkdir(parents=True)
        wrong_descriptor = wrong_dir / "bundle.json"
        canonical = ctx["published_dir"] / "bundle.json"
        wrong_descriptor.write_bytes(canonical.read_bytes())
        payload["bundle_ref"]["descriptor_relative_path"] = wrong_descriptor.relative_to(
            ctx["data_root"]
        ).as_posix()
        payload["bundle_ref"]["descriptor_sha256"] = hashlib.sha256(
            wrong_descriptor.read_bytes()
        ).hexdigest()
    elif case_id == "wrong_lock":
        evidence = ProvenanceEvidence(
            implementation=ctx["evidence"].implementation,
            dependency_lock_sha256="d" * 64,
        )
    elif case_id == "wrong_implementation":
        evidence = ProvenanceEvidence(
            implementation=ImplementationIdentity(revision="other", tree_state="clean"),
            dependency_lock_sha256=ctx["evidence"].dependency_lock_sha256,
        )
    elif case_id == "dirty_require_clean":
        dirty = ImplementationIdentity(
            revision="abc",
            tree_state="dirty",
            dirty_tree_digest="e" * 64,
        )
        payload["implementation"] = {
            "revision": dirty.revision,
            "tree_state": dirty.tree_state,
            "dirty_tree_digest": dirty.dirty_tree_digest,
        }
        evidence = ProvenanceEvidence(
            implementation=dirty,
            dependency_lock_sha256=ctx["evidence"].dependency_lock_sha256,
        )
        require_clean = True

    result = receipt_verified(
        row,
        payload,
        data_root=ctx["data_root"],
        store=ctx["store"],
        expected=evidence,
        require_clean=require_clean,
    )
    assert result is expected
