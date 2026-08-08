"""Initial FilingBundle catalog schema.

Revision ID: 0001_catalog
Revises:
Create Date: 2026-08-08

Explicit historical migration (does not call metadata.create_all).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_catalog"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHA256_CHECK = r"^[0-9a-f]{64}$"


def upgrade() -> None:
    op.create_table(
        "issuer",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cik", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="issuer_pkey"),
        sa.UniqueConstraint("cik", name="issuer_cik_key"),
    )
    op.create_table(
        "filing",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("issuer_id", sa.BigInteger(), nullable=False),
        sa.Column("accession_number", sa.Text(), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_period_end", sa.Date(), nullable=True),
        sa.Column("primary_document", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["issuer_id"], ["issuer.id"], name="filing_issuer_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="filing_pkey"),
        sa.UniqueConstraint("accession_number", name="filing_accession_number_key"),
    )
    op.create_table(
        "content_object",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("byte_size >= 0", name="ck_content_object_byte_size_nonneg"),
        sa.CheckConstraint(
            f"sha256 ~ '{SHA256_CHECK}'",
            name="ck_content_object_sha256_hex",
        ),
        sa.PrimaryKeyConstraint("id", name="content_object_pkey"),
        sa.UniqueConstraint("sha256", name="content_object_sha256_key"),
    )
    op.create_table(
        "filing_bundle",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_id", sa.BigInteger(), nullable=False),
        sa.Column("opaque_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("acquisition_policy_version", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.CheckConstraint(
            f"payload_hash ~ '{SHA256_CHECK}'",
            name="ck_filing_bundle_payload_hash_hex",
        ),
        sa.ForeignKeyConstraint(["filing_id"], ["filing.id"], name="filing_bundle_filing_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="filing_bundle_pkey"),
        sa.UniqueConstraint("filing_id", "opaque_id", name="uq_filing_bundle_filing_opaque"),
    )
    op.create_table(
        "bundle_artifact",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_bundle_id", sa.BigInteger(), nullable=False),
        sa.Column("logical_path", sa.Text(), nullable=False),
        sa.Column("content_object_id", sa.BigInteger(), nullable=False),
        sa.Column("artifact_kind", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_object_id"],
            ["content_object.id"],
            name="bundle_artifact_content_object_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["filing_bundle_id"],
            ["filing_bundle.id"],
            name="bundle_artifact_filing_bundle_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="bundle_artifact_pkey"),
        sa.UniqueConstraint(
            "filing_bundle_id",
            "logical_path",
            name="uq_bundle_artifact_bundle_path",
        ),
    )
    op.create_table(
        "bundle_uri_binding",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_bundle_id", sa.BigInteger(), nullable=False),
        sa.Column("bundle_artifact_id", sa.BigInteger(), nullable=False),
        sa.Column("document_uri", sa.Text(), nullable=False),
        sa.Column(
            "replay_aliases",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["bundle_artifact_id"],
            ["bundle_artifact.id"],
            name="bundle_uri_binding_bundle_artifact_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["filing_bundle_id"],
            ["filing_bundle.id"],
            name="bundle_uri_binding_filing_bundle_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="bundle_uri_binding_pkey"),
        sa.UniqueConstraint(
            "filing_bundle_id",
            "document_uri",
            name="uq_bundle_uri_binding_bundle_uri",
        ),
    )
    op.create_table(
        "xbrl_report_input",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_bundle_id", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=True),
        sa.CheckConstraint("ordinal >= 0", name="ck_xbrl_report_input_ordinal_nonneg"),
        sa.CheckConstraint(
            "(kind = 'instance' AND target IS NULL) OR (kind = 'ixds' AND target = 'default')",
            name="ck_xbrl_report_input_kind_target",
        ),
        sa.ForeignKeyConstraint(
            ["filing_bundle_id"],
            ["filing_bundle.id"],
            name="xbrl_report_input_filing_bundle_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="xbrl_report_input_pkey"),
        sa.UniqueConstraint(
            "filing_bundle_id",
            "ordinal",
            name="uq_xbrl_report_input_bundle_ordinal",
        ),
    )
    op.create_table(
        "xbrl_report_input_member",
        sa.Column("report_input_id", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("bundle_uri_binding_id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "ordinal >= 0",
            name="ck_xbrl_report_input_member_ordinal_nonneg",
        ),
        sa.ForeignKeyConstraint(
            ["bundle_uri_binding_id"],
            ["bundle_uri_binding.id"],
            name="xbrl_report_input_member_bundle_uri_binding_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["report_input_id"],
            ["xbrl_report_input.id"],
            name="xbrl_report_input_member_report_input_id_fkey",
        ),
        sa.PrimaryKeyConstraint(
            "report_input_id",
            "ordinal",
            name="pk_xbrl_report_input_member",
        ),
        sa.UniqueConstraint(
            "report_input_id",
            "bundle_uri_binding_id",
            name="uq_xbrl_report_input_member_binding",
        ),
    )


def downgrade() -> None:
    op.drop_table("xbrl_report_input_member")
    op.drop_table("xbrl_report_input")
    op.drop_table("bundle_uri_binding")
    op.drop_table("bundle_artifact")
    op.drop_table("filing_bundle")
    op.drop_table("content_object")
    op.drop_table("filing")
    op.drop_table("issuer")
