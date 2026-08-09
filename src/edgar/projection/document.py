"""Application service: offline document projection for a cataloged bundle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, Engine, select

from edgar.config import Settings
from edgar.db import schema as tables
from edgar.db.catalog import CatalogConflict, load_bundle, resolve_cataloged_bundle
from edgar.db.document import (
    DocumentFailureResult,
    DocumentProjectionConflict,
    DocumentProjectionResult,
    catalog_document_projection,
    ensure_filing_document,
    record_document_projection_failure,
)
from edgar.db.engine import create_db_engine
from edgar.domain.bundle import BundleArtifact, FilingBundle, bundles_equivalent
from edgar.parsing.config import (
    DOCUMENT_PROJECTION_VERSION,
    build_document_config,
    document_config_fingerprint,
)
from edgar.parsing.html import parse_html_document
from edgar.parsing.records import DocumentIssueRecord, DocumentParseError, DocumentProjectionData
from edgar.parsing.sections import extract_filing_sections
from edgar.storage.bundles import BundleRepository, validate_published_bundle_path
from edgar.storage.objects import ObjectStore


class DocumentProjectionError(RuntimeError):
    """Document projection failed after optional failed-attempt persistence."""

    def __init__(
        self,
        message: str,
        *,
        failure: DocumentFailureResult | None = None,
    ) -> None:
        super().__init__(message)
        self.failure = failure


class DocumentPreflightError(ValueError):
    """Preflight failure: no attempt is recorded."""


@dataclass(frozen=True)
class ProjectDocumentResult:
    accession: str
    bundle_id: int
    filing_document_id: int
    artifact_path: str
    projection: DocumentProjectionResult


def _is_html_path(logical_path: str) -> bool:
    lower = logical_path.lower()
    return lower.endswith(".htm") or lower.endswith(".html")


def _resolve_target_artifact(
    bundle: FilingBundle,
    *,
    artifact_path: str | None,
) -> tuple[BundleArtifact, bool]:
    """Return (artifact, is_primary). Raises DocumentPreflightError on failure."""
    if artifact_path is None:
        primary_path = f"accession/{bundle.filing.primary_document}"
        matches = [a for a in bundle.artifacts if a.logical_path == primary_path]
        if len(matches) != 1:
            raise DocumentPreflightError(
                f"default primary document not found as exactly one artifact: {primary_path}"
            )
        artifact = matches[0]
        if artifact.artifact_kind != "primary_document":
            raise DocumentPreflightError(
                "default primary artifact_kind must be primary_document, "
                f"got {artifact.artifact_kind!r}"
            )
        if not _is_html_path(artifact.logical_path):
            raise DocumentPreflightError(
                f"default primary document is not HTML: {artifact.logical_path}"
            )
        return artifact, True

    matches = [a for a in bundle.artifacts if a.logical_path == artifact_path]
    if len(matches) != 1:
        raise DocumentPreflightError(
            f"artifact_path not found in bundle (exactly one required): {artifact_path}"
        )
    artifact = matches[0]
    if artifact.artifact_kind not in {"primary_document", "attachment"}:
        raise DocumentPreflightError(
            f"unsupported artifact_kind for document projection: {artifact.artifact_kind!r}"
        )
    if not _is_html_path(artifact.logical_path):
        raise DocumentPreflightError(f"unsupported non-HTML artifact: {artifact.logical_path}")
    primary_path = f"accession/{bundle.filing.primary_document}"
    is_primary = (
        artifact.logical_path == primary_path and artifact.artifact_kind == "primary_document"
    )
    return artifact, is_primary


def _artifact_db_id(conn: Connection, bundle_id: int, logical_path: str) -> int:
    row = conn.execute(
        select(tables.bundle_artifact.c.id)
        .where(tables.bundle_artifact.c.filing_bundle_id == bundle_id)
        .where(tables.bundle_artifact.c.logical_path == logical_path)
    ).scalar_one_or_none()
    if row is None:
        raise DocumentPreflightError(f"cataloged artifact missing for path {logical_path}")
    return int(row)


class DocumentProjectionService:
    """Project an HTML filing document of a published, already-cataloged bundle."""

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

    def project_published_bundle(
        self,
        bundle_dir: Path,
        *,
        artifact_path: str | None = None,
    ) -> ProjectDocumentResult:
        opaque_id, cik, accession = validate_published_bundle_path(
            self._settings.edgar_data_root, bundle_dir
        )
        fs_bundle = self._bundles.load(bundle_dir)
        if fs_bundle.filing.cik != cik or fs_bundle.filing.accession != accession:
            raise ValueError(f"bundle filing identity does not match directory path {bundle_dir}")

        artifact, is_primary = _resolve_target_artifact(fs_bundle, artifact_path=artifact_path)

        engine = self._require_engine()
        with engine.connect() as conn:
            bundle_id, _report_input_id = resolve_cataloged_bundle(
                conn, cik=cik, accession=accession, opaque_id=opaque_id
            )
            db_bundle = load_bundle(conn, bundle_id)
            if not bundles_equivalent(fs_bundle, db_bundle):
                raise CatalogConflict(
                    "filesystem FilingBundle is not equivalent to the cataloged bundle; "
                    "refusing document projection"
                )
            # Confirm artifact exists in catalog before starting an attempt.
            _artifact_db_id(conn, bundle_id, artifact.logical_path)

        config = build_document_config()
        config_dict = config.to_dict()
        fingerprint = document_config_fingerprint(config)
        started_at = datetime.now(UTC)

        html_bytes = self._store.open_bytes(artifact.content.sha256)
        try:
            parsed = parse_html_document(html_bytes)
        except DocumentParseError as exc:
            completed_at = datetime.now(UTC)
            with engine.begin() as conn:
                artifact_id = _artifact_db_id(conn, bundle_id, artifact.logical_path)
                filing_document_id = ensure_filing_document(conn, artifact_id)
                failure = record_document_projection_failure(
                    conn,
                    filing_document_id=filing_document_id,
                    parser_version=DOCUMENT_PROJECTION_VERSION,
                    parser_config=config_dict,
                    config_fingerprint=fingerprint,
                    started_at=started_at,
                    completed_at=completed_at,
                    issues=exc.issues,
                )
            raise DocumentProjectionError(str(exc), failure=failure) from exc

        sections, section_issues, status, _terminal = extract_filing_sections(
            parsed,
            form_type=fs_bundle.filing.form_type,
            extract_regulatory_sections=is_primary,
        )
        issues = list(parsed.issues) + list(section_issues)
        projection_data = DocumentProjectionData(
            parser_version=DOCUMENT_PROJECTION_VERSION,
            config_fingerprint=fingerprint,
            blocks=parsed.blocks,
            sections=tuple(sections),
            issues=tuple(issues),
        )
        completed_at = datetime.now(UTC)
        try:
            with engine.begin() as conn:
                artifact_id = _artifact_db_id(conn, bundle_id, artifact.logical_path)
                filing_document_id = ensure_filing_document(conn, artifact_id)
                result = catalog_document_projection(
                    conn,
                    filing_document_id=filing_document_id,
                    projection_data=projection_data,
                    status=status,
                    parser_config=config_dict,
                    started_at=started_at,
                    completed_at=completed_at,
                )
        except DocumentProjectionConflict as exc:
            with engine.begin() as conn:
                artifact_id = _artifact_db_id(conn, bundle_id, artifact.logical_path)
                filing_document_id = ensure_filing_document(conn, artifact_id)
                failure = record_document_projection_failure(
                    conn,
                    filing_document_id=filing_document_id,
                    parser_version=DOCUMENT_PROJECTION_VERSION,
                    parser_config=config_dict,
                    config_fingerprint=fingerprint,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    issues=(
                        DocumentIssueRecord(
                            severity="fatal",
                            code="DOCUMENT_PROJECTION_CONFLICT",
                            message=str(exc),
                        ),
                    ),
                )
            raise DocumentProjectionError(str(exc), failure=failure) from exc

        return ProjectDocumentResult(
            accession=accession,
            bundle_id=bundle_id,
            filing_document_id=filing_document_id,
            artifact_path=artifact.logical_path,
            projection=result,
        )


__all__ = [
    "DocumentPreflightError",
    "DocumentProjectionError",
    "DocumentProjectionService",
    "ProjectDocumentResult",
]
