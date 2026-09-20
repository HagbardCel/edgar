"""Application service: source.* catalog + extract + persist for a published bundle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from edgar.config import Settings
from edgar.db.engine import create_db_engine
from edgar.db.source import (
    PersistExtractionError,
    PersistExtractionResult,
    SourceCatalogConflict,
    catalog_source_filing,
    persist_extraction,
)
from edgar.db.source_persist import PersistableFilingExtraction, PersistableReport
from edgar.provenance import gather_dependency_lock_sha256, gather_implementation_identity
from edgar.storage.bundles import BundleRepository, validate_published_bundle_path
from edgar.storage.objects import ObjectStore
from edgar.xbrl.closure import DEFAULT_WORKER_TIMEOUT_SECONDS
from edgar.xbrl.extraction_receipt import (
    build_bundle_ref,
    build_extraction_receipt,
    verify_extraction_config_chain,
)
from edgar.xbrl.source_extract import extract_filing_with_outcomes
from edgar.xbrl.worker import WORKER_PROTOCOL_VERSION


class SourceExtractError(RuntimeError):
    """Source extraction or persistence failed (no snapshot replacement on failure)."""


@dataclass(frozen=True)
class ReportCompletenessProbe:
    """Layer-A completeness: iterator/DTO/persisted fact counts for one report."""

    report_key: str
    arelle_item_fact_count: int
    fact_dto_count: int
    concept_count: int
    declaration_count: int
    context_count: int
    dimension_count: int
    unit_count: int
    measure_count: int
    relationship_count: int
    issue_count: int


@dataclass(frozen=True)
class SourceExtractResult:
    accession: str
    opaque_id: str
    filing_id: int
    catalog_reused: bool
    document_count: int
    persist: PersistExtractionResult
    report_probes: tuple[ReportCompletenessProbe, ...] = ()


class SourceExtractService:
    """Catalog (source.*) if needed, extract offline, then atomically persist."""

    def __init__(
        self,
        settings: Settings,
        *,
        engine: Engine | None = None,
        bundles: BundleRepository | None = None,
        timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings
        self._engine = engine
        if bundles is None:
            store = ObjectStore(settings.edgar_data_root)
            bundles = BundleRepository(settings.edgar_data_root, store)
        self._bundles = bundles
        self._store = bundles.store
        self._timeout_seconds = timeout_seconds

    def _require_engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        url = self._settings.require_database_url()
        self._engine = create_db_engine(url)
        return self._engine

    def extract_published_bundle(self, bundle_dir: Path) -> SourceExtractResult:
        opaque_id, cik, accession = validate_published_bundle_path(
            self._settings.edgar_data_root, bundle_dir
        )
        bundle = self._bundles.load(bundle_dir)
        if bundle.filing.cik != cik or bundle.filing.accession != accession:
            raise ValueError(f"bundle filing identity does not match directory path {bundle_dir}")

        engine = self._require_engine()
        with engine.begin() as conn:
            try:
                catalog = catalog_source_filing(conn, bundle)
            except SourceCatalogConflict as exc:
                raise SourceExtractError(str(exc)) from exc

        try:
            filing_outcome = extract_filing_with_outcomes(
                bundle,
                self._store,
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 — any extract failure skips replacement
            raise SourceExtractError(str(exc)) from exc

        extraction = filing_outcome.extraction
        implementation = gather_implementation_identity()
        lock_sha = gather_dependency_lock_sha256()
        bundle_ref = build_bundle_ref(
            data_root=self._settings.edgar_data_root,
            bundle_dir=bundle_dir,
            bundle=bundle,
        )
        persistable_reports: list[PersistableReport] = []
        for report_outcome in filing_outcome.report_outcomes:
            report = report_outcome.report
            worker = report_outcome.worker
            semantic_config = worker.effective_semantic_config
            verify_extraction_config_chain(
                job_semantic_config=semantic_config,
                worker_effective_semantic_config=semantic_config,
                receipt_semantic_config=semantic_config,
                worker_protocol_version=str(worker.raw_result.get("protocol_version") or ""),
                expected_worker_protocol_version=WORKER_PROTOCOL_VERSION,
                receipt_worker_protocol_version=WORKER_PROTOCOL_VERSION,
            )
            receipt = build_extraction_receipt(
                bundle_ref=bundle_ref,
                report_input=report.report_input,
                semantic_config=semantic_config,
                arelle_version=worker.arelle_version,
                worker_protocol_version=WORKER_PROTOCOL_VERSION,
                implementation=implementation,
                dependency_lock_sha256=lock_sha,
            )
            persistable_reports.append(
                PersistableReport(
                    report=report,
                    extraction_receipt=receipt,
                    upstream_inventory=None,
                )
            )
        persistable = PersistableFilingExtraction(
            reports=tuple(persistable_reports),
            document_blocks=extraction.document_blocks,
            filing_sections=extraction.filing_sections,
            issues=extraction.issues,
        )

        report_probes = tuple(
            ReportCompletenessProbe(
                report_key=report.report_key,
                arelle_item_fact_count=report.arelle_item_fact_count,
                fact_dto_count=len(report.facts),
                concept_count=len(report.concepts),
                declaration_count=len(report.declarations),
                context_count=len(report.contexts),
                dimension_count=len(report.dimensions),
                unit_count=len(report.units),
                measure_count=len(report.measures),
                relationship_count=len(report.relationships),
                issue_count=len(report.issues),
            )
            for report in extraction.reports
        )
        for probe in report_probes:
            if probe.arelle_item_fact_count != probe.fact_dto_count:
                raise SourceExtractError(
                    "layer-A completeness failed before persist: "
                    f"report_key={probe.report_key} "
                    f"arelle_item_fact_count={probe.arelle_item_fact_count} "
                    f"fact_dto_count={probe.fact_dto_count}"
                )

        try:
            with engine.begin() as conn:
                persist = persist_extraction(
                    conn, filing_id=catalog.filing_id, extraction=persistable
                )
        except PersistExtractionError as exc:
            raise SourceExtractError(str(exc)) from exc

        return SourceExtractResult(
            accession=accession,
            opaque_id=opaque_id,
            filing_id=catalog.filing_id,
            catalog_reused=catalog.reused,
            document_count=catalog.document_count,
            persist=persist,
            report_probes=report_probes,
        )


__all__ = [
    "ReportCompletenessProbe",
    "SourceExtractError",
    "SourceExtractResult",
    "SourceExtractService",
]
