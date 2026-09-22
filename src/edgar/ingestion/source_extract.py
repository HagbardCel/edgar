"""Application service: source.* catalog + extract + persist for a published bundle."""

from __future__ import annotations

import hashlib
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
from edgar.domain.bundle import bundles_equivalent
from edgar.provenance import (
    ImplementationIdentity,
    gather_dependency_lock_sha256,
    gather_implementation_identity,
)
from edgar.storage.bundles import BundleRepository, validate_published_bundle_path
from edgar.storage.objects import ObjectStore
from edgar.xbrl.closure import DEFAULT_WORKER_TIMEOUT_SECONDS
from edgar.xbrl.config import SemanticConfig, build_semantic_config
from edgar.xbrl.extraction_receipt import (
    BundleRef,
    build_extraction_receipt,
    load_bundle_ref,
)
from edgar.xbrl.source_extract import extract_filing_with_outcomes
from edgar.xbrl.worker import WORKER_PROTOCOL_VERSION


class SourceExtractError(RuntimeError):
    """Source extraction or persistence failed (no snapshot replacement on failure)."""


@dataclass(frozen=True)
class ExtractionRunContext:
    """Provenance/config captured once before worker execution."""

    implementation: ImplementationIdentity
    dependency_lock_sha256: str | None
    bundle_ref: BundleRef
    semantic_config: SemanticConfig


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
        loaded = self._bundles.load(bundle_dir)
        if loaded.filing.cik != cik or loaded.filing.accession != accession:
            raise ValueError(f"bundle filing identity does not match directory path {bundle_dir}")

        captured = load_bundle_ref(
            data_root=self._settings.edgar_data_root,
            bundle_dir=bundle_dir,
        )
        if not bundles_equivalent(captured.bundle, loaded):
            raise SourceExtractError(
                "authoritative descriptor read is not equivalent to BundleRepository.load()"
            )
        bundle = captured.bundle
        bundle_ref = captured.bundle_ref

        pre_implementation = gather_implementation_identity()
        pre_lock = gather_dependency_lock_sha256()
        semantic_config = build_semantic_config()
        context = ExtractionRunContext(
            implementation=pre_implementation,
            dependency_lock_sha256=pre_lock,
            bundle_ref=bundle_ref,
            semantic_config=semantic_config,
        )

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
                semantic_config=context.semantic_config,
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 — any extract failure skips replacement
            raise SourceExtractError(str(exc)) from exc

        post_implementation = gather_implementation_identity()
        post_lock = gather_dependency_lock_sha256()
        if post_implementation != context.implementation:
            raise SourceExtractError("implementation identity changed during extraction")
        if post_lock != context.dependency_lock_sha256:
            raise SourceExtractError("dependency lock digest changed during extraction")
        descriptor_path = (
            self._settings.edgar_data_root.expanduser().resolve()
            / context.bundle_ref.descriptor_relative_path
        )
        try:
            post_sha = hashlib.sha256(descriptor_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise SourceExtractError(f"cannot re-read descriptor after extraction: {exc}") from exc
        if post_sha != context.bundle_ref.descriptor_sha256:
            raise SourceExtractError("descriptor SHA changed during extraction")

        extraction = filing_outcome.extraction
        config_payload = context.semantic_config.to_dict()
        persistable_reports: list[PersistableReport] = []
        for report_outcome in filing_outcome.report_outcomes:
            report = report_outcome.report
            worker = report_outcome.worker
            receipt = build_extraction_receipt(
                bundle_ref=context.bundle_ref,
                report_input=report.report_input,
                semantic_config=config_payload,
                arelle_version=worker.arelle_version,
                worker_protocol_version=WORKER_PROTOCOL_VERSION,
                implementation=context.implementation,
                dependency_lock_sha256=context.dependency_lock_sha256,
            )
            persistable_reports.append(
                PersistableReport(
                    report=report,
                    extraction_receipt=receipt,
                    upstream_inventory=report_outcome.upstream_inventory,
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
        inv_by_key = {
            ro.report.report_key: ro.upstream_inventory for ro in filing_outcome.report_outcomes
        }
        for probe in report_probes:
            if probe.arelle_item_fact_count != probe.fact_dto_count:
                raise SourceExtractError(
                    "layer-A completeness failed before persist: "
                    f"report_key={probe.report_key} "
                    f"arelle_item_fact_count={probe.arelle_item_fact_count} "
                    f"fact_dto_count={probe.fact_dto_count}"
                )
            upstream = inv_by_key[probe.report_key]
            if upstream.selected_target_item_count != probe.arelle_item_fact_count:
                raise SourceExtractError(
                    "upstream vs worker completeness failed before persist: "
                    f"report_key={probe.report_key} "
                    f"selected_target_item_count={upstream.selected_target_item_count} "
                    f"arelle_item_fact_count={probe.arelle_item_fact_count}"
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
    "ExtractionRunContext",
    "ReportCompletenessProbe",
    "SourceExtractError",
    "SourceExtractResult",
    "SourceExtractService",
]
