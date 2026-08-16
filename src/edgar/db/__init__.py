"""PostgreSQL package: engines, source catalog/extraction, schema metadata."""

from edgar.db.engine import create_db_engine
from edgar.db.schema import ALL_TABLES, SOURCE_TABLES, metadata
from edgar.db.source import (
    PersistExtractionResult,
    SourceCatalogConflict,
    SourceCatalogResult,
    catalog_source_filing,
    list_source_document_sections,
    persist_extraction,
)

__all__ = [
    "ALL_TABLES",
    "PersistExtractionResult",
    "SOURCE_TABLES",
    "SourceCatalogConflict",
    "SourceCatalogResult",
    "catalog_source_filing",
    "create_db_engine",
    "list_source_document_sections",
    "metadata",
    "persist_extraction",
]
