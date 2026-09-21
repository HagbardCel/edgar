"""Unit tests for M1A-1 extraction receipt validation."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

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
        accepted_at=datetime(2024, 11, 1, 12, 0, tzinfo=UTC),
        report_period_end=left.report_period_end,
        primary_document=left.primary_document,
    )
    assert filing_identity_semantically_equal(left, right)


def test_semantic_config_from_dict_round_trip() -> None:
    cfg = build_semantic_config()
    assert SemanticConfig.from_dict(cfg.to_dict()).to_dict() == cfg.to_dict()


def test_decode_extraction_receipt_round_trip() -> None:
    receipt = _sample_receipt()
    decoded = decode_extraction_receipt(receipt.to_dict())
    assert decoded.to_dict() == receipt.to_dict()


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
