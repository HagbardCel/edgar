"""PostgreSQL catalog package."""

from edgar.db.catalog import (
    CatalogConflict,
    CatalogResult,
    catalog_bundle,
    load_bundle,
    resolve_cataloged_bundle,
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
    "SemanticProjectionConflict",
    "SemanticProjectionResult",
    "catalog_bundle",
    "catalog_semantic_projection",
    "create_db_engine",
    "load_bundle",
    "load_semantic_projection",
    "metadata",
    "record_semantic_projection_failure",
    "resolve_cataloged_bundle",
]
