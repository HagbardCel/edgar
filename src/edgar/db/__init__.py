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
from edgar.db.metrics import (
    MappingRuleRow,
    MetricRegistryConflict,
    RegistryRevisionRow,
    SourceFactOccurrence,
    SyncResult,
    get_latest_revision,
    get_mapping,
    get_metric,
    get_supersession_chain,
    list_mappings,
    list_metrics,
    query_source_fact_occurrences,
    sync_registry,
    verify_materialization,
)
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
    "MappingRuleRow",
    "MetricRegistryConflict",
    "RegistryRevisionRow",
    "SemanticProjectionConflict",
    "SemanticProjectionResult",
    "SourceFactOccurrence",
    "SyncResult",
    "catalog_bundle",
    "catalog_document_projection",
    "catalog_semantic_projection",
    "create_db_engine",
    "ensure_filing_document",
    "get_latest_revision",
    "get_mapping",
    "get_metric",
    "get_supersession_chain",
    "list_document_sections",
    "list_mappings",
    "list_metrics",
    "load_bundle",
    "load_document_projection",
    "load_semantic_projection",
    "metadata",
    "query_source_fact_occurrences",
    "record_document_projection_failure",
    "record_semantic_projection_failure",
    "resolve_cataloged_bundle",
    "sync_registry",
    "verify_materialization",
]
