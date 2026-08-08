"""SQLAlchemy Core table definitions for the FilingBundle catalog."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY

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
