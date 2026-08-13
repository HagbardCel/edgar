"""Metric ontology and curated mapping registry (Phase 2A).

Revision ID: 0004_metric_ontology
Revises: 0003_document_projection
Create Date: 2026-08-13

Explicit historical migration (does not call metadata.create_all).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_metric_ontology"
down_revision: str | Sequence[str] | None = "0003_document_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHA256_CHECK = r"^[0-9a-f]{64}$"

_RELATIONSHIP_TYPES = (
    "equivalent",
    "issuer_equivalent",
    "narrower_than",
    "broader_than",
    "component_of",
    "derived_equivalent",
    "presentation_alias",
    "proxy_for",
    "incompatible",
    "unresolved",
)

_SCOPE_KINDS = ("global", "issuer", "issuer_period", "filing")
_CONFIDENCE_TIERS = ("high", "medium", "low")


def upgrade() -> None:
    op.create_table(
        "metric_family",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("parent_family_id", sa.BigInteger(), nullable=True),
        sa.Column("family_hash", sa.Text(), nullable=False),
        sa.CheckConstraint(
            f"family_hash ~ '{SHA256_CHECK}'",
            name="ck_metric_family_family_hash_hex",
        ),
        sa.ForeignKeyConstraint(
            ["parent_family_id"],
            ["metric_family.id"],
            name="metric_family_parent_family_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="metric_family_pkey"),
        sa.UniqueConstraint("code", name="uq_metric_family_code"),
    )
    op.create_table(
        "metric_definition",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("metric_code", sa.Text(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("definition_schema_version", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("economic_definition", sa.Text(), nullable=False),
        sa.Column("accounting_basis", sa.Text(), nullable=False),
        sa.Column("period_type", sa.Text(), nullable=False),
        sa.Column("value_kind", sa.Text(), nullable=False),
        sa.Column("unit_kind", sa.Text(), nullable=False),
        sa.Column("entity_scope", sa.Text(), nullable=False),
        sa.Column("sign_convention", sa.Text(), nullable=False),
        sa.Column("constraints", postgresql.JSONB(), nullable=False),
        sa.Column("definition_hash", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "definition_version > 0",
            name="ck_metric_definition_version_positive",
        ),
        sa.CheckConstraint(
            "definition_schema_version > 0",
            name="ck_metric_definition_schema_version_positive",
        ),
        sa.CheckConstraint(
            "period_type IN ('instant', 'duration')",
            name="ck_metric_definition_period_type",
        ),
        sa.CheckConstraint(
            f"definition_hash ~ '{SHA256_CHECK}'",
            name="ck_metric_definition_definition_hash_hex",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["metric_family.id"],
            name="metric_definition_family_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="metric_definition_pkey"),
        sa.UniqueConstraint(
            "metric_code",
            "definition_version",
            name="uq_metric_definition_code_version",
        ),
    )
    op.create_table(
        "metric_mapping_rule",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("rule_key", sa.Text(), nullable=False),
        sa.Column("rule_schema_version", sa.Integer(), nullable=False),
        sa.Column("source_concept_identity_id", sa.BigInteger(), nullable=False),
        sa.Column("target_metric_definition_id", sa.BigInteger(), nullable=False),
        sa.Column("relationship_type", sa.Text(), nullable=False),
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("scope", postgresql.JSONB(), nullable=False),
        sa.Column("confidence_tier", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_citations", postgresql.JSONB(), nullable=False),
        sa.Column("reviewed_by", sa.Text(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_rule_id", sa.BigInteger(), nullable=True),
        sa.Column("rule_hash", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "rule_schema_version > 0",
            name="ck_metric_mapping_rule_schema_version_positive",
        ),
        sa.CheckConstraint(
            "relationship_type IN ("
            + ", ".join(f"'{value}'" for value in _RELATIONSHIP_TYPES)
            + ")",
            name="ck_metric_mapping_rule_relationship_type",
        ),
        sa.CheckConstraint(
            "scope_kind IN (" + ", ".join(f"'{value}'" for value in _SCOPE_KINDS) + ")",
            name="ck_metric_mapping_rule_scope_kind",
        ),
        sa.CheckConstraint(
            "confidence_tier IN (" + ", ".join(f"'{value}'" for value in _CONFIDENCE_TIERS) + ")",
            name="ck_metric_mapping_rule_confidence_tier",
        ),
        sa.CheckConstraint(
            "scope->>'kind' = scope_kind",
            name="ck_metric_mapping_rule_scope_kind_matches",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scope) = 'object'",
            name="ck_metric_mapping_rule_scope_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_snapshot) = 'object'",
            name="ck_metric_mapping_rule_evidence_snapshot_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_citations) = 'array'",
            name="ck_metric_mapping_rule_evidence_citations_array",
        ),
        sa.CheckConstraint(
            f"rule_hash ~ '{SHA256_CHECK}'",
            name="ck_metric_mapping_rule_rule_hash_hex",
        ),
        sa.CheckConstraint(
            "supersedes_rule_id IS NULL OR supersedes_rule_id <> id",
            name="ck_metric_mapping_rule_supersedes_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["source_concept_identity_id"],
            ["concept_identity.id"],
            name="metric_mapping_rule_source_concept_identity_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["target_metric_definition_id"],
            ["metric_definition.id"],
            name="metric_mapping_rule_target_metric_definition_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_rule_id"],
            ["metric_mapping_rule.id"],
            name="metric_mapping_rule_supersedes_rule_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="metric_mapping_rule_pkey"),
        sa.UniqueConstraint("rule_key", name="uq_metric_mapping_rule_rule_key"),
    )
    op.create_table(
        "semantic_registry_revision",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("registry_hash", sa.Text(), nullable=False),
        sa.Column("registry_schema_version", sa.Integer(), nullable=False),
        sa.Column("families_file_hash", sa.Text(), nullable=False),
        sa.Column("definitions_file_hash", sa.Text(), nullable=False),
        sa.Column("rules_file_hash", sa.Text(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "registry_schema_version > 0",
            name="ck_semantic_registry_revision_schema_version_positive",
        ),
        sa.CheckConstraint(
            f"registry_hash ~ '{SHA256_CHECK}'",
            name="ck_semantic_registry_revision_registry_hash_hex",
        ),
        sa.CheckConstraint(
            f"families_file_hash ~ '{SHA256_CHECK}'",
            name="ck_semantic_registry_revision_families_file_hash_hex",
        ),
        sa.CheckConstraint(
            f"definitions_file_hash ~ '{SHA256_CHECK}'",
            name="ck_semantic_registry_revision_definitions_file_hash_hex",
        ),
        sa.CheckConstraint(
            f"rules_file_hash ~ '{SHA256_CHECK}'",
            name="ck_semantic_registry_revision_rules_file_hash_hex",
        ),
        sa.PrimaryKeyConstraint("id", name="semantic_registry_revision_pkey"),
    )
    op.create_index(
        "ix_semantic_registry_revision_registry_hash",
        "semantic_registry_revision",
        ["registry_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_semantic_registry_revision_registry_hash",
        table_name="semantic_registry_revision",
    )
    op.drop_table("semantic_registry_revision")
    op.drop_table("metric_mapping_rule")
    op.drop_table("metric_definition")
    op.drop_table("metric_family")
