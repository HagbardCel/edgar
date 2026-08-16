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
from edgar.storage.bundles import BundleRepository, validate_published_bundle_path
from edgar.storage.objects import ObjectStore
from edgar.xbrl.source_extract import extract_filing


class SourceExtractError(RuntimeError):
    """Source extraction or persistence failed (no snapshot replacement on failure)."""


@dataclass(frozen=True)
class SourceExtractResult:
    accession: str
    opaque_id: str
    filing_id: int
    catalog_reused: bool
    document_count: int
    persist: PersistExtractionResult


class SourceExtractService:
    """Catalog (source.*) if needed, extract offline, then atomically persist."""

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
            extraction = extract_filing(bundle, self._store)
        except Exception as exc:  # noqa: BLE001 — any extract failure skips replacement
            raise SourceExtractError(str(exc)) from exc

        try:
            with engine.begin() as conn:
                persist = persist_extraction(
                    conn, filing_id=catalog.filing_id, extraction=extraction
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
        )


__all__ = [
    "SourceExtractError",
    "SourceExtractResult",
    "SourceExtractService",
]
