"""Unit tests for M1A-1 extraction receipt validation."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from edgar.domain.bundle import FilingIdentity
from edgar.provenance import ImplementationIdentity
from edgar.xbrl.config import build_semantic_config
from edgar.xbrl.extraction_receipt import (
    BundleRef,
    ExtractionReceipt,
    PersistedReportRow,
    ReceiptValidationError,
    build_extraction_receipt,
    filing_identity_semantically_equal,
    validate_persisted_receipt_semantics,
    validate_receipt_binding,
    verify_extraction_config_chain,
)
from edgar.xbrl.worker import WORKER_PROTOCOL_VERSION


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


def _sample_receipt() -> ExtractionReceipt:
    filing = _sample_filing()
    report_input = {"kind": "instance", "document_uris": ["https://example.test/instance.xml"]}
    manifest = {
        "schema_version": 1,
        "acquisition_policy_version": "acq-v1",
        "filing": filing.to_dict(),
        "payload_hash": "a" * 64,
        "artifacts": [],
        "report_inputs": [report_input],
        "uri_bindings": [],
    }
    bundle_ref = BundleRef(
        descriptor_relative_path="bundles/x/y/z/bundle.json",
        descriptor_sha256="b" * 64,
        manifest=manifest,
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
        report_key="d" * 64,
        extractor_version=receipt.extractor_version,
        arelle_version=receipt.arelle_version,
        filing=filing,
    )
    # report_key must match report_input — use real key
    from edgar.domain.report_key import report_key

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
    from edgar.xbrl.config import SemanticConfig

    assert SemanticConfig.from_dict(cfg.to_dict()).to_dict() == cfg.to_dict()
