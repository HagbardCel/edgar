"""Phase 2C registry schema: canonical metric mirror and mapping ledger.

Revision ID: 0002_registry
Revises: 0001_source_v2
Create Date: 2026-08-17

Self-contained DDL. Do not import live application metadata. Live Core tables
live in ``src/edgar/db/registry_schema.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_registry"
down_revision: str | Sequence[str] | None = "0001_source_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS registry"))
    op.create_table(
        "canonical_metric",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("period_type", sa.Text(), nullable=False),
        sa.Column("value_kind", sa.Text(), nullable=False),
        sa.Column("unit_dimension", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("includes", postgresql.JSONB(), nullable=False),
        sa.Column("excludes", postgresql.JSONB(), nullable=False),
        sa.Column("definition_hash", sa.Text(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name="canonical_metric_pkey"),
        sa.CheckConstraint("kind = 'reported'", name="ck_registry_canonical_metric_kind"),
        sa.CheckConstraint(
            "statement IN ('income_statement', 'balance_sheet', 'cash_flow', "
            "'per_share', 'shares')",
            name="ck_registry_canonical_metric_statement",
        ),
        sa.CheckConstraint(
            "period_type IN ('instant', 'duration')",
            name="ck_registry_canonical_metric_period_type",
        ),
        sa.CheckConstraint(
            "value_kind = 'numeric'", name="ck_registry_canonical_metric_value_kind"
        ),
        sa.CheckConstraint(
            "unit_dimension IN ('monetary', 'shares', 'monetary_per_share')",
            name="ck_registry_canonical_metric_unit_dimension",
        ),
        sa.CheckConstraint(
            "definition_hash ~ '^[0-9a-f]{64}$'",
            name="ck_registry_canonical_metric_definition_hash",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(includes) = 'array'",
            name="ck_registry_canonical_metric_includes_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(excludes) = 'array'",
            name="ck_registry_canonical_metric_excludes_array",
        ),
        schema="registry",
    )
    op.create_table(
        "mapping_assertion",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("supersedes_id", sa.BigInteger(), nullable=True),
        sa.Column("source_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_metric_key", sa.Text(), nullable=False),
        sa.Column("target_definition_hash", sa.Text(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("issuer_cik", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="mapping_assertion_pkey"),
        sa.UniqueConstraint("supersedes_id", name="uq_registry_mapping_assertion_supersedes_id"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["registry.mapping_assertion.id"],
            name="mapping_assertion_supersedes_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["source_concept_id"],
            ["source.concept.id"],
            name="mapping_assertion_source_concept_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["target_metric_key"],
            ["registry.canonical_metric.key"],
            name="mapping_assertion_target_metric_key_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["issuer_cik"],
            ["source.issuer.cik"],
            name="mapping_assertion_issuer_cik_fkey",
        ),
        sa.CheckConstraint(
            "relation IN ('exact', 'narrower', 'broader', 'related')",
            name="ck_registry_mapping_assertion_relation",
        ),
        sa.CheckConstraint(
            "scope_kind IN ('global', 'issuer')",
            name="ck_registry_mapping_assertion_scope_kind",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'accepted', 'rejected')",
            name="ck_registry_mapping_assertion_status",
        ),
        sa.CheckConstraint(
            "method IN ('curated', 'deterministic_rule', 'lexical_candidate', "
            "'structural_candidate', 'model_candidate', 'human_review')",
            name="ck_registry_mapping_assertion_method",
        ),
        sa.CheckConstraint(
            "target_definition_hash ~ '^[0-9a-f]{64}$'",
            name="ck_registry_mapping_assertion_target_definition_hash",
        ),
        sa.CheckConstraint(
            "btrim(created_by) <> ''", name="ck_registry_mapping_assertion_created_by"
        ),
        sa.CheckConstraint(
            "(scope_kind = 'global' AND issuer_cik IS NULL) "
            "OR (scope_kind = 'issuer' AND issuer_cik IS NOT NULL)",
            name="ck_registry_mapping_assertion_scope_issuer",
        ),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to",
            name="ck_registry_mapping_assertion_valid_range",
        ),
        sa.CheckConstraint(
            "status <> 'accepted' OR ("
            "rationale IS NOT NULL AND btrim(rationale) <> '' "
            "AND jsonb_typeof(evidence) = 'array' AND jsonb_array_length(evidence) >= 1)",
            name="ck_registry_mapping_assertion_accepted",
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR (rationale IS NOT NULL AND btrim(rationale) <> '')",
            name="ck_registry_mapping_assertion_rejected",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'array'",
            name="ck_registry_mapping_assertion_evidence_array",
        ),
        schema="registry",
    )
    op.create_index(
        "ix_registry_mapping_assertion_source_concept",
        "mapping_assertion",
        ["source_concept_id"],
        schema="registry",
    )
    op.create_index(
        "ix_registry_mapping_assertion_target_metric",
        "mapping_assertion",
        ["target_metric_key"],
        schema="registry",
    )
    op.create_index(
        "ix_registry_mapping_assertion_status",
        "mapping_assertion",
        ["status"],
        schema="registry",
    )
    op.create_index(
        "ix_registry_mapping_assertion_issuer",
        "mapping_assertion",
        ["issuer_cik"],
        schema="registry",
    )
    op.create_index(
        "ix_registry_mapping_assertion_supersedes",
        "mapping_assertion",
        ["supersedes_id"],
        schema="registry",
    )
    op.create_index(
        "ix_registry_mapping_assertion_created_at",
        "mapping_assertion",
        ["created_at"],
        schema="registry",
    )
    op.create_index(
        "ix_registry_mapping_assertion_source_status",
        "mapping_assertion",
        ["source_concept_id", "status"],
        schema="registry",
    )
    op.create_index(
        "ix_registry_mapping_assertion_metric_status",
        "mapping_assertion",
        ["target_metric_key", "status"],
        schema="registry",
    )
    op.create_index(
        "ix_registry_mapping_assertion_issuer_concept",
        "mapping_assertion",
        ["issuer_cik", "source_concept_id"],
        schema="registry",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_registry_mapping_assertion_issuer_concept",
        table_name="mapping_assertion",
        schema="registry",
    )
    op.drop_index(
        "ix_registry_mapping_assertion_metric_status",
        table_name="mapping_assertion",
        schema="registry",
    )
    op.drop_index(
        "ix_registry_mapping_assertion_source_status",
        table_name="mapping_assertion",
        schema="registry",
    )
    op.drop_index(
        "ix_registry_mapping_assertion_created_at",
        table_name="mapping_assertion",
        schema="registry",
    )
    op.drop_index(
        "ix_registry_mapping_assertion_supersedes",
        table_name="mapping_assertion",
        schema="registry",
    )
    op.drop_index(
        "ix_registry_mapping_assertion_issuer",
        table_name="mapping_assertion",
        schema="registry",
    )
    op.drop_index(
        "ix_registry_mapping_assertion_status",
        table_name="mapping_assertion",
        schema="registry",
    )
    op.drop_index(
        "ix_registry_mapping_assertion_target_metric",
        table_name="mapping_assertion",
        schema="registry",
    )
    op.drop_index(
        "ix_registry_mapping_assertion_source_concept",
        table_name="mapping_assertion",
        schema="registry",
    )
    op.drop_table("mapping_assertion", schema="registry")
    op.drop_table("canonical_metric", schema="registry")
    op.execute(sa.text("DROP SCHEMA IF EXISTS registry"))
