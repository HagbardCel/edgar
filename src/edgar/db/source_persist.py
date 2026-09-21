"""Parent-side persistence types wrapping worker extraction output (M1A)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edgar.xbrl.extraction_receipt import ExtractionReceipt
from edgar.xbrl.source_records import (
    DocumentBlockRecord,
    ExtractionIssueRecord,
    FilingSectionRecord,
    ReportExtraction,
)


@dataclass(frozen=True)
class PersistableReport:
    report: ReportExtraction
    extraction_receipt: ExtractionReceipt
    upstream_inventory: dict[str, Any] | None = None


@dataclass(frozen=True)
class PersistableFilingExtraction:
    reports: tuple[PersistableReport, ...]
    document_blocks: tuple[DocumentBlockRecord, ...] = ()
    filing_sections: tuple[FilingSectionRecord, ...] = ()
    issues: tuple[ExtractionIssueRecord, ...] = ()

    def __post_init__(self) -> None:
        if not self.reports:
            raise ValueError("PersistableFilingExtraction requires at least one report")


__all__ = [
    "PersistableFilingExtraction",
    "PersistableReport",
]
