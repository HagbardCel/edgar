"""Application service: offline Arelle semantic projection for a cataloged bundle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

from edgar.config import Settings
from edgar.db.catalog import CatalogConflict, load_bundle, resolve_cataloged_bundle
from edgar.db.engine import create_db_engine
from edgar.db.semantic import (
    SemanticFailureResult,
    SemanticProjectionConflict,
    SemanticProjectionResult,
    catalog_semantic_projection,
    record_semantic_projection_failure,
)
from edgar.domain.bundle import bundles_equivalent
from edgar.storage.bundles import BundleRepository, validate_published_bundle_path
from edgar.storage.objects import ObjectStore
from edgar.xbrl.config import (
    SEMANTIC_PROJECTION_VERSION,
    build_semantic_config,
    semantic_config_fingerprint,
)
from edgar.xbrl.records import SemanticIssueRecord
from edgar.xbrl.semantic import SemanticWorkerError, run_offline_semantic_projection


class SemanticProjectionError(RuntimeError):
    """Semantic projection failed after optional failed-attempt persistence."""

    def __init__(
        self,
        message: str,
        *,
        failure: SemanticFailureResult | None = None,
    ) -> None:
        super().__init__(message)
        self.failure = failure


@dataclass(frozen=True)
class ProjectPublishedBundleResult:
    accession: str
    bundle_id: int
    report_input_id: int
    projection: SemanticProjectionResult


class SemanticProjectionService:
    """Project the primary XBRL report of a published, already-cataloged bundle."""

    def __init__(
        self,
        settings: Settings,
        *,
        engine: Engine | None = None,
        bundles: BundleRepository | None = None,
    ) -> None:
        self._settings = settings
        self._engine = engine
        if bundles is None:
            store = ObjectStore(settings.edgar_data_root)
            bundles = BundleRepository(settings.edgar_data_root, store)
        self._bundles = bundles
        self._store = bundles.store

    def _require_engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        url = self._settings.require_database_url()
        self._engine = create_db_engine(url)
        return self._engine

    def project_published_bundle(self, bundle_dir: Path) -> ProjectPublishedBundleResult:
        opaque_id, cik, accession = validate_published_bundle_path(
            self._settings.edgar_data_root, bundle_dir
        )
        fs_bundle = self._bundles.load(bundle_dir)
        if fs_bundle.filing.cik != cik or fs_bundle.filing.accession != accession:
            raise ValueError(f"bundle filing identity does not match directory path {bundle_dir}")

        engine = self._require_engine()
        with engine.connect() as conn:
            bundle_id, report_input_id = resolve_cataloged_bundle(
                conn, cik=cik, accession=accession, opaque_id=opaque_id
            )
            db_bundle = load_bundle(conn, bundle_id)
        if not bundles_equivalent(fs_bundle, db_bundle):
            raise CatalogConflict(
                "filesystem FilingBundle is not equivalent to the cataloged bundle; "
                "refusing semantic projection"
            )

        config = build_semantic_config()
        config_dict = config.to_dict()
        fingerprint = semantic_config_fingerprint(config)
        started_at = datetime.now(UTC)

        try:
            worker = run_offline_semantic_projection(fs_bundle, self._store)
        except SemanticWorkerError as exc:
            completed_at = datetime.now(UTC)
            with engine.begin() as conn:
                failure = record_semantic_projection_failure(
                    conn,
                    report_input_id=report_input_id,
                    projection_version=SEMANTIC_PROJECTION_VERSION,
                    semantic_config=config_dict,
                    config_fingerprint=fingerprint,
                    arelle_version=exc.arelle_version,
                    started_at=started_at,
                    completed_at=completed_at,
                    issues=exc.issues
                    or (
                        SemanticIssueRecord(
                            severity="fatal",
                            code="SEMANTIC_WORKER_FAILED",
                            message=str(exc),
                        ),
                    ),
                )
            raise SemanticProjectionError(str(exc), failure=failure) from exc

        completed_at = datetime.now(UTC)
        try:
            with engine.begin() as conn:
                result = catalog_semantic_projection(
                    conn,
                    report_input_id=report_input_id,
                    bundle_id=bundle_id,
                    projection_data=worker.data,
                    status=worker.status,
                    semantic_config=config_dict,
                    started_at=started_at,
                    completed_at=completed_at,
                )
        except SemanticProjectionConflict as exc:
            with engine.begin() as conn:
                failure = record_semantic_projection_failure(
                    conn,
                    report_input_id=report_input_id,
                    projection_version=SEMANTIC_PROJECTION_VERSION,
                    semantic_config=config_dict,
                    config_fingerprint=fingerprint,
                    arelle_version=worker.arelle_version,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    issues=(
                        SemanticIssueRecord(
                            severity="fatal",
                            code="SEMANTIC_PROJECTION_CONFLICT",
                            message=str(exc),
                        ),
                    ),
                )
            raise SemanticProjectionError(str(exc), failure=failure) from exc

        return ProjectPublishedBundleResult(
            accession=accession,
            bundle_id=bundle_id,
            report_input_id=report_input_id,
            projection=result,
        )


__all__ = [
    "ProjectPublishedBundleResult",
    "SemanticProjectionError",
    "SemanticProjectionService",
]
