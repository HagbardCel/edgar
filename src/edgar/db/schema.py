"""SQLAlchemy Core table definitions for the FilingBundle catalog and the XBRL
semantic projection."""

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
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = MetaData()

SHA256_CHECK = r"^[0-9a-f]{64}$"

issuer = Table(
    "issuer",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("cik", Text, nullable=False),
    PrimaryKeyConstraint("id", name="issuer_pkey"),
    UniqueConstraint("cik", name="issuer_cik_key"),
)

filing = Table(
    "filing",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("issuer_id", BigInteger, nullable=False),
    Column("accession_number", Text, nullable=False),
    Column("form_type", Text, nullable=False),
    Column("filing_date", Date, nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=True),
    Column("report_period_end", Date, nullable=True),
    Column("primary_document", Text, nullable=False),
    PrimaryKeyConstraint("id", name="filing_pkey"),
    UniqueConstraint("accession_number", name="filing_accession_number_key"),
    ForeignKeyConstraint(["issuer_id"], ["issuer.id"], name="filing_issuer_id_fkey"),
)

content_object = Table(
    "content_object",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("sha256", Text, nullable=False),
    Column("byte_size", BigInteger, nullable=False),
    PrimaryKeyConstraint("id", name="content_object_pkey"),
    UniqueConstraint("sha256", name="content_object_sha256_key"),
    CheckConstraint("byte_size >= 0", name="ck_content_object_byte_size_nonneg"),
    CheckConstraint(
        f"sha256 ~ '{SHA256_CHECK}'",
        name="ck_content_object_sha256_hex",
    ),
)

filing_bundle = Table(
    "filing_bundle",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("filing_id", BigInteger, nullable=False),
    Column("opaque_id", Text, nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("acquisition_policy_version", Text, nullable=False),
    Column("payload_hash", Text, nullable=False),
    PrimaryKeyConstraint("id", name="filing_bundle_pkey"),
    ForeignKeyConstraint(["filing_id"], ["filing.id"], name="filing_bundle_filing_id_fkey"),
    UniqueConstraint("filing_id", "opaque_id", name="uq_filing_bundle_filing_opaque"),
    CheckConstraint(
        f"payload_hash ~ '{SHA256_CHECK}'",
        name="ck_filing_bundle_payload_hash_hex",
    ),
)

bundle_artifact = Table(
    "bundle_artifact",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("filing_bundle_id", BigInteger, nullable=False),
    Column("logical_path", Text, nullable=False),
    Column("content_object_id", BigInteger, nullable=False),
    Column("artifact_kind", Text, nullable=False),
    Column("required", Boolean, nullable=False),
    PrimaryKeyConstraint("id", name="bundle_artifact_pkey"),
    ForeignKeyConstraint(
        ["filing_bundle_id"],
        ["filing_bundle.id"],
        name="bundle_artifact_filing_bundle_id_fkey",
    ),
    ForeignKeyConstraint(
        ["content_object_id"],
        ["content_object.id"],
        name="bundle_artifact_content_object_id_fkey",
    ),
    UniqueConstraint(
        "filing_bundle_id",
        "logical_path",
        name="uq_bundle_artifact_bundle_path",
    ),
)

bundle_uri_binding = Table(
    "bundle_uri_binding",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("filing_bundle_id", BigInteger, nullable=False),
    Column("bundle_artifact_id", BigInteger, nullable=False),
    Column("document_uri", Text, nullable=False),
    Column(
        "replay_aliases",
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    ),
    PrimaryKeyConstraint("id", name="bundle_uri_binding_pkey"),
    ForeignKeyConstraint(
        ["filing_bundle_id"],
        ["filing_bundle.id"],
        name="bundle_uri_binding_filing_bundle_id_fkey",
    ),
    ForeignKeyConstraint(
        ["bundle_artifact_id"],
        ["bundle_artifact.id"],
        name="bundle_uri_binding_bundle_artifact_id_fkey",
    ),
    UniqueConstraint(
        "filing_bundle_id",
        "document_uri",
        name="uq_bundle_uri_binding_bundle_uri",
    ),
)

xbrl_report_input = Table(
    "xbrl_report_input",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("filing_bundle_id", BigInteger, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("target", Text, nullable=True),
    PrimaryKeyConstraint("id", name="xbrl_report_input_pkey"),
    ForeignKeyConstraint(
        ["filing_bundle_id"],
        ["filing_bundle.id"],
        name="xbrl_report_input_filing_bundle_id_fkey",
    ),
    UniqueConstraint(
        "filing_bundle_id",
        "ordinal",
        name="uq_xbrl_report_input_bundle_ordinal",
    ),
    CheckConstraint("ordinal >= 0", name="ck_xbrl_report_input_ordinal_nonneg"),
    CheckConstraint(
        "(kind = 'instance' AND target IS NULL) OR (kind = 'ixds' AND target = 'default')",
        name="ck_xbrl_report_input_kind_target",
    ),
)

xbrl_report_input_member = Table(
    "xbrl_report_input_member",
    metadata,
    Column("report_input_id", BigInteger, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("bundle_uri_binding_id", BigInteger, nullable=False),
    PrimaryKeyConstraint("report_input_id", "ordinal", name="pk_xbrl_report_input_member"),
    ForeignKeyConstraint(
        ["report_input_id"],
        ["xbrl_report_input.id"],
        name="xbrl_report_input_member_report_input_id_fkey",
    ),
    ForeignKeyConstraint(
        ["bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="xbrl_report_input_member_bundle_uri_binding_id_fkey",
    ),
    UniqueConstraint(
        "report_input_id",
        "bundle_uri_binding_id",
        name="uq_xbrl_report_input_member_binding",
    ),
    CheckConstraint("ordinal >= 0", name="ck_xbrl_report_input_member_ordinal_nonneg"),
)

CATALOG_TABLES = (
    issuer,
    filing,
    content_object,
    filing_bundle,
    bundle_artifact,
    bundle_uri_binding,
    xbrl_report_input,
    xbrl_report_input_member,
)

# --- XBRL semantic projection -------------------------------------------------
#
# Projection identity is (report input, projection version, engine version,
# config fingerprint); operational attempts are separate provenance and a
# projection never owns a single attempt (docs/data-model.md, ADR 0008).

semantic_projection = Table(
    "semantic_projection",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("xbrl_report_input_id", BigInteger, nullable=False),
    Column("projection_version", Text, nullable=False),
    Column("arelle_version", Text, nullable=False),
    Column("semantic_config_fingerprint", Text, nullable=False),
    Column("semantic_config", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("id", name="semantic_projection_pkey"),
    ForeignKeyConstraint(
        ["xbrl_report_input_id"],
        ["xbrl_report_input.id"],
        name="semantic_projection_xbrl_report_input_id_fkey",
    ),
    UniqueConstraint(
        "xbrl_report_input_id",
        "projection_version",
        "arelle_version",
        "semantic_config_fingerprint",
        name="uq_semantic_projection_identity",
    ),
    CheckConstraint(
        f"semantic_config_fingerprint ~ '{SHA256_CHECK}'",
        name="ck_semantic_projection_config_fingerprint_hex",
    ),
    CheckConstraint(
        "status IN ('complete', 'incomplete')",
        name="ck_semantic_projection_status",
    ),
)

semantic_projection_attempt = Table(
    "semantic_projection_attempt",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("xbrl_report_input_id", BigInteger, nullable=False),
    Column("projection_version", Text, nullable=False),
    Column("semantic_config_fingerprint", Text, nullable=False),
    Column("semantic_config", JSONB, nullable=False),
    Column("arelle_version", Text, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("semantic_projection_id", BigInteger, nullable=True),
    PrimaryKeyConstraint("id", name="semantic_projection_attempt_pkey"),
    ForeignKeyConstraint(
        ["xbrl_report_input_id"],
        ["xbrl_report_input.id"],
        name="semantic_projection_attempt_xbrl_report_input_id_fkey",
    ),
    ForeignKeyConstraint(
        ["semantic_projection_id"],
        ["semantic_projection.id"],
        name="semantic_projection_attempt_semantic_projection_id_fkey",
    ),
    CheckConstraint(
        f"semantic_config_fingerprint ~ '{SHA256_CHECK}'",
        name="ck_semantic_projection_attempt_config_fingerprint_hex",
    ),
    CheckConstraint(
        "(status = 'completed' AND semantic_projection_id IS NOT NULL)"
        " OR (status = 'failed' AND semantic_projection_id IS NULL)",
        name="ck_semantic_projection_attempt_status_outcome",
    ),
)

semantic_issue = Table(
    "semantic_issue",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("semantic_projection_id", BigInteger, nullable=True),
    Column("semantic_projection_attempt_id", BigInteger, nullable=True),
    Column("kind", Text, nullable=False),
    Column("severity", Text, nullable=False),
    Column("code", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("context", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    PrimaryKeyConstraint("id", name="semantic_issue_pkey"),
    ForeignKeyConstraint(
        ["semantic_projection_id"],
        ["semantic_projection.id"],
        name="semantic_issue_semantic_projection_id_fkey",
    ),
    ForeignKeyConstraint(
        ["semantic_projection_attempt_id"],
        ["semantic_projection_attempt.id"],
        name="semantic_issue_semantic_projection_attempt_id_fkey",
    ),
    CheckConstraint(
        "(semantic_projection_id IS NOT NULL AND semantic_projection_attempt_id IS NULL)"
        " OR (semantic_projection_id IS NULL AND semantic_projection_attempt_id IS NOT NULL)",
        name="ck_semantic_issue_single_owner",
    ),
)

concept_identity = Table(
    "concept_identity",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("namespace_uri", Text, nullable=False),
    Column("local_name", Text, nullable=False),
    PrimaryKeyConstraint("id", name="concept_identity_pkey"),
    UniqueConstraint("namespace_uri", "local_name", name="uq_concept_identity_qname"),
)

concept_declaration = Table(
    "concept_declaration",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("semantic_projection_id", BigInteger, nullable=False),
    Column("concept_identity_id", BigInteger, nullable=False),
    Column("type_namespace_uri", Text, nullable=True),
    Column("type_local_name", Text, nullable=True),
    Column("substitution_group_namespace_uri", Text, nullable=True),
    Column("substitution_group_local_name", Text, nullable=True),
    Column("period_type", Text, nullable=True),
    Column("balance", Text, nullable=True),
    Column("is_abstract", Boolean, nullable=True),
    Column("is_nillable", Boolean, nullable=True),
    Column("source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("source_locator_scheme", Text, nullable=False),
    Column("source_locator_value", JSONB, nullable=False),
    PrimaryKeyConstraint("id", name="concept_declaration_pkey"),
    ForeignKeyConstraint(
        ["semantic_projection_id"],
        ["semantic_projection.id"],
        name="concept_declaration_semantic_projection_id_fkey",
    ),
    ForeignKeyConstraint(
        ["concept_identity_id"],
        ["concept_identity.id"],
        name="concept_declaration_concept_identity_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="concept_declaration_source_bundle_uri_binding_id_fkey",
    ),
    UniqueConstraint(
        "semantic_projection_id",
        "concept_identity_id",
        name="uq_concept_declaration_projection_concept",
    ),
)

concept_label = Table(
    "concept_label",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("semantic_projection_id", BigInteger, nullable=False),
    Column("concept_declaration_id", BigInteger, nullable=False),
    Column("link_role_uri", Text, nullable=False),
    Column("arcrole_uri", Text, nullable=False),
    Column("resource_role_uri", Text, nullable=True),
    Column("language", Text, nullable=True),
    Column("text", Text, nullable=False),
    Column("order_value", Numeric, nullable=True),
    Column("resource_source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("resource_source_locator_scheme", Text, nullable=False),
    Column("resource_source_locator_value", JSONB, nullable=False),
    Column("arc_source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("arc_source_locator_scheme", Text, nullable=False),
    Column("arc_source_locator_value", JSONB, nullable=False),
    PrimaryKeyConstraint("id", name="concept_label_pkey"),
    ForeignKeyConstraint(
        ["semantic_projection_id"],
        ["semantic_projection.id"],
        name="concept_label_semantic_projection_id_fkey",
    ),
    ForeignKeyConstraint(
        ["concept_declaration_id"],
        ["concept_declaration.id"],
        name="concept_label_concept_declaration_id_fkey",
    ),
    ForeignKeyConstraint(
        ["resource_source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="concept_label_resource_source_bundle_uri_binding_id_fkey",
    ),
    ForeignKeyConstraint(
        ["arc_source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="concept_label_arc_source_bundle_uri_binding_id_fkey",
    ),
    Index(
        "ix_concept_label_declaration_role_language",
        "concept_declaration_id",
        "resource_role_uri",
        "language",
    ),
)

concept_reference = Table(
    "concept_reference",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("semantic_projection_id", BigInteger, nullable=False),
    Column("concept_declaration_id", BigInteger, nullable=False),
    Column("link_role_uri", Text, nullable=False),
    Column("arcrole_uri", Text, nullable=False),
    Column("resource_role_uri", Text, nullable=True),
    Column("reference_parts", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("order_value", Numeric, nullable=True),
    Column("resource_source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("resource_source_locator_scheme", Text, nullable=False),
    Column("resource_source_locator_value", JSONB, nullable=False),
    Column("arc_source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("arc_source_locator_scheme", Text, nullable=False),
    Column("arc_source_locator_value", JSONB, nullable=False),
    PrimaryKeyConstraint("id", name="concept_reference_pkey"),
    ForeignKeyConstraint(
        ["semantic_projection_id"],
        ["semantic_projection.id"],
        name="concept_reference_semantic_projection_id_fkey",
    ),
    ForeignKeyConstraint(
        ["concept_declaration_id"],
        ["concept_declaration.id"],
        name="concept_reference_concept_declaration_id_fkey",
    ),
    ForeignKeyConstraint(
        ["resource_source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="concept_reference_resource_source_bundle_uri_binding_id_fkey",
    ),
    ForeignKeyConstraint(
        ["arc_source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="concept_reference_arc_source_bundle_uri_binding_id_fkey",
    ),
    Index(
        "ix_concept_reference_declaration_role",
        "concept_declaration_id",
        "resource_role_uri",
    ),
)

# A role or arcrole URI may be declared in more than one document of a DTS, so
# the URI alone is never declaration identity (docs/data-model.md).
role_declaration = Table(
    "role_declaration",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("semantic_projection_id", BigInteger, nullable=False),
    Column("role_uri", Text, nullable=False),
    Column("definition", Text, nullable=True),
    Column("used_on", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("source_locator_scheme", Text, nullable=False),
    Column("source_locator_value", JSONB, nullable=False),
    PrimaryKeyConstraint("id", name="role_declaration_pkey"),
    ForeignKeyConstraint(
        ["semantic_projection_id"],
        ["semantic_projection.id"],
        name="role_declaration_semantic_projection_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="role_declaration_source_bundle_uri_binding_id_fkey",
    ),
    Index("ix_role_declaration_projection_role", "semantic_projection_id", "role_uri"),
)

arcrole_declaration = Table(
    "arcrole_declaration",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("semantic_projection_id", BigInteger, nullable=False),
    Column("arcrole_uri", Text, nullable=False),
    Column("definition", Text, nullable=True),
    Column("used_on", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("cycles_allowed", Text, nullable=True),
    Column("source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("source_locator_scheme", Text, nullable=False),
    Column("source_locator_value", JSONB, nullable=False),
    PrimaryKeyConstraint("id", name="arcrole_declaration_pkey"),
    ForeignKeyConstraint(
        ["semantic_projection_id"],
        ["semantic_projection.id"],
        name="arcrole_declaration_semantic_projection_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="arcrole_declaration_source_bundle_uri_binding_id_fkey",
    ),
    Index("ix_arcrole_declaration_projection_arcrole", "semantic_projection_id", "arcrole_uri"),
)

xbrl_context = Table(
    "xbrl_context",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("semantic_projection_id", BigInteger, nullable=False),
    Column("source_context_id", Text, nullable=False),
    Column("entity_scheme", Text, nullable=False),
    Column("entity_identifier", Text, nullable=False),
    Column("period_kind", Text, nullable=False),
    Column("instant_date", Date, nullable=True),
    Column("start_date", Date, nullable=True),
    Column("end_date", Date, nullable=True),
    Column("non_dimensional_segment_xml", Text, nullable=True),
    Column("non_dimensional_scenario_xml", Text, nullable=True),
    Column("source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("source_locator_scheme", Text, nullable=False),
    Column("source_locator_value", JSONB, nullable=False),
    PrimaryKeyConstraint("id", name="xbrl_context_pkey"),
    ForeignKeyConstraint(
        ["semantic_projection_id"],
        ["semantic_projection.id"],
        name="xbrl_context_semantic_projection_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="xbrl_context_source_bundle_uri_binding_id_fkey",
    ),
    CheckConstraint(
        "period_kind IN ('instant', 'duration', 'forever')",
        name="ck_xbrl_context_period_kind",
    ),
    CheckConstraint(
        "(period_kind = 'instant' AND instant_date IS NOT NULL"
        " AND start_date IS NULL AND end_date IS NULL)"
        " OR (period_kind = 'duration' AND instant_date IS NULL"
        " AND start_date IS NOT NULL AND end_date IS NOT NULL)"
        " OR (period_kind = 'forever' AND instant_date IS NULL"
        " AND start_date IS NULL AND end_date IS NULL)",
        name="ck_xbrl_context_period_fields",
    ),
    Index("ix_xbrl_context_projection_source_id", "semantic_projection_id", "source_context_id"),
)

# Filed dimension occurrences only: an implicit default member is never
# materialized here (docs/data-model.md).
xbrl_context_dimension = Table(
    "xbrl_context_dimension",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("context_id", BigInteger, nullable=False),
    Column("dimension_concept_declaration_id", BigInteger, nullable=False),
    Column("context_element", Text, nullable=False),
    Column("member_kind", Text, nullable=False),
    Column("member_concept_declaration_id", BigInteger, nullable=True),
    Column("typed_member_xml", Text, nullable=True),
    Column("typed_member_hash", Text, nullable=True),
    Column("source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("source_locator_scheme", Text, nullable=False),
    Column("source_locator_value", JSONB, nullable=False),
    PrimaryKeyConstraint("id", name="xbrl_context_dimension_pkey"),
    ForeignKeyConstraint(
        ["context_id"],
        ["xbrl_context.id"],
        name="xbrl_context_dimension_context_id_fkey",
    ),
    ForeignKeyConstraint(
        ["dimension_concept_declaration_id"],
        ["concept_declaration.id"],
        name="xbrl_context_dimension_dimension_concept_declaration_id_fkey",
    ),
    ForeignKeyConstraint(
        ["member_concept_declaration_id"],
        ["concept_declaration.id"],
        name="xbrl_context_dimension_member_concept_declaration_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="xbrl_context_dimension_source_bundle_uri_binding_id_fkey",
    ),
    CheckConstraint(
        "context_element IN ('segment', 'scenario')",
        name="ck_xbrl_context_dimension_context_element",
    ),
    CheckConstraint(
        "member_kind IN ('explicit', 'typed')",
        name="ck_xbrl_context_dimension_member_kind",
    ),
    CheckConstraint(
        "(member_kind = 'explicit' AND member_concept_declaration_id IS NOT NULL"
        " AND typed_member_xml IS NULL)"
        " OR (member_kind = 'typed' AND member_concept_declaration_id IS NULL"
        " AND typed_member_xml IS NOT NULL)",
        name="ck_xbrl_context_dimension_member_exclusive",
    ),
    Index("ix_xbrl_context_dimension_dimension", "dimension_concept_declaration_id"),
)

xbrl_unit = Table(
    "xbrl_unit",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("semantic_projection_id", BigInteger, nullable=False),
    Column("source_unit_id", Text, nullable=False),
    Column("source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("source_locator_scheme", Text, nullable=False),
    Column("source_locator_value", JSONB, nullable=False),
    PrimaryKeyConstraint("id", name="xbrl_unit_pkey"),
    ForeignKeyConstraint(
        ["semantic_projection_id"],
        ["semantic_projection.id"],
        name="xbrl_unit_semantic_projection_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="xbrl_unit_source_bundle_uri_binding_id_fkey",
    ),
    Index("ix_xbrl_unit_projection_source_id", "semantic_projection_id", "source_unit_id"),
)

# Measures are expanded QNames; a source prefix is never semantic identity.
xbrl_unit_measure = Table(
    "xbrl_unit_measure",
    metadata,
    Column("unit_id", BigInteger, nullable=False),
    Column("side", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("namespace_uri", Text, nullable=True),
    Column("local_name", Text, nullable=False),
    PrimaryKeyConstraint("unit_id", "side", "ordinal", name="pk_xbrl_unit_measure"),
    ForeignKeyConstraint(["unit_id"], ["xbrl_unit.id"], name="xbrl_unit_measure_unit_id_fkey"),
    CheckConstraint(
        "side IN ('numerator', 'denominator')",
        name="ck_xbrl_unit_measure_side",
    ),
    CheckConstraint("ordinal >= 1", name="ck_xbrl_unit_measure_ordinal_positive"),
)

# One row per source occurrence: uniqueness on (concept, context, unit, value)
# is forbidden because two identical occurrences must both survive.
xbrl_fact = Table(
    "xbrl_fact",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("semantic_projection_id", BigInteger, nullable=False),
    Column("concept_declaration_id", BigInteger, nullable=False),
    Column("context_id", BigInteger, nullable=False),
    Column("unit_id", BigInteger, nullable=True),
    Column("source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("source_locator_scheme", Text, nullable=False),
    Column("source_locator_value", JSONB, nullable=False),
    Column("value_status", Text, nullable=False),
    Column("raw_lexical_value", Text, nullable=True),
    Column("resolved_value_kind", Text, nullable=True),
    Column("resolved_value_text", Text, nullable=True),
    Column("resolved_numeric", Numeric, nullable=True),
    Column("is_nil", Boolean, nullable=False),
    Column("reported_decimals", Text, nullable=True),
    Column("reported_precision", Text, nullable=True),
    Column("xml_lang", Text, nullable=True),
    Column("format_namespace_uri", Text, nullable=True),
    Column("format_local_name", Text, nullable=True),
    Column("scale", Integer, nullable=True),
    Column("sign", Text, nullable=True),
    Column("escape", Boolean, nullable=True),
    Column("continuation_provenance", JSONB, nullable=True),
    PrimaryKeyConstraint("id", name="xbrl_fact_pkey"),
    ForeignKeyConstraint(
        ["semantic_projection_id"],
        ["semantic_projection.id"],
        name="xbrl_fact_semantic_projection_id_fkey",
    ),
    ForeignKeyConstraint(
        ["concept_declaration_id"],
        ["concept_declaration.id"],
        name="xbrl_fact_concept_declaration_id_fkey",
    ),
    ForeignKeyConstraint(
        ["context_id"],
        ["xbrl_context.id"],
        name="xbrl_fact_context_id_fkey",
    ),
    ForeignKeyConstraint(["unit_id"], ["xbrl_unit.id"], name="xbrl_fact_unit_id_fkey"),
    ForeignKeyConstraint(
        ["source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="xbrl_fact_source_bundle_uri_binding_id_fkey",
    ),
    CheckConstraint(
        "value_status IN ('valid', 'nil', 'invalid', 'unresolved')",
        name="ck_xbrl_fact_value_status",
    ),
    Index("ix_xbrl_fact_concept_declaration", "concept_declaration_id"),
    Index("ix_xbrl_fact_context", "context_id"),
)

xbrl_relationship = Table(
    "xbrl_relationship",
    metadata,
    Column("id", BigInteger, autoincrement=True, nullable=False),
    Column("semantic_projection_id", BigInteger, nullable=False),
    Column("network_type", Text, nullable=False),
    Column("link_role_uri", Text, nullable=False),
    Column("arcrole_uri", Text, nullable=False),
    Column("source_concept_declaration_id", BigInteger, nullable=False),
    Column("target_concept_declaration_id", BigInteger, nullable=False),
    Column("order_value", Numeric, nullable=True),
    Column("weight", Numeric, nullable=True),
    Column("preferred_label_role", Text, nullable=True),
    Column("target_role_uri", Text, nullable=True),
    Column("closed", Boolean, nullable=True),
    Column("usable", Boolean, nullable=True),
    Column("context_element", Text, nullable=True),
    Column("source_bundle_uri_binding_id", BigInteger, nullable=False),
    Column("source_locator_scheme", Text, nullable=False),
    Column("source_locator_value", JSONB, nullable=False),
    PrimaryKeyConstraint("id", name="xbrl_relationship_pkey"),
    ForeignKeyConstraint(
        ["semantic_projection_id"],
        ["semantic_projection.id"],
        name="xbrl_relationship_semantic_projection_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_concept_declaration_id"],
        ["concept_declaration.id"],
        name="xbrl_relationship_source_concept_declaration_id_fkey",
    ),
    ForeignKeyConstraint(
        ["target_concept_declaration_id"],
        ["concept_declaration.id"],
        name="xbrl_relationship_target_concept_declaration_id_fkey",
    ),
    ForeignKeyConstraint(
        ["source_bundle_uri_binding_id"],
        ["bundle_uri_binding.id"],
        name="xbrl_relationship_source_bundle_uri_binding_id_fkey",
    ),
    CheckConstraint(
        "network_type IN ('presentation', 'calculation', 'definition')",
        name="ck_xbrl_relationship_network_type",
    ),
    CheckConstraint(
        "context_element IS NULL OR context_element IN ('segment', 'scenario')",
        name="ck_xbrl_relationship_context_element",
    ),
    Index(
        "ix_xbrl_relationship_projection_network_role",
        "semantic_projection_id",
        "network_type",
        "link_role_uri",
    ),
)

SEMANTIC_TABLES = (
    semantic_projection,
    semantic_projection_attempt,
    semantic_issue,
    concept_identity,
    concept_declaration,
    concept_label,
    concept_reference,
    role_declaration,
    arcrole_declaration,
    xbrl_context,
    xbrl_context_dimension,
    xbrl_unit,
    xbrl_unit_measure,
    xbrl_fact,
    xbrl_relationship,
)

ALL_TABLES = CATALOG_TABLES + SEMANTIC_TABLES
