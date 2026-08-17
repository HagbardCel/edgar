"""Phase 2B ``source.*`` SQLAlchemy table definitions.

Grain and identity are frozen here. Interpretation-relevant fidelity columns
required by the V2 source model and parity fixtures are retained.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from edgar.db.schema import SHA256_CHECK, metadata

SOURCE_SCHEMA = "source"

# --- Acquisition-owned durable catalog ---------------------------------------

source_issuer = Table(
    "issuer",
    metadata,
    Column("cik", Text, nullable=False),
    Column("name", Text, nullable=True),
    PrimaryKeyConstraint("cik", name="issuer_pkey"),
    schema=SOURCE_SCHEMA,
)

source_filing = Table(
    "filing",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("issuer_cik", Text, nullable=False),
    Column("accession", Text, nullable=False),
    Column("form", Text, nullable=False),
    Column("filing_date", Date, nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=True),
    Column("report_period_end", Date, nullable=True),
    Column("primary_document", Text, nullable=False),
    PrimaryKeyConstraint("id", name="filing_pkey"),
    ForeignKeyConstraint(
        ["issuer_cik"],
        [f"{SOURCE_SCHEMA}.issuer.cik"],
        name="filing_issuer_cik_fkey",
    ),
    UniqueConstraint("accession", name="filing_accession_key"),
    Index("ix_source_filing_issuer_date", "issuer_cik", "filing_date"),
    Index("ix_source_filing_form", "form"),
    schema=SOURCE_SCHEMA,
)

source_document = Table(
    "document",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("filing_id", BigInteger, nullable=False),
    Column("relative_path", Text, nullable=False),
    Column("document_kind", Text, nullable=False),
    Column("source_url", Text, nullable=True),
    Column("sha256", Text, nullable=False),
    Column("byte_size", BigInteger, nullable=False),
    Column("is_primary", Boolean, nullable=False, server_default=text("false")),
    PrimaryKeyConstraint("id", name="document_pkey"),
    ForeignKeyConstraint(
        ["filing_id"],
        [f"{SOURCE_SCHEMA}.filing.id"],
        name="document_filing_id_fkey",
    ),
    UniqueConstraint("filing_id", "relative_path", name="uq_source_document_filing_path"),
    CheckConstraint("byte_size >= 0", name="ck_source_document_byte_size_nonneg"),
    CheckConstraint(
        f"sha256 ~ '{SHA256_CHECK}'",
        name="ck_source_document_sha256_hex",
    ),
    Index("ix_source_document_filing", "filing_id"),
    schema=SOURCE_SCHEMA,
)

# --- Shared global identity --------------------------------------------------

source_concept = Table(
    "concept",
    metadata,
    Column("id", UUID(as_uuid=True), nullable=False),
    Column("namespace_uri", Text, nullable=False),
    Column("local_name", Text, nullable=False),
    PrimaryKeyConstraint("id", name="concept_pkey"),
    UniqueConstraint("namespace_uri", "local_name", name="uq_source_concept_qname"),
    schema=SOURCE_SCHEMA,
)

# --- Extraction-owned current state ------------------------------------------

source_xbrl_report = Table(
    "xbrl_report",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("filing_id", BigInteger, nullable=False),
    Column("report_key", Text, nullable=False),
    Column("report_input", JSONB, nullable=False),
    Column("entry_document_id", BigInteger, nullable=True),
    Column("extractor_version", Text, nullable=False),
    Column("arelle_version", Text, nullable=False),
    Column("extracted_at", DateTime(timezone=True), nullable=False),
    Column("arelle_item_fact_count", Integer, nullable=False),
    PrimaryKeyConstraint("id", name="xbrl_report_pkey"),
    ForeignKeyConstraint(
        ["filing_id"],
        [f"{SOURCE_SCHEMA}.filing.id"],
        name="xbrl_report_filing_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["entry_document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="xbrl_report_entry_document_id_fkey",
    ),
    UniqueConstraint("filing_id", "report_key", name="uq_source_xbrl_report_filing_key"),
    CheckConstraint(
        f"report_key ~ '{SHA256_CHECK}'",
        name="ck_source_xbrl_report_key_hex",
    ),
    CheckConstraint(
        "arelle_item_fact_count >= 0",
        name="ck_source_xbrl_report_fact_count_nonneg",
    ),
    Index("ix_source_xbrl_report_filing", "filing_id"),
    schema=SOURCE_SCHEMA,
)

source_concept_declaration = Table(
    "concept_declaration",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("report_id", BigInteger, nullable=False),
    Column("concept_id", UUID(as_uuid=True), nullable=False),
    Column("data_type", Text, nullable=True),
    Column("period_type", Text, nullable=True),
    Column("balance", Text, nullable=True),
    Column("abstract", Boolean, nullable=True),
    Column("nillable", Boolean, nullable=True),
    Column("substitution_group", Text, nullable=True),
    Column("source_document_id", BigInteger, nullable=True),
    Column("source_locator", JSONB, nullable=True),
    PrimaryKeyConstraint("id", name="concept_declaration_pkey"),
    ForeignKeyConstraint(
        ["report_id"],
        [f"{SOURCE_SCHEMA}.xbrl_report.id"],
        name="concept_declaration_report_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["concept_id"],
        [f"{SOURCE_SCHEMA}.concept.id"],
        name="concept_declaration_concept_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="concept_declaration_source_document_id_fkey",
    ),
    UniqueConstraint(
        "report_id",
        "concept_id",
        name="uq_source_concept_declaration_report_concept",
    ),
    CheckConstraint(
        "period_type IS NULL OR period_type IN ('instant', 'duration')",
        name="ck_source_concept_declaration_period_type",
    ),
    CheckConstraint(
        "balance IS NULL OR balance IN ('debit', 'credit')",
        name="ck_source_concept_declaration_balance",
    ),
    Index("ix_source_concept_declaration_source_document", "source_document_id"),
    schema=SOURCE_SCHEMA,
)

source_concept_label = Table(
    "concept_label",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("report_id", BigInteger, nullable=False),
    Column("concept_id", UUID(as_uuid=True), nullable=False),
    Column("link_role_uri", Text, nullable=False),
    Column("arcrole_uri", Text, nullable=False),
    Column("resource_role_uri", Text, nullable=True),
    Column("language", Text, nullable=True),
    Column("text", Text, nullable=False),
    Column("order_value", Numeric, nullable=True),
    Column("source_order", Integer, nullable=False),
    Column("source_document_id", BigInteger, nullable=True),
    Column("source_locator", JSONB, nullable=True),
    Column("arc_source_document_id", BigInteger, nullable=True),
    Column("arc_locator", JSONB, nullable=True),
    PrimaryKeyConstraint("id", name="concept_label_pkey"),
    ForeignKeyConstraint(
        ["report_id"],
        [f"{SOURCE_SCHEMA}.xbrl_report.id"],
        name="concept_label_report_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["concept_id"],
        [f"{SOURCE_SCHEMA}.concept.id"],
        name="concept_label_concept_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="concept_label_source_document_id_fkey",
    ),
    ForeignKeyConstraint(
        ["arc_source_document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="concept_label_arc_source_document_id_fkey",
    ),
    UniqueConstraint(
        "report_id",
        "source_order",
        name="uq_source_concept_label_report_order",
    ),
    CheckConstraint("source_order >= 0", name="ck_source_concept_label_source_order_nonneg"),
    Index("ix_source_concept_label_report_concept", "report_id", "concept_id"),
    schema=SOURCE_SCHEMA,
)

source_concept_reference = Table(
    "concept_reference",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("report_id", BigInteger, nullable=False),
    Column("concept_id", UUID(as_uuid=True), nullable=False),
    Column("link_role_uri", Text, nullable=False),
    Column("arcrole_uri", Text, nullable=False),
    Column("resource_role_uri", Text, nullable=True),
    Column("order_value", Numeric, nullable=True),
    Column("source_order", Integer, nullable=False),
    Column("reference_parts", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("source_document_id", BigInteger, nullable=True),
    Column("source_locator", JSONB, nullable=True),
    Column("arc_source_document_id", BigInteger, nullable=True),
    Column("arc_locator", JSONB, nullable=True),
    PrimaryKeyConstraint("id", name="concept_reference_pkey"),
    ForeignKeyConstraint(
        ["report_id"],
        [f"{SOURCE_SCHEMA}.xbrl_report.id"],
        name="concept_reference_report_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["concept_id"],
        [f"{SOURCE_SCHEMA}.concept.id"],
        name="concept_reference_concept_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="concept_reference_source_document_id_fkey",
    ),
    ForeignKeyConstraint(
        ["arc_source_document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="concept_reference_arc_source_document_id_fkey",
    ),
    UniqueConstraint(
        "report_id",
        "source_order",
        name="uq_source_concept_reference_report_order",
    ),
    CheckConstraint("source_order >= 0", name="ck_source_concept_reference_source_order_nonneg"),
    Index("ix_source_concept_reference_report_concept", "report_id", "concept_id"),
    schema=SOURCE_SCHEMA,
)

source_context = Table(
    "context",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("report_id", BigInteger, nullable=False),
    Column("source_context_id", Text, nullable=False),
    Column("entity_scheme", Text, nullable=False),
    Column("entity_identifier", Text, nullable=False),
    Column("period_kind", Text, nullable=False),
    Column("instant_lexical", Text, nullable=True),
    Column("start_lexical", Text, nullable=True),
    Column("end_lexical", Text, nullable=True),
    Column("instant_at", DateTime(timezone=True), nullable=True),
    Column("start_at", DateTime(timezone=True), nullable=True),
    Column("end_at", DateTime(timezone=True), nullable=True),
    Column("source_document_id", BigInteger, nullable=True),
    Column("source_locator", JSONB, nullable=True),
    PrimaryKeyConstraint("id", name="context_pkey"),
    ForeignKeyConstraint(
        ["report_id"],
        [f"{SOURCE_SCHEMA}.xbrl_report.id"],
        name="context_report_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["source_document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="context_source_document_id_fkey",
    ),
    UniqueConstraint("report_id", "source_context_id", name="uq_source_context_report_source_id"),
    CheckConstraint(
        "period_kind IN ('instant', 'duration', 'forever')",
        name="ck_source_context_period_kind",
    ),
    CheckConstraint(
        "(period_kind = 'instant' AND instant_lexical IS NOT NULL"
        " AND start_lexical IS NULL AND end_lexical IS NULL"
        " AND start_at IS NULL AND end_at IS NULL)"
        " OR (period_kind = 'duration' AND instant_lexical IS NULL"
        " AND start_lexical IS NOT NULL AND end_lexical IS NOT NULL"
        " AND instant_at IS NULL)"
        " OR (period_kind = 'forever' AND instant_lexical IS NULL"
        " AND start_lexical IS NULL AND end_lexical IS NULL"
        " AND instant_at IS NULL AND start_at IS NULL AND end_at IS NULL)",
        name="ck_source_context_period_fields",
    ),
    CheckConstraint(
        "(instant_at IS NULL OR instant_lexical IS NOT NULL)"
        " AND (start_at IS NULL OR start_lexical IS NOT NULL)"
        " AND (end_at IS NULL OR end_lexical IS NOT NULL)",
        name="ck_source_context_at_requires_lexical",
    ),
    Index("ix_source_context_report_source_id", "report_id", "source_context_id"),
    schema=SOURCE_SCHEMA,
)

source_context_dimension = Table(
    "context_dimension",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("context_id", BigInteger, nullable=False),
    Column("dimension_concept_id", UUID(as_uuid=True), nullable=False),
    Column("context_element", Text, nullable=False),
    Column("member_kind", Text, nullable=False),
    Column("explicit_member_concept_id", UUID(as_uuid=True), nullable=True),
    Column("typed_member", JSONB, nullable=True),
    Column("source_document_id", BigInteger, nullable=True),
    Column("source_locator", JSONB, nullable=True),
    PrimaryKeyConstraint("id", name="context_dimension_pkey"),
    ForeignKeyConstraint(
        ["context_id"],
        [f"{SOURCE_SCHEMA}.context.id"],
        name="context_dimension_context_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["dimension_concept_id"],
        [f"{SOURCE_SCHEMA}.concept.id"],
        name="context_dimension_dimension_concept_id_fkey",
    ),
    ForeignKeyConstraint(
        ["explicit_member_concept_id"],
        [f"{SOURCE_SCHEMA}.concept.id"],
        name="context_dimension_explicit_member_concept_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="context_dimension_source_document_id_fkey",
    ),
    CheckConstraint(
        "context_element IN ('segment', 'scenario')",
        name="ck_source_context_dimension_context_element",
    ),
    CheckConstraint(
        "member_kind IN ('explicit', 'typed')",
        name="ck_source_context_dimension_member_kind",
    ),
    CheckConstraint(
        "(member_kind = 'explicit' AND explicit_member_concept_id IS NOT NULL"
        " AND typed_member IS NULL)"
        " OR (member_kind = 'typed' AND explicit_member_concept_id IS NULL"
        " AND typed_member IS NOT NULL)",
        name="ck_source_context_dimension_member_exclusive",
    ),
    Index("ix_source_context_dimension_context", "context_id"),
    Index("ix_source_context_dimension_concept", "dimension_concept_id"),
    schema=SOURCE_SCHEMA,
)

source_unit = Table(
    "unit",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("report_id", BigInteger, nullable=False),
    Column("source_unit_id", Text, nullable=False),
    Column("source_document_id", BigInteger, nullable=True),
    Column("source_locator", JSONB, nullable=True),
    PrimaryKeyConstraint("id", name="unit_pkey"),
    ForeignKeyConstraint(
        ["report_id"],
        [f"{SOURCE_SCHEMA}.xbrl_report.id"],
        name="unit_report_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["source_document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="unit_source_document_id_fkey",
    ),
    UniqueConstraint("report_id", "source_unit_id", name="uq_source_unit_report_source_id"),
    Index("ix_source_unit_report_source_id", "report_id", "source_unit_id"),
    schema=SOURCE_SCHEMA,
)

source_unit_measure = Table(
    "unit_measure",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("unit_id", BigInteger, nullable=False),
    Column("side", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("measure_namespace_uri", Text, nullable=True),
    Column("measure_local_name", Text, nullable=False),
    PrimaryKeyConstraint("id", name="unit_measure_pkey"),
    ForeignKeyConstraint(
        ["unit_id"],
        [f"{SOURCE_SCHEMA}.unit.id"],
        name="unit_measure_unit_id_fkey",
        ondelete="CASCADE",
    ),
    UniqueConstraint("unit_id", "side", "ordinal", name="uq_source_unit_measure_side_ordinal"),
    CheckConstraint(
        "side IN ('numerator', 'denominator')",
        name="ck_source_unit_measure_side",
    ),
    CheckConstraint("ordinal >= 1", name="ck_source_unit_measure_ordinal_positive"),
    schema=SOURCE_SCHEMA,
)

source_fact = Table(
    "fact",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("report_id", BigInteger, nullable=False),
    Column("source_order", Integer, nullable=False),
    Column("concept_id", UUID(as_uuid=True), nullable=False),
    Column("context_id", BigInteger, nullable=False),
    Column("unit_id", BigInteger, nullable=True),
    Column("value_status", Text, nullable=False),
    Column("raw_lexical_value", Text, nullable=True),
    Column("resolved_value_kind", Text, nullable=True),
    Column("resolved_numeric", Numeric, nullable=True),
    Column("resolved_text", Text, nullable=True),
    Column("is_nil", Boolean, nullable=False),
    Column("decimals", Text, nullable=True),
    Column("precision", Text, nullable=True),
    Column("xml_lang", Text, nullable=True),
    Column("scale", Integer, nullable=True),
    Column("sign", Text, nullable=True),
    Column("format_namespace_uri", Text, nullable=True),
    Column("format_local_name", Text, nullable=True),
    Column("escape", Boolean, nullable=True),
    Column("continuation_provenance", JSONB, nullable=True),
    Column("source_xml_id", Text, nullable=True),
    Column("source_document_id", BigInteger, nullable=True),
    Column("source_locator", JSONB, nullable=True),
    PrimaryKeyConstraint("id", name="fact_pkey"),
    ForeignKeyConstraint(
        ["report_id"],
        [f"{SOURCE_SCHEMA}.xbrl_report.id"],
        name="fact_report_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["concept_id"],
        [f"{SOURCE_SCHEMA}.concept.id"],
        name="fact_concept_id_fkey",
    ),
    ForeignKeyConstraint(
        ["context_id"],
        [f"{SOURCE_SCHEMA}.context.id"],
        name="fact_context_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["unit_id"],
        [f"{SOURCE_SCHEMA}.unit.id"],
        name="fact_unit_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["source_document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="fact_source_document_id_fkey",
    ),
    UniqueConstraint("report_id", "source_order", name="uq_source_fact_report_order"),
    CheckConstraint(
        "value_status IN ('valid', 'nil', 'invalid', 'unresolved')",
        name="ck_source_fact_value_status",
    ),
    CheckConstraint(
        "resolved_value_kind IS NULL OR resolved_value_kind IN "
        "('numeric', 'text', 'boolean', 'date', 'datetime', 'time', 'qname')",
        name="ck_source_fact_resolved_value_kind",
    ),
    CheckConstraint(
        "CASE "
        "WHEN resolved_value_kind IS NULL THEN "
        "resolved_text IS NULL AND resolved_numeric IS NULL "
        "WHEN resolved_value_kind = 'numeric' THEN "
        "resolved_text IS NULL AND resolved_numeric IS NOT NULL "
        "ELSE "
        "resolved_text IS NOT NULL AND resolved_numeric IS NULL "
        "END",
        name="ck_source_fact_resolved_value_coherence",
    ),
    CheckConstraint("source_order >= 0", name="ck_source_fact_source_order_nonneg"),
    Index("ix_source_fact_report_concept", "report_id", "concept_id"),
    Index("ix_source_fact_context", "context_id"),
    Index("ix_source_fact_source_document", "source_document_id"),
    schema=SOURCE_SCHEMA,
)

source_relationship = Table(
    "relationship",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("report_id", BigInteger, nullable=False),
    Column("source_order", Integer, nullable=False),
    Column("network_type", Text, nullable=False),
    Column("link_role_uri", Text, nullable=False),
    Column("arcrole_uri", Text, nullable=False),
    Column("source_concept_id", UUID(as_uuid=True), nullable=False),
    Column("target_concept_id", UUID(as_uuid=True), nullable=False),
    Column("order_value", Numeric, nullable=True),
    Column("weight", Numeric, nullable=True),
    Column("preferred_label", Text, nullable=True),
    Column("target_role", Text, nullable=True),
    Column("attributes", JSONB, nullable=True),
    Column("source_document_id", BigInteger, nullable=True),
    Column("source_locator", JSONB, nullable=True),
    PrimaryKeyConstraint("id", name="relationship_pkey"),
    ForeignKeyConstraint(
        ["report_id"],
        [f"{SOURCE_SCHEMA}.xbrl_report.id"],
        name="relationship_report_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["source_concept_id"],
        [f"{SOURCE_SCHEMA}.concept.id"],
        name="relationship_source_concept_id_fkey",
    ),
    ForeignKeyConstraint(
        ["target_concept_id"],
        [f"{SOURCE_SCHEMA}.concept.id"],
        name="relationship_target_concept_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="relationship_source_document_id_fkey",
    ),
    UniqueConstraint("report_id", "source_order", name="uq_source_relationship_report_order"),
    CheckConstraint(
        "network_type IN ('presentation', 'calculation', 'definition')",
        name="ck_source_relationship_network_type",
    ),
    CheckConstraint("source_order >= 0", name="ck_source_relationship_source_order_nonneg"),
    Index(
        "ix_source_relationship_report_network_role",
        "report_id",
        "network_type",
        "link_role_uri",
    ),
    Index("ix_source_relationship_source_concept", "report_id", "source_concept_id"),
    Index("ix_source_relationship_target_concept", "report_id", "target_concept_id"),
    Index("ix_source_relationship_source_document", "source_document_id"),
    schema=SOURCE_SCHEMA,
)

source_extraction_issue = Table(
    "extraction_issue",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("filing_id", BigInteger, nullable=False),
    Column("report_id", BigInteger, nullable=True),
    Column("document_id", BigInteger, nullable=True),
    Column("component", Text, nullable=False),
    Column("code", Text, nullable=False),
    Column("severity", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("details", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("source_locator", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("id", name="extraction_issue_pkey"),
    ForeignKeyConstraint(
        ["filing_id"],
        [f"{SOURCE_SCHEMA}.filing.id"],
        name="extraction_issue_filing_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["report_id"],
        [f"{SOURCE_SCHEMA}.xbrl_report.id"],
        name="extraction_issue_report_id_fkey",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="extraction_issue_document_id_fkey",
    ),
    CheckConstraint(
        "severity IN ('fatal', 'warning', 'info')",
        name="ck_source_extraction_issue_severity",
    ),
    Index("ix_source_extraction_issue_filing", "filing_id"),
    schema=SOURCE_SCHEMA,
)

source_document_block = Table(
    "document_block",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("document_id", BigInteger, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("parent_ordinal", Integer, nullable=True),
    Column("block_type", Text, nullable=False),
    Column("text", Text, nullable=True),
    Column("heading_level", SmallInteger, nullable=True),
    Column("source_locator", JSONB, nullable=False),
    Column("parser_version", Text, nullable=False),
    PrimaryKeyConstraint("id", name="document_block_pkey"),
    ForeignKeyConstraint(
        ["document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="document_block_document_id_fkey",
        ondelete="CASCADE",
    ),
    UniqueConstraint("document_id", "ordinal", name="uq_source_document_block_document_ordinal"),
    CheckConstraint("ordinal >= 0", name="ck_source_document_block_ordinal_nonneg"),
    CheckConstraint(
        "parent_ordinal IS NULL OR parent_ordinal < ordinal",
        name="ck_source_document_block_parent_precedes",
    ),
    CheckConstraint(
        "block_type IN ("
        "'heading', 'paragraph', 'list', 'list_item', "
        "'table', 'footnote', 'signature', 'other'"
        ")",
        name="ck_source_document_block_type",
    ),
    CheckConstraint(
        "(block_type = 'heading' AND heading_level BETWEEN 1 AND 6)"
        " OR (block_type <> 'heading' AND heading_level IS NULL)",
        name="ck_source_document_block_heading_level",
    ),
    Index("ix_source_document_block_document_ordinal", "document_id", "ordinal"),
    schema=SOURCE_SCHEMA,
)

source_filing_section = Table(
    "filing_section",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("document_id", BigInteger, nullable=False),
    Column("section_key", Text, nullable=False),
    Column("start_block_ordinal", Integer, nullable=False),
    Column("end_block_ordinal_exclusive", Integer, nullable=False),
    Column("method", Text, nullable=False),
    Column("confidence_score", SmallInteger, nullable=False),
    PrimaryKeyConstraint("id", name="filing_section_pkey"),
    ForeignKeyConstraint(
        ["document_id"],
        [f"{SOURCE_SCHEMA}.document.id"],
        name="filing_section_document_id_fkey",
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "document_id",
        "section_key",
        name="uq_source_filing_section_document_key",
    ),
    CheckConstraint(
        "start_block_ordinal >= 0 AND end_block_ordinal_exclusive > start_block_ordinal",
        name="ck_source_filing_section_range",
    ),
    CheckConstraint(
        "confidence_score BETWEEN 0 AND 100",
        name="ck_source_filing_section_confidence_score",
    ),
    Index("ix_source_filing_section_document_key", "document_id", "section_key"),
    schema=SOURCE_SCHEMA,
)

SOURCE_CATALOG_TABLES = (
    source_issuer,
    source_filing,
    source_document,
)

SOURCE_EXTRACTION_TABLES = (
    source_xbrl_report,
    source_concept_declaration,
    source_concept_label,
    source_concept_reference,
    source_context,
    source_context_dimension,
    source_unit,
    source_unit_measure,
    source_fact,
    source_relationship,
    source_extraction_issue,
    source_document_block,
    source_filing_section,
)

SOURCE_TABLES = SOURCE_CATALOG_TABLES + (source_concept,) + SOURCE_EXTRACTION_TABLES

# Ensure Alembic / truncate helpers see these tables when schema is imported.
assert metadata is not None
