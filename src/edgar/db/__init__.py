"""PostgreSQL catalog package."""

from edgar.db.catalog import (
    CatalogConflict,
    CatalogResult,
    catalog_bundle,
    load_bundle,
    resolve_cataloged_bundle,
)
from edgar.db.document import (
    DocumentProjectionConflict,
    DocumentProjectionResult,
    catalog_document_projection,
    ensure_filing_document,
    list_document_sections,
    load_document_projection,
    record_document_projection_failure,
)
from edgar.db.engine import create_db_engine
from edgar.db.schema import metadata
from edgar.db.semantic import (
    SemanticProjectionConflict,
    SemanticProjectionResult,
    catalog_semantic_projection,
    load_semantic_projection,
    record_semantic_projection_failure,
)

__all__ = [
    "CatalogConflict",
    "CatalogResult",
    "DocumentProjectionConflict",
    "DocumentProjectionResult",
    "SemanticProjectionConflict",
    "SemanticProjectionResult",
    "catalog_bundle",
    "catalog_document_projection",
    "catalog_semantic_projection",
    "create_db_engine",
    "ensure_filing_document",
    "list_document_sections",
    "load_bundle",
    "load_document_projection",
    "load_semantic_projection",
    "metadata",
    "record_document_projection_failure",
    "record_semantic_projection_failure",
    "resolve_cataloged_bundle",
]
