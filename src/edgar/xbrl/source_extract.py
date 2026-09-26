"""Offline source-layer XBRL + document extraction for Phase 2B.

Reuses the isolated Arelle worker via
:func:`edgar.xbrl.semantic.run_offline_extract`, and fills document
blocks/sections from ``edgar.parsing`` heuristics.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from edgar.domain.bundle import FilingBundle, XbrlReportInput
from edgar.domain.report_key import report_key as compute_report_key
from edgar.storage.objects import ObjectStore
from edgar.xbrl.closure import DEFAULT_WORKER_TIMEOUT_SECONDS
from edgar.xbrl.config import SemanticConfig, build_semantic_config
from edgar.xbrl.integrity import ReportIntegrityError, validate_report_extraction
from edgar.xbrl.report_set import assert_unique_report_keys, validate_outcome_keys
from edgar.xbrl.semantic import OfflineExtractResult, run_offline_extract
from edgar.xbrl.source_documents import extract_documents_for_filing
from edgar.xbrl.source_records import FilingExtraction, ReportExtraction
from edgar.xbrl.upstream_inventory import (
    InventoryFailure,
    UpstreamInventory,
    any_inventory_failure,
    build_inventory_outcomes,
    inventory_by_key,
)


class FilingExtractError(RuntimeError):
    """Filing-level extract aborted before a persistable snapshot exists."""


@dataclass(frozen=True)
class ReportExtractOutcome:
    report: ReportExtraction
    worker: OfflineExtractResult
    upstream_inventory: UpstreamInventory


@dataclass(frozen=True)
class FilingExtractOutcome:
    extraction: FilingExtraction
    report_outcomes: tuple[ReportExtractOutcome, ...]


def _first_inventory_failure(outcomes: tuple[InventoryFailure | object, ...]) -> InventoryFailure:
    for outcome in outcomes:
        if isinstance(outcome, InventoryFailure):
            return outcome
    raise AssertionError("expected at least one inventory failure")


def _assert_worker_fact_counts(report: ReportExtraction) -> None:
    if report.arelle_item_fact_count != len(report.facts):
        raise AssertionError(
            "arelle_item_fact_count must equal len(facts): "
            f"{report.arelle_item_fact_count} != {len(report.facts)}"
        )


def _finalize_report_outcome(
    report: ReportExtraction,
    worker: OfflineExtractResult,
    upstream: UpstreamInventory,
) -> ReportExtractOutcome:
    _assert_worker_fact_counts(report)
    if upstream.selected_target_item_count != report.arelle_item_fact_count:
        raise FilingExtractError(
            "raw vs worker fact count mismatch for "
            f"report_key={report.report_key}: "
            f"upstream.selected_target_item_count={upstream.selected_target_item_count} "
            f"arelle_item_fact_count={report.arelle_item_fact_count}"
        )
    try:
        validate_report_extraction(report)
    except ReportIntegrityError as exc:
        raise FilingExtractError(
            f"report integrity failed for report_key={report.report_key}: {exc}"
        ) from exc
    return ReportExtractOutcome(
        report=report,
        worker=worker,
        upstream_inventory=upstream,
    )


def _inventory_map_for_bundle(
    bundle: FilingBundle,
    store: ObjectStore,
) -> dict[str, UpstreamInventory]:
    keys = [compute_report_key(inp) for inp in bundle.report_inputs]
    assert_unique_report_keys(keys)
    expected = frozenset(keys)
    inventory_outcomes = build_inventory_outcomes(bundle, store)
    if any_inventory_failure(inventory_outcomes):
        failure = _first_inventory_failure(inventory_outcomes)
        raise FilingExtractError(
            f"inventory failed for report_key={failure.report_key}: "
            f"{failure.code}: {failure.message}"
        )
    return inventory_by_key(inventory_outcomes, expected)


def extract_report_with_outcome(
    bundle: FilingBundle,
    store: ObjectStore,
    report_input: XbrlReportInput,
    *,
    semantic_config: SemanticConfig,
    python_executable: str = sys.executable,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
    upstream_inventory: UpstreamInventory | None = None,
) -> ReportExtractOutcome:
    """Extract one report with an explicit typed semantic config."""
    key = compute_report_key(report_input)
    upstream = upstream_inventory
    if upstream is None:
        upstream = _inventory_map_for_bundle(bundle, store)[key]
    result = run_offline_extract(
        bundle,
        store,
        report_input=report_input,
        semantic_config=semantic_config,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
    )
    return _finalize_report_outcome(result.report, result, upstream)


def extract_report(
    bundle: FilingBundle,
    store: ObjectStore,
    report_input: XbrlReportInput,
    *,
    python_executable: str = sys.executable,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> ReportExtraction:
    """Extract one report input into a source ``ReportExtraction``."""
    return extract_report_with_outcome(
        bundle,
        store,
        report_input,
        semantic_config=build_semantic_config(),
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
    ).report


def extract_filing_with_outcomes(
    bundle: FilingBundle,
    store: ObjectStore,
    *,
    semantic_config: SemanticConfig,
    python_executable: str = sys.executable,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> FilingExtractOutcome:
    """Extract every report input plus eligible HTML documents.

    Document parse happens outside any DB transaction. Fatal document parse
    errors propagate so callers can skip snapshot replacement. A fatal failure
    of any report aborts the entire filing extraction.
    """
    keys = [compute_report_key(inp) for inp in bundle.report_inputs]
    assert_unique_report_keys(keys)
    expected = frozenset(keys)
    inv_by_key = _inventory_map_for_bundle(bundle, store)

    report_outcomes: list[ReportExtractOutcome] = []
    for report_input in bundle.report_inputs:
        key = compute_report_key(report_input)
        result = run_offline_extract(
            bundle,
            store,
            report_input=report_input,
            semantic_config=semantic_config,
            python_executable=python_executable,
            timeout_seconds=timeout_seconds,
        )
        report_outcomes.append(_finalize_report_outcome(result.report, result, inv_by_key[key]))

    validate_outcome_keys(
        expected,
        tuple(report_outcomes),
        key_of=lambda o: o.report.report_key,
        label="worker",
    )

    blocks, sections, doc_issues = extract_documents_for_filing(bundle, store)
    extraction = FilingExtraction(
        reports=tuple(item.report for item in report_outcomes),
        document_blocks=blocks,
        filing_sections=sections,
        issues=doc_issues,
    )
    return FilingExtractOutcome(extraction=extraction, report_outcomes=tuple(report_outcomes))


def extract_filing(
    bundle: FilingBundle,
    store: ObjectStore,
    *,
    python_executable: str = sys.executable,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> FilingExtraction:
    """Extract every report input plus eligible HTML documents."""
    return extract_filing_with_outcomes(
        bundle,
        store,
        semantic_config=build_semantic_config(),
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
    ).extraction


__all__ = [
    "FilingExtractError",
    "FilingExtractOutcome",
    "ReportExtractOutcome",
    "extract_filing",
    "extract_filing_with_outcomes",
    "extract_report",
    "extract_report_with_outcome",
]
