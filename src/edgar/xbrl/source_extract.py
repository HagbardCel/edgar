"""Offline source-layer XBRL + document extraction for Phase 2B.

Reuses the isolated Arelle worker via
:func:`edgar.xbrl.semantic.run_offline_extract`, and fills document
blocks/sections from ``edgar.parsing`` heuristics.
"""

from __future__ import annotations

import sys

from edgar.domain.bundle import FilingBundle, XbrlReportInput
from edgar.storage.objects import ObjectStore
from edgar.xbrl.closure import DEFAULT_WORKER_TIMEOUT_SECONDS
from edgar.xbrl.semantic import run_offline_extract
from edgar.xbrl.source_documents import extract_documents_for_filing
from edgar.xbrl.source_records import FilingExtraction, ReportExtraction


def extract_report(
    bundle: FilingBundle,
    store: ObjectStore,
    report_input: XbrlReportInput,
    *,
    python_executable: str = sys.executable,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> ReportExtraction:
    """Extract one report input into a source ``ReportExtraction``."""
    result = run_offline_extract(
        bundle,
        store,
        report_input=report_input,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
    )
    report = result.report
    if report.arelle_item_fact_count != len(report.facts):
        raise AssertionError(
            "arelle_item_fact_count must equal len(facts): "
            f"{report.arelle_item_fact_count} != {len(report.facts)}"
        )
    return report


def extract_filing(
    bundle: FilingBundle,
    store: ObjectStore,
    *,
    python_executable: str = sys.executable,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> FilingExtraction:
    """Extract every report input plus eligible HTML documents.

    Document parse happens outside any DB transaction. Fatal document parse
    errors propagate so callers can skip snapshot replacement. A fatal failure
    of any report aborts the entire filing extraction.
    """
    reports: list[ReportExtraction] = []
    for report_input in bundle.report_inputs:
        reports.append(
            extract_report(
                bundle,
                store,
                report_input,
                python_executable=python_executable,
                timeout_seconds=timeout_seconds,
            )
        )
    blocks, sections, doc_issues = extract_documents_for_filing(bundle, store)
    return FilingExtraction(
        reports=tuple(reports),
        document_blocks=blocks,
        filing_sections=sections,
        issues=doc_issues,
    )
