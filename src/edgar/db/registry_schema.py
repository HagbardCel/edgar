"""Phase 2C ``registry.*`` SQLAlchemy table definitions."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from edgar.db.schema import SHA256_CHECK, metadata

REGISTRY_SCHEMA = "registry"

registry_canonical_metric = Table(
    "canonical_metric",
    metadata,
    Column("key", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("statement", Text, nullable=False),
    Column("period_type", Text, nullable=False),
    Column("value_kind", Text, nullable=False),
    Column("unit_dimension", Text, nullable=False),
    Column("definition", Text, nullable=False),
    Column("includes", JSONB, nullable=False),
    Column("excludes", JSONB, nullable=False),
    Column("definition_hash", Text, nullable=False),
    Column("synced_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("key", name="canonical_metric_pkey"),
    CheckConstraint("kind = 'reported'", name="ck_registry_canonical_metric_kind"),
    CheckConstraint(
        "statement IN ('income_statement', 'balance_sheet', 'cash_flow', 'per_share', 'shares')",
        name="ck_registry_canonical_metric_statement",
    ),
    CheckConstraint(
        "period_type IN ('instant', 'duration')",
        name="ck_registry_canonical_metric_period_type",
    ),
    CheckConstraint("value_kind = 'numeric'", name="ck_registry_canonical_metric_value_kind"),
    CheckConstraint(
        "unit_dimension IN ('monetary', 'shares', 'monetary_per_share')",
        name="ck_registry_canonical_metric_unit_dimension",
    ),
    CheckConstraint(
        f"definition_hash ~ '{SHA256_CHECK}'",
        name="ck_registry_canonical_metric_definition_hash",
    ),
    CheckConstraint(
        "jsonb_typeof(includes) = 'array'",
        name="ck_registry_canonical_metric_includes_array",
    ),
    CheckConstraint(
        "jsonb_typeof(excludes) = 'array'",
        name="ck_registry_canonical_metric_excludes_array",
    ),
    schema=REGISTRY_SCHEMA,
)

registry_mapping_assertion = Table(
    "mapping_assertion",
    metadata,
    Column("id", BigInteger, Identity(), nullable=False),
    Column("supersedes_id", BigInteger, nullable=True),
    Column("source_concept_id", UUID(as_uuid=True), nullable=False),
    Column("target_metric_key", Text, nullable=False),
    Column("target_definition_hash", Text, nullable=False),
    Column("relation", Text, nullable=False),
    Column("scope_kind", Text, nullable=False),
    Column("issuer_cik", Text, nullable=True),
    Column("valid_from", Date, nullable=True),
    Column("valid_to", Date, nullable=True),
    Column("status", Text, nullable=False),
    Column("method", Text, nullable=False),
    Column("rationale", Text, nullable=True),
    Column("evidence", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("created_by", Text, nullable=False),
    PrimaryKeyConstraint("id", name="mapping_assertion_pkey"),
    UniqueConstraint("supersedes_id", name="uq_registry_mapping_assertion_supersedes_id"),
    ForeignKeyConstraint(
        ["supersedes_id"],
        [f"{REGISTRY_SCHEMA}.mapping_assertion.id"],
        name="mapping_assertion_supersedes_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_concept_id"],
        ["source.concept.id"],
        name="mapping_assertion_source_concept_id_fkey",
    ),
    ForeignKeyConstraint(
        ["target_metric_key"],
        [f"{REGISTRY_SCHEMA}.canonical_metric.key"],
        name="mapping_assertion_target_metric_key_fkey",
    ),
    ForeignKeyConstraint(
        ["issuer_cik"],
        ["source.issuer.cik"],
        name="mapping_assertion_issuer_cik_fkey",
    ),
    CheckConstraint(
        "relation IN ('exact', 'narrower', 'broader', 'related')",
        name="ck_registry_mapping_assertion_relation",
    ),
    CheckConstraint(
        "scope_kind IN ('global', 'issuer')",
        name="ck_registry_mapping_assertion_scope_kind",
    ),
    CheckConstraint(
        "status IN ('candidate', 'accepted', 'rejected')",
        name="ck_registry_mapping_assertion_status",
    ),
    CheckConstraint(
        "method IN ('curated', 'deterministic_rule', 'lexical_candidate', "
        "'structural_candidate', 'model_candidate', 'human_review')",
        name="ck_registry_mapping_assertion_method",
    ),
    CheckConstraint(
        f"target_definition_hash ~ '{SHA256_CHECK}'",
        name="ck_registry_mapping_assertion_target_definition_hash",
    ),
    CheckConstraint("btrim(created_by) <> ''", name="ck_registry_mapping_assertion_created_by"),
    CheckConstraint(
        "(scope_kind = 'global' AND issuer_cik IS NULL) "
        "OR (scope_kind = 'issuer' AND issuer_cik IS NOT NULL)",
        name="ck_registry_mapping_assertion_scope_issuer",
    ),
    CheckConstraint(
        "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
        name="ck_registry_mapping_assertion_valid_range",
    ),
    CheckConstraint(
        "status <> 'accepted' OR ("
        "rationale IS NOT NULL AND btrim(rationale) <> '' "
        "AND jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) >= 1)",
        name="ck_registry_mapping_assertion_accepted",
    ),
    CheckConstraint(
        "status <> 'rejected' OR (rationale IS NOT NULL AND btrim(rationale) <> '')",
        name="ck_registry_mapping_assertion_rejected",
    ),
    CheckConstraint(
        "jsonb_typeof(evidence) = 'array'",
        name="ck_registry_mapping_assertion_evidence_array",
    ),
    Index("ix_registry_mapping_assertion_source_concept", "source_concept_id"),
    Index("ix_registry_mapping_assertion_target_metric", "target_metric_key"),
    Index("ix_registry_mapping_assertion_status", "status"),
    Index("ix_registry_mapping_assertion_issuer", "issuer_cik"),
    Index("ix_registry_mapping_assertion_supersedes", "supersedes_id"),
    Index("ix_registry_mapping_assertion_created_at", "created_at"),
    Index(
        "ix_registry_mapping_assertion_source_status",
        "source_concept_id",
        "status",
    ),
    Index(
        "ix_registry_mapping_assertion_metric_status",
        "target_metric_key",
        "status",
    ),
    Index(
        "ix_registry_mapping_assertion_issuer_concept",
        "issuer_cik",
        "source_concept_id",
    ),
    schema=REGISTRY_SCHEMA,
)

REGISTRY_TABLES = (
    registry_canonical_metric,
    registry_mapping_assertion,
)

assert metadata is not None
