"""Synthetic extraction receipts for low-level persistence tests (M1A-1)."""

from __future__ import annotations

from edgar.db.source_persist import PersistableFilingExtraction, PersistableReport
from edgar.domain.bundle import FilingBundle
from edgar.provenance import ImplementationIdentity
from edgar.xbrl.config import build_semantic_config
from edgar.xbrl.extraction_receipt import (
    RECEIPT_VERSION,
    BundleRef,
    ExtractionReceipt,
    semantic_config_canonical_digest,
)
from edgar.xbrl.source_records import (
    SOURCE_RECORDS_SCHEMA_VERSION,
    FilingExtraction,
    ReportExtraction,
)
from edgar.xbrl.worker import WORKER_PROTOCOL_VERSION


def minimal_test_receipt(
    report: ReportExtraction,
    *,
    bundle: FilingBundle,
    descriptor_relative_path: str = (
        "bundles/0001065088/0001065088-24-000036/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bundle.json"
    ),
    descriptor_sha256: str | None = None,
) -> ExtractionReceipt:
    """Build a structurally valid receipt matching the report's versions."""
    digest = descriptor_sha256 or ("a" * 64)
    bundle_ref = BundleRef(
        descriptor_relative_path=descriptor_relative_path,
        descriptor_sha256=digest,
        manifest=bundle.to_dict(),
    )
    config = build_semantic_config().to_dict()
    return ExtractionReceipt(
        receipt_version=RECEIPT_VERSION,
        bundle_ref=bundle_ref,
        report_input=dict(report.report_input),
        semantic_config=config,
        semantic_config_sha256=semantic_config_canonical_digest(config),
        extractor_version=report.extractor_version,
        source_records_schema_version=SOURCE_RECORDS_SCHEMA_VERSION,
        worker_protocol_version=WORKER_PROTOCOL_VERSION,
        arelle_version=report.arelle_version,
        implementation=ImplementationIdentity(
            revision="test-revision",
            tree_state="clean",
            dirty_tree_digest=None,
        ),
        dependency_lock_sha256="b" * 64,
    )


def wrap_filing_extraction(
    extraction: FilingExtraction,
    *,
    bundle: FilingBundle,
) -> PersistableFilingExtraction:
    """Attach synthetic receipts so ``persist_extraction`` accepts the extraction."""
    return PersistableFilingExtraction(
        reports=tuple(
            PersistableReport(
                report=report,
                extraction_receipt=minimal_test_receipt(report, bundle=bundle),
            )
            for report in extraction.reports
        ),
        document_blocks=extraction.document_blocks,
        filing_sections=extraction.filing_sections,
        issues=extraction.issues,
    )
