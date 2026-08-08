"""Application service: catalog a published filesystem FilingBundle."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine

from edgar.config import Settings
from edgar.db.catalog import CatalogConflict, CatalogResult, catalog_bundle
from edgar.db.engine import create_db_engine
from edgar.storage.bundles import BundleRepository, validate_published_bundle_path
from edgar.storage.objects import ObjectStore


class CatalogService:
    """Validate a published bundle under EDGAR_DATA_ROOT, then catalog it."""

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
            return catalog_bundle(conn, bundle, opaque_id)


__all__ = ["CatalogConflict", "CatalogResult", "CatalogService"]
