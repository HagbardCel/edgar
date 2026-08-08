"""SQLAlchemy Core table definitions for the FilingBundle catalog."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
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
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("cik", Text, nullable=False, unique=True),
)

filing = Table(
    "filing",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("issuer_id", BigInteger, ForeignKey("issuer.id"), nullable=False),
    Column("accession_number", Text, nullable=False, unique=True),
    Column("form_type", Text, nullable=False),
    Column("filing_date", Date, nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=True),
    Column("report_period_end", Date, nullable=True),
    Column("primary_document", Text, nullable=False),
)

content_object = Table(
    "content_object",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("sha256", Text, nullable=False, unique=True),
    Column("byte_size", BigInteger, nullable=False),
    CheckConstraint("byte_size >= 0", name="ck_content_object_byte_size_nonneg"),
    CheckConstraint(
        f"sha256 ~ '{SHA256_CHECK}'",
        name="ck_content_object_sha256_hex",
    ),
)

filing_bundle = Table(
    "filing_bundle",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("filing_id", BigInteger, ForeignKey("filing.id"), nullable=False),
    Column("opaque_id", Text, nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("acquisition_policy_version", Text, nullable=False),
    Column("payload_hash", Text, nullable=False),
    UniqueConstraint("filing_id", "opaque_id", name="uq_filing_bundle_filing_opaque"),
    CheckConstraint(
        f"payload_hash ~ '{SHA256_CHECK}'",
        name="ck_filing_bundle_payload_hash_hex",
    ),
)

bundle_artifact = Table(
    "bundle_artifact",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("filing_bundle_id", BigInteger, ForeignKey("filing_bundle.id"), nullable=False),
    Column("logical_path", Text, nullable=False),
    Column("content_object_id", BigInteger, ForeignKey("content_object.id"), nullable=False),
    Column("artifact_kind", Text, nullable=False),
    Column("required", Boolean, nullable=False),
    UniqueConstraint(
        "filing_bundle_id",
        "logical_path",
        name="uq_bundle_artifact_bundle_path",
    ),
)

bundle_uri_binding = Table(
    "bundle_uri_binding",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("filing_bundle_id", BigInteger, ForeignKey("filing_bundle.id"), nullable=False),
    Column(
        "bundle_artifact_id",
        BigInteger,
        ForeignKey("bundle_artifact.id"),
        nullable=False,
    ),
    Column("document_uri", Text, nullable=False),
    Column(
        "replay_aliases",
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
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
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("filing_bundle_id", BigInteger, ForeignKey("filing_bundle.id"), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("target", Text, nullable=True),
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
    Column("report_input_id", BigInteger, ForeignKey("xbrl_report_input.id"), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column(
        "bundle_uri_binding_id",
        BigInteger,
        ForeignKey("bundle_uri_binding.id"),
        nullable=False,
    ),
    PrimaryKeyConstraint("report_input_id", "ordinal", name="pk_xbrl_report_input_member"),
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
