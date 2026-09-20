"""Parent-side persistence types wrapping worker extraction output (M1A)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edgar.xbrl.extraction_receipt import ExtractionReceipt
from edgar.xbrl.source_records import (
    DocumentBlockRecord,
    ExtractionIssueRecord,
    FilingExtraction,
    FilingSectionRecord,
    ReportExtraction,
)


@dataclass(frozen=True)
class PersistableReport:
    report: ReportExtraction
    extraction_receipt: ExtractionReceipt | None = None
    upstream_inventory: dict[str, Any] | None = None


@dataclass(frozen=True)
class PersistableFilingExtraction:
    reports: tuple[PersistableReport, ...]
    document_blocks: tuple[DocumentBlockRecord, ...] = ()
    filing_sections: tuple[FilingSectionRecord, ...] = ()
    issues: tuple[ExtractionIssueRecord, ...] = ()

    @classmethod
    def from_filing_extraction(
        cls,
        extraction: FilingExtraction,
        *,
        receipts: tuple[ExtractionReceipt | None, ...] | None = None,
    ) -> PersistableFilingExtraction:
        if receipts is not None and len(receipts) != len(extraction.reports):
            raise ValueError("receipts length must match reports length")
        reports: list[PersistableReport] = []
        for index, report in enumerate(extraction.reports):
            receipt = receipts[index] if receipts is not None else None
            reports.append(
                PersistableReport(
                    report=report,
                    extraction_receipt=receipt,
                    upstream_inventory=None,
                )
            )
        return cls(
            reports=tuple(reports),
            document_blocks=extraction.document_blocks,
            filing_sections=extraction.filing_sections,
            issues=extraction.issues,
        )


__all__ = [
    "PersistableFilingExtraction",
    "PersistableReport",
]
