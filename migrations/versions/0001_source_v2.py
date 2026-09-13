"""V2 Alembic baseline: frozen self-contained ``source.*`` DDL.

Revision ID: 0001_source_v2
Revises:
Create Date: 2026-08-16

Fresh ``alembic upgrade head`` creates only ``source.*`` (no Phase-1
projection/catalog tables). Existing Phase-1 databases must be recreated;
do not upgrade from the deleted 0001–0004 lineage.

This revision must not import application metadata. Live Core tables live in
``src/edgar/db/source_schema.py``; later schema edits require a new revision
and must not change the historical meaning of ``0001_source_v2``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_source_v2"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS source"))
    op.create_table(
        "issuer",
        sa.Column("cik", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("cik", name="issuer_pkey"),
        schema="source",
    )
    op.create_table(
        "filing",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("issuer_cik", sa.Text(), nullable=False),
        sa.Column("accession", sa.Text(), nullable=False),
        sa.Column("form", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_period_end", sa.Date(), nullable=True),
        sa.Column("primary_document", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["issuer_cik"], ["source.issuer.cik"], name="filing_issuer_cik_fkey"
        ),
        sa.UniqueConstraint("accession", name="filing_accession_key"),
        sa.PrimaryKeyConstraint("id", name="filing_pkey"),
        schema="source",
    )
    op.create_table(
        "document",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_id", sa.BigInteger(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("document_kind", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("filing_id", "relative_path", name="uq_source_document_filing_path"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_document_sha256_hex"),
        sa.CheckConstraint("byte_size >= 0", name="ck_source_document_byte_size_nonneg"),
        sa.PrimaryKeyConstraint("id", name="document_pkey"),
        sa.ForeignKeyConstraint(
            ["filing_id"], ["source.filing.id"], name="document_filing_id_fkey"
        ),
        schema="source",
    )
    op.create_table(
        "concept",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("namespace_uri", sa.Text(), nullable=False),
        sa.Column("local_name", sa.Text(), nullable=False),
        sa.UniqueConstraint("namespace_uri", "local_name", name="uq_source_concept_qname"),
        sa.PrimaryKeyConstraint("id", name="concept_pkey"),
        schema="source",
    )
    op.create_table(
        "xbrl_report",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_id", sa.BigInteger(), nullable=False),
        sa.Column("report_key", sa.Text(), nullable=False),
        sa.Column("report_input", postgresql.JSONB(), nullable=False),
        sa.Column("entry_document_id", sa.BigInteger(), nullable=True),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("arelle_version", sa.Text(), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arelle_item_fact_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("report_key ~ '^[0-9a-f]{64}$'", name="ck_source_xbrl_report_key_hex"),
        sa.PrimaryKeyConstraint("id", name="xbrl_report_pkey"),
        sa.ForeignKeyConstraint(
            ["filing_id"],
            ["source.filing.id"],
            name="xbrl_report_filing_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "arelle_item_fact_count >= 0", name="ck_source_xbrl_report_fact_count_nonneg"
        ),
        sa.ForeignKeyConstraint(
            ["entry_document_id"], ["source.document.id"], name="xbrl_report_entry_document_id_fkey"
        ),
        sa.UniqueConstraint("filing_id", "report_key", name="uq_source_xbrl_report_filing_key"),
        schema="source",
    )
    op.create_table(
        "concept_declaration",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("data_type", sa.Text(), nullable=True),
        sa.Column("period_type", sa.Text(), nullable=True),
        sa.Column("balance", sa.Text(), nullable=True),
        sa.Column("abstract", sa.Boolean(), nullable=True),
        sa.Column("nillable", sa.Boolean(), nullable=True),
        sa.Column("substitution_group", sa.Text(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_locator", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["source.xbrl_report.id"],
            name="concept_declaration_report_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["source.concept.id"], name="concept_declaration_concept_id_fkey"
        ),
        sa.CheckConstraint(
            "balance IS NULL OR balance IN ('debit', 'credit')",
            name="ck_source_concept_declaration_balance",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source.document.id"],
            name="concept_declaration_source_document_id_fkey",
        ),
        sa.UniqueConstraint(
            "report_id", "concept_id", name="uq_source_concept_declaration_report_concept"
        ),
        sa.CheckConstraint(
            "period_type IS NULL OR period_type IN ('instant', 'duration')",
            name="ck_source_concept_declaration_period_type",
        ),
        sa.PrimaryKeyConstraint("id", name="concept_declaration_pkey"),
        schema="source",
    )
    op.create_table(
        "concept_label",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("link_role_uri", sa.Text(), nullable=False),
        sa.Column("arcrole_uri", sa.Text(), nullable=False),
        sa.Column("resource_role_uri", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("order_value", sa.Numeric(), nullable=True),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_locator", postgresql.JSONB(), nullable=True),
        sa.Column("arc_source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("arc_locator", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["arc_source_document_id"],
            ["source.document.id"],
            name="concept_label_arc_source_document_id_fkey",
        ),
        sa.UniqueConstraint(
            "report_id", "source_order", name="uq_source_concept_label_report_order"
        ),
        sa.PrimaryKeyConstraint("id", name="concept_label_pkey"),
        sa.CheckConstraint("source_order >= 0", name="ck_source_concept_label_source_order_nonneg"),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["source.xbrl_report.id"],
            name="concept_label_report_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["source.concept.id"], name="concept_label_concept_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source.document.id"],
            name="concept_label_source_document_id_fkey",
        ),
        schema="source",
    )
    op.create_table(
        "concept_reference",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("link_role_uri", sa.Text(), nullable=False),
        sa.Column("arcrole_uri", sa.Text(), nullable=False),
        sa.Column("resource_role_uri", sa.Text(), nullable=True),
        sa.Column("order_value", sa.Numeric(), nullable=True),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column(
            "reference_parts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_locator", postgresql.JSONB(), nullable=True),
        sa.Column("arc_source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("arc_locator", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source.document.id"],
            name="concept_reference_source_document_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["arc_source_document_id"],
            ["source.document.id"],
            name="concept_reference_arc_source_document_id_fkey",
        ),
        sa.UniqueConstraint(
            "report_id", "source_order", name="uq_source_concept_reference_report_order"
        ),
        sa.PrimaryKeyConstraint("id", name="concept_reference_pkey"),
        sa.CheckConstraint(
            "source_order >= 0", name="ck_source_concept_reference_source_order_nonneg"
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["source.xbrl_report.id"],
            name="concept_reference_report_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["source.concept.id"], name="concept_reference_concept_id_fkey"
        ),
        schema="source",
    )
    op.create_table(
        "context",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("source_context_id", sa.Text(), nullable=False),
        sa.Column("entity_scheme", sa.Text(), nullable=False),
        sa.Column("entity_identifier", sa.Text(), nullable=False),
        sa.Column("period_kind", sa.Text(), nullable=False),
        sa.Column("instant_lexical", sa.Text(), nullable=True),
        sa.Column("start_lexical", sa.Text(), nullable=True),
        sa.Column("end_lexical", sa.Text(), nullable=True),
        sa.Column("instant_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_locator", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["source.xbrl_report.id"],
            name="context_report_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "("
            "period_kind = 'instant' AND instant_lexical IS NOT NULL"
            " AND start_lexical IS NULL AND end_lexical IS NULL"
            " AND start_at IS NULL AND end_at IS NULL"
            ") OR ("
            "period_kind = 'duration' AND instant_lexical IS NULL"
            " AND start_lexical IS NOT NULL AND end_lexical IS NOT NULL"
            " AND instant_at IS NULL"
            ") OR ("
            "period_kind = 'forever' AND instant_lexical IS NULL"
            " AND start_lexical IS NULL AND end_lexical IS NULL"
            " AND instant_at IS NULL AND start_at IS NULL AND end_at IS NULL"
            ")",
            name="ck_source_context_period_fields",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source.document.id"], name="context_source_document_id_fkey"
        ),
        sa.CheckConstraint(
            "(instant_at IS NULL OR instant_lexical IS NOT NULL)"
            " AND (start_at IS NULL OR start_lexical IS NOT NULL)"
            " AND (end_at IS NULL OR end_lexical IS NOT NULL)",
            name="ck_source_context_at_requires_lexical",
        ),
        sa.UniqueConstraint(
            "report_id", "source_context_id", name="uq_source_context_report_source_id"
        ),
        sa.CheckConstraint(
            "period_kind IN ('instant', 'duration', 'forever')",
            name="ck_source_context_period_kind",
        ),
        sa.PrimaryKeyConstraint("id", name="context_pkey"),
        schema="source",
    )
    op.create_table(
        "context_dimension",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("context_id", sa.BigInteger(), nullable=False),
        sa.Column("dimension_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_element", sa.Text(), nullable=False),
        sa.Column("member_kind", sa.Text(), nullable=False),
        sa.Column("explicit_member_concept_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("typed_member", postgresql.JSONB(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_locator", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "member_kind IN ('explicit', 'typed')", name="ck_source_context_dimension_member_kind"
        ),
        sa.ForeignKeyConstraint(
            ["explicit_member_concept_id"],
            ["source.concept.id"],
            name="context_dimension_explicit_member_concept_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source.document.id"],
            name="context_dimension_source_document_id_fkey",
        ),
        sa.CheckConstraint(
            "(member_kind = 'explicit' AND explicit_member_concept_id IS NOT NULL"
            " AND typed_member IS NULL) OR ("
            "member_kind = 'typed' AND explicit_member_concept_id IS NULL"
            " AND typed_member IS NOT NULL)",
            name="ck_source_context_dimension_member_exclusive",
        ),
        sa.CheckConstraint(
            "context_element IN ('segment', 'scenario')",
            name="ck_source_context_dimension_context_element",
        ),
        sa.PrimaryKeyConstraint("id", name="context_dimension_pkey"),
        sa.ForeignKeyConstraint(
            ["context_id"],
            ["source.context.id"],
            name="context_dimension_context_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dimension_concept_id"],
            ["source.concept.id"],
            name="context_dimension_dimension_concept_id_fkey",
        ),
        schema="source",
    )
    op.create_table(
        "unit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("source_unit_id", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_locator", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="unit_pkey"),
        sa.ForeignKeyConstraint(
            ["report_id"], ["source.xbrl_report.id"], name="unit_report_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source.document.id"], name="unit_source_document_id_fkey"
        ),
        sa.UniqueConstraint("report_id", "source_unit_id", name="uq_source_unit_report_source_id"),
        schema="source",
    )
    op.create_table(
        "unit_measure",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("unit_id", sa.BigInteger(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("measure_namespace_uri", sa.Text(), nullable=True),
        sa.Column("measure_local_name", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "side IN ('numerator', 'denominator')", name="ck_source_unit_measure_side"
        ),
        sa.PrimaryKeyConstraint("id", name="unit_measure_pkey"),
        sa.CheckConstraint("ordinal >= 1", name="ck_source_unit_measure_ordinal_positive"),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["source.unit.id"], name="unit_measure_unit_id_fkey", ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "unit_id", "side", "ordinal", name="uq_source_unit_measure_side_ordinal"
        ),
        schema="source",
    )
    op.create_table(
        "fact",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_id", sa.BigInteger(), nullable=False),
        sa.Column("unit_id", sa.BigInteger(), nullable=True),
        sa.Column("value_status", sa.Text(), nullable=False),
        sa.Column("raw_lexical_value", sa.Text(), nullable=True),
        sa.Column("resolved_value_kind", sa.Text(), nullable=True),
        sa.Column("resolved_numeric", sa.Numeric(), nullable=True),
        sa.Column("resolved_text", sa.Text(), nullable=True),
        sa.Column("is_nil", sa.Boolean(), nullable=False),
        sa.Column("decimals", sa.Text(), nullable=True),
        sa.Column("precision", sa.Text(), nullable=True),
        sa.Column("xml_lang", sa.Text(), nullable=True),
        sa.Column("scale", sa.Integer(), nullable=True),
        sa.Column("sign", sa.Text(), nullable=True),
        sa.Column("format_namespace_uri", sa.Text(), nullable=True),
        sa.Column("format_local_name", sa.Text(), nullable=True),
        sa.Column("escape", sa.Boolean(), nullable=True),
        sa.Column("continuation_provenance", postgresql.JSONB(), nullable=True),
        sa.Column("source_xml_id", sa.Text(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_locator", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"], ["source.xbrl_report.id"], name="fact_report_id_fkey", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "value_status IN ('valid', 'nil', 'invalid', 'unresolved')",
            name="ck_source_fact_value_status",
        ),
        sa.CheckConstraint("source_order >= 0", name="ck_source_fact_source_order_nonneg"),
        sa.ForeignKeyConstraint(["concept_id"], ["source.concept.id"], name="fact_concept_id_fkey"),
        sa.ForeignKeyConstraint(
            ["context_id"], ["source.context.id"], name="fact_context_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["source.unit.id"], name="fact_unit_id_fkey", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "resolved_value_kind IS NULL OR resolved_value_kind IN ("
            "'numeric', 'text', 'boolean', 'date', 'datetime', 'time', 'qname')",
            name="ck_source_fact_resolved_value_kind",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source.document.id"], name="fact_source_document_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="fact_pkey"),
        sa.CheckConstraint(
            "CASE WHEN resolved_value_kind IS NULL THEN"
            " resolved_text IS NULL AND resolved_numeric IS NULL"
            " WHEN resolved_value_kind = 'numeric' THEN"
            " resolved_text IS NULL AND resolved_numeric IS NOT NULL"
            " ELSE resolved_text IS NOT NULL AND resolved_numeric IS NULL END",
            name="ck_source_fact_resolved_value_coherence",
        ),
        sa.UniqueConstraint("report_id", "source_order", name="uq_source_fact_report_order"),
        schema="source",
    )
    op.create_table(
        "relationship",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("network_type", sa.Text(), nullable=False),
        sa.Column("link_role_uri", sa.Text(), nullable=False),
        sa.Column("arcrole_uri", sa.Text(), nullable=False),
        sa.Column("source_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_value", sa.Numeric(), nullable=True),
        sa.Column("weight", sa.Numeric(), nullable=True),
        sa.Column("preferred_label", sa.Text(), nullable=True),
        sa.Column("target_role", sa.Text(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.Column("source_document_id", sa.BigInteger(), nullable=True),
        sa.Column("source_locator", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "network_type IN ('presentation', 'calculation', 'definition')",
            name="ck_source_relationship_network_type",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["source.xbrl_report.id"],
            name="relationship_report_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_concept_id"], ["source.concept.id"], name="relationship_source_concept_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["target_concept_id"], ["source.concept.id"], name="relationship_target_concept_id_fkey"
        ),
        sa.CheckConstraint("source_order >= 0", name="ck_source_relationship_source_order_nonneg"),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source.document.id"],
            name="relationship_source_document_id_fkey",
        ),
        sa.UniqueConstraint(
            "report_id", "source_order", name="uq_source_relationship_report_order"
        ),
        sa.PrimaryKeyConstraint("id", name="relationship_pkey"),
        schema="source",
    )
    op.create_table(
        "extraction_issue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_id", sa.BigInteger(), nullable=False),
        sa.Column("report_id", sa.BigInteger(), nullable=True),
        sa.Column("document_id", sa.BigInteger(), nullable=True),
        sa.Column("component", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("source_locator", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "severity IN ('fatal', 'warning', 'info')", name="ck_source_extraction_issue_severity"
        ),
        sa.PrimaryKeyConstraint("id", name="extraction_issue_pkey"),
        sa.ForeignKeyConstraint(
            ["filing_id"],
            ["source.filing.id"],
            name="extraction_issue_filing_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["source.xbrl_report.id"],
            name="extraction_issue_report_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["source.document.id"], name="extraction_issue_document_id_fkey"
        ),
        schema="source",
    )
    op.create_table(
        "document_block",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("parent_ordinal", sa.Integer(), nullable=True),
        sa.Column("block_type", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("heading_level", sa.SmallInteger(), nullable=True),
        sa.Column("source_locator", postgresql.JSONB(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="document_block_pkey"),
        sa.CheckConstraint(
            "parent_ordinal IS NULL OR parent_ordinal < ordinal",
            name="ck_source_document_block_parent_precedes",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["source.document.id"],
            name="document_block_document_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "block_type IN ("
            "'heading', 'paragraph', 'list', 'list_item', 'table',"
            " 'footnote', 'signature', 'other')",
            name="ck_source_document_block_type",
        ),
        sa.UniqueConstraint(
            "document_id", "ordinal", name="uq_source_document_block_document_ordinal"
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_source_document_block_ordinal_nonneg"),
        sa.CheckConstraint(
            "(block_type = 'heading' AND heading_level BETWEEN 1 AND 6)"
            " OR (block_type <> 'heading' AND heading_level IS NULL)",
            name="ck_source_document_block_heading_level",
        ),
        schema="source",
    )
    op.create_table(
        "filing_section",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("section_key", sa.Text(), nullable=False),
        sa.Column("start_block_ordinal", sa.Integer(), nullable=False),
        sa.Column("end_block_ordinal_exclusive", sa.Integer(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="filing_section_pkey"),
        sa.CheckConstraint(
            "confidence_score BETWEEN 0 AND 100", name="ck_source_filing_section_confidence_score"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["source.document.id"],
            name="filing_section_document_id_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id", "section_key", name="uq_source_filing_section_document_key"
        ),
        sa.CheckConstraint(
            "start_block_ordinal >= 0 AND end_block_ordinal_exclusive > start_block_ordinal",
            name="ck_source_filing_section_range",
        ),
        schema="source",
    )
    op.create_index(
        "ix_source_filing_issuer_date",
        "filing",
        ["issuer_cik", "filing_date"],
        unique=False,
        schema="source",
    )
    op.create_index("ix_source_filing_form", "filing", ["form"], unique=False, schema="source")
    op.create_index(
        "ix_source_document_filing", "document", ["filing_id"], unique=False, schema="source"
    )
    op.create_index(
        "ix_source_xbrl_report_filing", "xbrl_report", ["filing_id"], unique=False, schema="source"
    )
    op.create_index(
        "ix_source_concept_declaration_source_document",
        "concept_declaration",
        ["source_document_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_concept_label_report_concept",
        "concept_label",
        ["report_id", "concept_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_concept_reference_report_concept",
        "concept_reference",
        ["report_id", "concept_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_context_report_source_id",
        "context",
        ["report_id", "source_context_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_context_dimension_context",
        "context_dimension",
        ["context_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_context_dimension_concept",
        "context_dimension",
        ["dimension_concept_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_unit_report_source_id",
        "unit",
        ["report_id", "source_unit_id"],
        unique=False,
        schema="source",
    )
    op.create_index("ix_source_fact_context", "fact", ["context_id"], unique=False, schema="source")
    op.create_index(
        "ix_source_fact_report_concept",
        "fact",
        ["report_id", "concept_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_fact_source_document",
        "fact",
        ["source_document_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_relationship_target_concept",
        "relationship",
        ["report_id", "target_concept_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_relationship_report_network_role",
        "relationship",
        ["report_id", "network_type", "link_role_uri"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_relationship_source_concept",
        "relationship",
        ["report_id", "source_concept_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_relationship_source_document",
        "relationship",
        ["source_document_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_extraction_issue_filing",
        "extraction_issue",
        ["filing_id"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_document_block_document_ordinal",
        "document_block",
        ["document_id", "ordinal"],
        unique=False,
        schema="source",
    )
    op.create_index(
        "ix_source_filing_section_document_key",
        "filing_section",
        ["document_id", "section_key"],
        unique=False,
        schema="source",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_filing_section_document_key", table_name="filing_section", schema="source"
    )
    op.drop_index(
        "ix_source_document_block_document_ordinal", table_name="document_block", schema="source"
    )
    op.drop_index(
        "ix_source_extraction_issue_filing", table_name="extraction_issue", schema="source"
    )
    op.drop_index(
        "ix_source_relationship_source_document", table_name="relationship", schema="source"
    )
    op.drop_index(
        "ix_source_relationship_source_concept", table_name="relationship", schema="source"
    )
    op.drop_index(
        "ix_source_relationship_report_network_role", table_name="relationship", schema="source"
    )
    op.drop_index(
        "ix_source_relationship_target_concept", table_name="relationship", schema="source"
    )
    op.drop_index("ix_source_fact_source_document", table_name="fact", schema="source")
    op.drop_index("ix_source_fact_report_concept", table_name="fact", schema="source")
    op.drop_index("ix_source_fact_context", table_name="fact", schema="source")
    op.drop_index("ix_source_unit_report_source_id", table_name="unit", schema="source")
    op.drop_index(
        "ix_source_context_dimension_concept", table_name="context_dimension", schema="source"
    )
    op.drop_index(
        "ix_source_context_dimension_context", table_name="context_dimension", schema="source"
    )
    op.drop_index("ix_source_context_report_source_id", table_name="context", schema="source")
    op.drop_index(
        "ix_source_concept_reference_report_concept",
        table_name="concept_reference",
        schema="source",
    )
    op.drop_index(
        "ix_source_concept_label_report_concept", table_name="concept_label", schema="source"
    )
    op.drop_index(
        "ix_source_concept_declaration_source_document",
        table_name="concept_declaration",
        schema="source",
    )
    op.drop_index("ix_source_xbrl_report_filing", table_name="xbrl_report", schema="source")
    op.drop_index("ix_source_document_filing", table_name="document", schema="source")
    op.drop_index("ix_source_filing_form", table_name="filing", schema="source")
    op.drop_index("ix_source_filing_issuer_date", table_name="filing", schema="source")
    op.drop_table("filing_section", schema="source")
    op.drop_table("document_block", schema="source")
    op.drop_table("extraction_issue", schema="source")
    op.drop_table("relationship", schema="source")
    op.drop_table("fact", schema="source")
    op.drop_table("unit_measure", schema="source")
    op.drop_table("unit", schema="source")
    op.drop_table("context_dimension", schema="source")
    op.drop_table("context", schema="source")
    op.drop_table("concept_reference", schema="source")
    op.drop_table("concept_label", schema="source")
    op.drop_table("concept_declaration", schema="source")
    op.drop_table("xbrl_report", schema="source")
    op.drop_table("concept", schema="source")
    op.drop_table("document", schema="source")
    op.drop_table("filing", schema="source")
    op.drop_table("issuer", schema="source")
    op.execute(sa.text("DROP SCHEMA IF EXISTS source CASCADE"))
