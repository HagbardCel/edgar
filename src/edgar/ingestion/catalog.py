"""Application service: catalog a published filesystem FilingBundle into source.*.

Phase 2B Commit 4: live catalog writes ``source.issuer`` / ``filing`` /
``document`` only (no Phase-1 ``filing_bundle`` dual write).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from edgar.config import Settings
from edgar.db.engine import create_db_engine
from edgar.db.source import SourceCatalogConflict, catalog_source_filing
from edgar.storage.bundles import BundleRepository, validate_published_bundle_path
from edgar.storage.objects import ObjectStore

# Preserve the historical CatalogConflict name for callers/tests.
CatalogConflict = SourceCatalogConflict


@dataclass(frozen=True)
class CatalogResult:
    filing_id: int
    accession: str
    issuer_cik: str
    document_count: int
    opaque_id: str
    reused: bool


class CatalogService:
    """Validate a published bundle under EDGAR_DATA_ROOT, then catalog into source.*."""

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

    def _require_engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        url = self._settings.require_database_url()
        self._engine = create_db_engine(url)
        return self._engine

    def catalog_published_bundle(self, bundle_dir: Path) -> CatalogResult:
        opaque_id, cik, accession = validate_published_bundle_path(
            self._settings.edgar_data_root, bundle_dir
        )
        bundle = self._bundles.load(bundle_dir)
        if bundle.filing.cik != cik or bundle.filing.accession != accession:
            raise ValueError(f"bundle filing identity does not match directory path {bundle_dir}")
        engine = self._require_engine()
        with engine.begin() as conn:
            result = catalog_source_filing(conn, bundle)
        return CatalogResult(
            filing_id=result.filing_id,
            accession=result.accession,
            issuer_cik=result.issuer_cik,
            document_count=result.document_count,
            opaque_id=opaque_id,
            reused=result.reused,
        )


__all__ = ["CatalogConflict", "CatalogResult", "CatalogService"]
