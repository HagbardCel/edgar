"""XBRL semantic projection schema.

Revision ID: 0002_semantic_projection
Revises: 0001_catalog
Create Date: 2026-08-08

Explicit historical migration (does not call metadata.create_all).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_semantic_projection"
down_revision: str | Sequence[str] | None = "0001_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHA256_CHECK = r"^[0-9a-f]{64}$"


def upgrade() -> None:
    op.create_table(
        "semantic_projection",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("xbrl_report_input_id", sa.BigInteger(), nullable=False),
        sa.Column("projection_version", sa.Text(), nullable=False),
        sa.Column("arelle_version", sa.Text(), nullable=False),
        sa.Column("semantic_config_fingerprint", sa.Text(), nullable=False),
        sa.Column("semantic_config", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"semantic_config_fingerprint ~ '{SHA256_CHECK}'",
            name="ck_semantic_projection_config_fingerprint_hex",
        ),
        sa.CheckConstraint(
            "status IN ('complete', 'incomplete')",
            name="ck_semantic_projection_status",
        ),
        sa.ForeignKeyConstraint(
            ["xbrl_report_input_id"],
            ["xbrl_report_input.id"],
            name="semantic_projection_xbrl_report_input_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="semantic_projection_pkey"),
        sa.UniqueConstraint(
            "xbrl_report_input_id",
            "projection_version",
            "arelle_version",
            "semantic_config_fingerprint",
            name="uq_semantic_projection_identity",
        ),
    )
    op.create_table(
        "semantic_projection_attempt",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("xbrl_report_input_id", sa.BigInteger(), nullable=False),
        sa.Column("projection_version", sa.Text(), nullable=False),
        sa.Column("semantic_config_fingerprint", sa.Text(), nullable=False),
        sa.Column("semantic_config", postgresql.JSONB(), nullable=False),
        sa.Column("arelle_version", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("semantic_projection_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            f"semantic_config_fingerprint ~ '{SHA256_CHECK}'",
            name="ck_semantic_projection_attempt_config_fingerprint_hex",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND semantic_projection_id IS NOT NULL)"
            " OR (status = 'failed' AND semantic_projection_id IS NULL)",
            name="ck_semantic_projection_attempt_status_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_projection_id"],
            ["semantic_projection.id"],
            name="semantic_projection_attempt_semantic_projection_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["xbrl_report_input_id"],
            ["xbrl_report_input.id"],
            name="semantic_projection_attempt_xbrl_report_input_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="semantic_projection_attempt_pkey"),
    )
    op.create_table(
        "semantic_issue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("semantic_projection_id", sa.BigInteger(), nullable=True),
        sa.Column("semantic_projection_attempt_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "context",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(semantic_projection_id IS NOT NULL AND semantic_projection_attempt_id IS NULL)"
            " OR (semantic_projection_id IS NULL AND semantic_projection_attempt_id IS NOT NULL)",
            name="ck_semantic_issue_single_owner",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_projection_attempt_id"],
            ["semantic_projection_attempt.id"],
            name="semantic_issue_semantic_projection_attempt_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_projection_id"],
            ["semantic_projection.id"],
            name="semantic_issue_semantic_projection_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="semantic_issue_pkey"),
    )
    op.create_table(
        "concept_identity",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("namespace_uri", sa.Text(), nullable=False),
        sa.Column("local_name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="concept_identity_pkey"),
        sa.UniqueConstraint("namespace_uri", "local_name", name="uq_concept_identity_qname"),
    )
    op.create_table(
        "concept_declaration",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("semantic_projection_id", sa.BigInteger(), nullable=False),
        sa.Column("concept_identity_id", sa.BigInteger(), nullable=False),
        sa.Column("type_namespace_uri", sa.Text(), nullable=True),
        sa.Column("type_local_name", sa.Text(), nullable=True),
        sa.Column("substitution_group_namespace_uri", sa.Text(), nullable=True),
        sa.Column("substitution_group_local_name", sa.Text(), nullable=True),
        sa.Column("period_type", sa.Text(), nullable=True),
        sa.Column("balance", sa.Text(), nullable=True),
        sa.Column("is_abstract", sa.Boolean(), nullable=True),
        sa.Column("is_nillable", sa.Boolean(), nullable=True),
        sa.Column("source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("source_locator_value", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["concept_identity_id"],
            ["concept_identity.id"],
            name="concept_declaration_concept_identity_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_projection_id"],
            ["semantic_projection.id"],
            name="concept_declaration_semantic_projection_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="concept_declaration_source_bundle_uri_binding_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="concept_declaration_pkey"),
        sa.UniqueConstraint(
            "semantic_projection_id",
            "concept_identity_id",
            name="uq_concept_declaration_projection_concept",
        ),
    )
    op.create_table(
        "concept_label",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("semantic_projection_id", sa.BigInteger(), nullable=False),
        sa.Column("concept_declaration_id", sa.BigInteger(), nullable=False),
        sa.Column("link_role_uri", sa.Text(), nullable=False),
        sa.Column("arcrole_uri", sa.Text(), nullable=False),
        sa.Column("resource_role_uri", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("order_value", sa.Numeric(), nullable=True),
        sa.Column("resource_source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("resource_source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("resource_source_locator_value", postgresql.JSONB(), nullable=False),
        sa.Column("arc_source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("arc_source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("arc_source_locator_value", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["arc_source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="concept_label_arc_source_bundle_uri_binding_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["concept_declaration_id"],
            ["concept_declaration.id"],
            name="concept_label_concept_declaration_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["resource_source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="concept_label_resource_source_bundle_uri_binding_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_projection_id"],
            ["semantic_projection.id"],
            name="concept_label_semantic_projection_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="concept_label_pkey"),
    )
    op.create_index(
        "ix_concept_label_declaration_role_language",
        "concept_label",
        ["concept_declaration_id", "resource_role_uri", "language"],
    )
    op.create_table(
        "concept_reference",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("semantic_projection_id", sa.BigInteger(), nullable=False),
        sa.Column("concept_declaration_id", sa.BigInteger(), nullable=False),
        sa.Column("link_role_uri", sa.Text(), nullable=False),
        sa.Column("arcrole_uri", sa.Text(), nullable=False),
        sa.Column("resource_role_uri", sa.Text(), nullable=True),
        sa.Column(
            "reference_parts",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("order_value", sa.Numeric(), nullable=True),
        sa.Column("resource_source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("resource_source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("resource_source_locator_value", postgresql.JSONB(), nullable=False),
        sa.Column("arc_source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("arc_source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("arc_source_locator_value", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["arc_source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="concept_reference_arc_source_bundle_uri_binding_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["concept_declaration_id"],
            ["concept_declaration.id"],
            name="concept_reference_concept_declaration_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["resource_source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="concept_reference_resource_source_bundle_uri_binding_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_projection_id"],
            ["semantic_projection.id"],
            name="concept_reference_semantic_projection_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="concept_reference_pkey"),
    )
    op.create_index(
        "ix_concept_reference_declaration_role",
        "concept_reference",
        ["concept_declaration_id", "resource_role_uri"],
    )
    op.create_table(
        "role_declaration",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("semantic_projection_id", sa.BigInteger(), nullable=False),
        sa.Column("role_uri", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column(
            "used_on",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("source_locator_value", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["semantic_projection_id"],
            ["semantic_projection.id"],
            name="role_declaration_semantic_projection_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="role_declaration_source_bundle_uri_binding_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="role_declaration_pkey"),
    )
    op.create_index(
        "ix_role_declaration_projection_role",
        "role_declaration",
        ["semantic_projection_id", "role_uri"],
    )
    op.create_table(
        "arcrole_declaration",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("semantic_projection_id", sa.BigInteger(), nullable=False),
        sa.Column("arcrole_uri", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column(
            "used_on",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("cycles_allowed", sa.Text(), nullable=True),
        sa.Column("source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("source_locator_value", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["semantic_projection_id"],
            ["semantic_projection.id"],
            name="arcrole_declaration_semantic_projection_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="arcrole_declaration_source_bundle_uri_binding_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="arcrole_declaration_pkey"),
    )
    op.create_index(
        "ix_arcrole_declaration_projection_arcrole",
        "arcrole_declaration",
        ["semantic_projection_id", "arcrole_uri"],
    )
    op.create_table(
        "xbrl_context",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("semantic_projection_id", sa.BigInteger(), nullable=False),
        sa.Column("source_context_id", sa.Text(), nullable=False),
        sa.Column("entity_scheme", sa.Text(), nullable=False),
        sa.Column("entity_identifier", sa.Text(), nullable=False),
        sa.Column("period_kind", sa.Text(), nullable=False),
        sa.Column("instant_date", sa.Date(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("source_locator_value", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "period_kind IN ('instant', 'duration', 'forever')",
            name="ck_xbrl_context_period_kind",
        ),
        sa.CheckConstraint(
            "(period_kind = 'instant' AND instant_date IS NOT NULL"
            " AND start_date IS NULL AND end_date IS NULL)"
            " OR (period_kind = 'duration' AND instant_date IS NULL"
            " AND start_date IS NOT NULL AND end_date IS NOT NULL)"
            " OR (period_kind = 'forever' AND instant_date IS NULL"
            " AND start_date IS NULL AND end_date IS NULL)",
            name="ck_xbrl_context_period_fields",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_projection_id"],
            ["semantic_projection.id"],
            name="xbrl_context_semantic_projection_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="xbrl_context_source_bundle_uri_binding_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="xbrl_context_pkey"),
    )
    op.create_index(
        "ix_xbrl_context_projection_source_id",
        "xbrl_context",
        ["semantic_projection_id", "source_context_id"],
    )
    op.create_table(
        "xbrl_context_dimension",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("context_id", sa.BigInteger(), nullable=False),
        sa.Column("dimension_concept_declaration_id", sa.BigInteger(), nullable=False),
        sa.Column("context_element", sa.Text(), nullable=False),
        sa.Column("member_kind", sa.Text(), nullable=False),
        sa.Column("member_concept_declaration_id", sa.BigInteger(), nullable=True),
        sa.Column("typed_member_xml", sa.Text(), nullable=True),
        sa.Column("typed_member_hash", sa.Text(), nullable=True),
        sa.Column("source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("source_locator_value", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "context_element IN ('segment', 'scenario')",
            name="ck_xbrl_context_dimension_context_element",
        ),
        sa.CheckConstraint(
            "member_kind IN ('explicit', 'typed')",
            name="ck_xbrl_context_dimension_member_kind",
        ),
        sa.CheckConstraint(
            "(member_kind = 'explicit' AND member_concept_declaration_id IS NOT NULL"
            " AND typed_member_xml IS NULL)"
            " OR (member_kind = 'typed' AND member_concept_declaration_id IS NULL"
            " AND typed_member_xml IS NOT NULL)",
            name="ck_xbrl_context_dimension_member_exclusive",
        ),
        sa.ForeignKeyConstraint(
            ["context_id"],
            ["xbrl_context.id"],
            name="xbrl_context_dimension_context_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["dimension_concept_declaration_id"],
            ["concept_declaration.id"],
            name="xbrl_context_dimension_dimension_concept_declaration_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["member_concept_declaration_id"],
            ["concept_declaration.id"],
            name="xbrl_context_dimension_member_concept_declaration_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="xbrl_context_dimension_source_bundle_uri_binding_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="xbrl_context_dimension_pkey"),
    )
    op.create_index(
        "ix_xbrl_context_dimension_dimension",
        "xbrl_context_dimension",
        ["dimension_concept_declaration_id"],
    )
    op.create_table(
        "xbrl_unit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("semantic_projection_id", sa.BigInteger(), nullable=False),
        sa.Column("source_unit_id", sa.Text(), nullable=False),
        sa.Column("source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("source_locator_value", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["semantic_projection_id"],
            ["semantic_projection.id"],
            name="xbrl_unit_semantic_projection_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="xbrl_unit_source_bundle_uri_binding_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="xbrl_unit_pkey"),
    )
    op.create_index(
        "ix_xbrl_unit_projection_source_id",
        "xbrl_unit",
        ["semantic_projection_id", "source_unit_id"],
    )
    op.create_table(
        "xbrl_unit_measure",
        sa.Column("unit_id", sa.BigInteger(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("namespace_uri", sa.Text(), nullable=True),
        sa.Column("local_name", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "side IN ('numerator', 'denominator')",
            name="ck_xbrl_unit_measure_side",
        ),
        sa.CheckConstraint("ordinal >= 1", name="ck_xbrl_unit_measure_ordinal_positive"),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["xbrl_unit.id"],
            name="xbrl_unit_measure_unit_id_fkey",
        ),
        sa.PrimaryKeyConstraint("unit_id", "side", "ordinal", name="pk_xbrl_unit_measure"),
    )
    op.create_table(
        "xbrl_fact",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("semantic_projection_id", sa.BigInteger(), nullable=False),
        sa.Column("concept_declaration_id", sa.BigInteger(), nullable=False),
        sa.Column("context_id", sa.BigInteger(), nullable=False),
        sa.Column("unit_id", sa.BigInteger(), nullable=True),
        sa.Column("source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("source_locator_value", postgresql.JSONB(), nullable=False),
        sa.Column("value_status", sa.Text(), nullable=False),
        sa.Column("raw_lexical_value", sa.Text(), nullable=True),
        sa.Column("resolved_value_kind", sa.Text(), nullable=True),
        sa.Column("resolved_value_text", sa.Text(), nullable=True),
        sa.Column("resolved_numeric", sa.Numeric(), nullable=True),
        sa.Column("is_nil", sa.Boolean(), nullable=False),
        sa.Column("reported_decimals", sa.Text(), nullable=True),
        sa.Column("reported_precision", sa.Text(), nullable=True),
        sa.Column("xml_lang", sa.Text(), nullable=True),
        sa.Column("format_namespace_uri", sa.Text(), nullable=True),
        sa.Column("format_local_name", sa.Text(), nullable=True),
        sa.Column("scale", sa.Integer(), nullable=True),
        sa.Column("sign", sa.Text(), nullable=True),
        sa.Column("escape", sa.Boolean(), nullable=True),
        sa.Column("continuation_provenance", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "value_status IN ('valid', 'nil', 'invalid', 'unresolved')",
            name="ck_xbrl_fact_value_status",
        ),
        sa.CheckConstraint(
            "resolved_value_kind IS NULL OR resolved_value_kind IN "
            "('numeric', 'text', 'boolean', 'date', 'datetime', 'time', 'qname')",
            name="ck_xbrl_fact_resolved_value_kind",
        ),
        sa.ForeignKeyConstraint(
            ["concept_declaration_id"],
            ["concept_declaration.id"],
            name="xbrl_fact_concept_declaration_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["context_id"],
            ["xbrl_context.id"],
            name="xbrl_fact_context_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_projection_id"],
            ["semantic_projection.id"],
            name="xbrl_fact_semantic_projection_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="xbrl_fact_source_bundle_uri_binding_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["xbrl_unit.id"],
            name="xbrl_fact_unit_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="xbrl_fact_pkey"),
    )
    op.create_index("ix_xbrl_fact_concept_declaration", "xbrl_fact", ["concept_declaration_id"])
    op.create_index("ix_xbrl_fact_context", "xbrl_fact", ["context_id"])
    op.create_table(
        "xbrl_relationship",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("semantic_projection_id", sa.BigInteger(), nullable=False),
        sa.Column("network_type", sa.Text(), nullable=False),
        sa.Column("link_role_uri", sa.Text(), nullable=False),
        sa.Column("arcrole_uri", sa.Text(), nullable=False),
        sa.Column("source_concept_declaration_id", sa.BigInteger(), nullable=False),
        sa.Column("target_concept_declaration_id", sa.BigInteger(), nullable=False),
        sa.Column("order_value", sa.Numeric(), nullable=True),
        sa.Column("weight", sa.Numeric(), nullable=True),
        sa.Column("preferred_label_role", sa.Text(), nullable=True),
        sa.Column("target_role_uri", sa.Text(), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=True),
        sa.Column("usable", sa.Boolean(), nullable=True),
        sa.Column("context_element", sa.Text(), nullable=True),
        sa.Column("source_bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.Column("source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("source_locator_value", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "context_element IS NULL OR context_element IN ('segment', 'scenario')",
            name="ck_xbrl_relationship_context_element",
        ),
        sa.CheckConstraint(
            "network_type IN ('presentation', 'calculation', 'definition')",
            name="ck_xbrl_relationship_network_type",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_projection_id"],
            ["semantic_projection.id"],
            name="xbrl_relationship_semantic_projection_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["source_bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="xbrl_relationship_source_bundle_uri_binding_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["source_concept_declaration_id"],
            ["concept_declaration.id"],
            name="xbrl_relationship_source_concept_declaration_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["target_concept_declaration_id"],
            ["concept_declaration.id"],
            name="xbrl_relationship_target_concept_declaration_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="xbrl_relationship_pkey"),
    )
    op.create_index(
        "ix_xbrl_relationship_projection_network_role",
        "xbrl_relationship",
        ["semantic_projection_id", "network_type", "link_role_uri"],
    )


def downgrade() -> None:
    op.drop_index("ix_xbrl_relationship_projection_network_role", table_name="xbrl_relationship")
    op.drop_table("xbrl_relationship")
    op.drop_index("ix_xbrl_fact_context", table_name="xbrl_fact")
    op.drop_index("ix_xbrl_fact_concept_declaration", table_name="xbrl_fact")
    op.drop_table("xbrl_fact")
    op.drop_table("xbrl_unit_measure")
    op.drop_index("ix_xbrl_unit_projection_source_id", table_name="xbrl_unit")
    op.drop_table("xbrl_unit")
    op.drop_index("ix_xbrl_context_dimension_dimension", table_name="xbrl_context_dimension")
    op.drop_table("xbrl_context_dimension")
    op.drop_index("ix_xbrl_context_projection_source_id", table_name="xbrl_context")
    op.drop_table("xbrl_context")
    op.drop_index("ix_arcrole_declaration_projection_arcrole", table_name="arcrole_declaration")
    op.drop_table("arcrole_declaration")
    op.drop_index("ix_role_declaration_projection_role", table_name="role_declaration")
    op.drop_table("role_declaration")
    op.drop_index("ix_concept_reference_declaration_role", table_name="concept_reference")
    op.drop_table("concept_reference")
    op.drop_index("ix_concept_label_declaration_role_language", table_name="concept_label")
    op.drop_table("concept_label")
    op.drop_table("concept_declaration")
    op.drop_table("concept_identity")
    op.drop_table("semantic_issue")
    op.drop_table("semantic_projection_attempt")
    op.drop_table("semantic_projection")
