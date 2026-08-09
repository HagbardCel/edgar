"""Document projection schema (Phase 1C).

Revision ID: 0003_document_projection
Revises: 0002_semantic_projection
Create Date: 2026-08-09

Explicit historical migration (does not call metadata.create_all).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_document_projection"
down_revision: str | Sequence[str] | None = "0002_semantic_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHA256_CHECK = r"^[0-9a-f]{64}$"


def upgrade() -> None:
    op.create_table(
        "filing_document",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bundle_artifact_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["bundle_artifact_id"],
            ["bundle_artifact.id"],
            name="filing_document_bundle_artifact_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="filing_document_pkey"),
        sa.UniqueConstraint(
            "bundle_artifact_id",
            name="uq_filing_document_bundle_artifact",
        ),
    )
    op.create_table(
        "document_projection",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("parser_config_fingerprint", sa.Text(), nullable=False),
        sa.Column("parser_config", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"parser_config_fingerprint ~ '{SHA256_CHECK}'",
            name="ck_document_projection_config_fingerprint_hex",
        ),
        sa.CheckConstraint(
            "status IN ('complete', 'incomplete')",
            name="ck_document_projection_status",
        ),
        sa.ForeignKeyConstraint(
            ["filing_document_id"],
            ["filing_document.id"],
            name="document_projection_filing_document_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="document_projection_pkey"),
        sa.UniqueConstraint(
            "filing_document_id",
            "parser_version",
            "parser_config_fingerprint",
            name="uq_document_projection_identity",
        ),
    )
    op.create_table(
        "document_projection_attempt",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("filing_document_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("parser_config_fingerprint", sa.Text(), nullable=False),
        sa.Column("parser_config", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("document_projection_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            f"parser_config_fingerprint ~ '{SHA256_CHECK}'",
            name="ck_document_projection_attempt_config_fingerprint_hex",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND document_projection_id IS NOT NULL)"
            " OR (status = 'failed' AND document_projection_id IS NULL)",
            name="ck_document_projection_attempt_status_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["document_projection_id"],
            ["document_projection.id"],
            name="document_projection_attempt_document_projection_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["filing_document_id"],
            ["filing_document.id"],
            name="document_projection_attempt_filing_document_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="document_projection_attempt_pkey"),
    )
    op.create_table(
        "document_issue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_projection_id", sa.BigInteger(), nullable=True),
        sa.Column("document_projection_attempt_id", sa.BigInteger(), nullable=True),
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
            "(document_projection_id IS NOT NULL AND document_projection_attempt_id IS NULL)"
            " OR (document_projection_id IS NULL AND document_projection_attempt_id IS NOT NULL)",
            name="ck_document_issue_single_owner",
        ),
        sa.ForeignKeyConstraint(
            ["document_projection_attempt_id"],
            ["document_projection_attempt.id"],
            name="document_issue_document_projection_attempt_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["document_projection_id"],
            ["document_projection.id"],
            name="document_issue_document_projection_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="document_issue_pkey"),
    )
    op.create_table(
        "document_block",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_projection_id", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("parent_ordinal", sa.Integer(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("heading_level", sa.SmallInteger(), nullable=True),
        sa.Column("source_locator_scheme", sa.Text(), nullable=False),
        sa.Column("source_locator_value", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_document_block_ordinal_nonneg"),
        sa.CheckConstraint(
            "parent_ordinal IS NULL OR parent_ordinal < ordinal",
            name="ck_document_block_parent_precedes",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_locator_value) = 'string'",
            name="ck_document_block_locator_value_string",
        ),
        sa.CheckConstraint(
            "kind IN ("
            "'heading', 'paragraph', 'list', 'list_item', "
            "'table', 'footnote', 'signature', 'other'"
            ")",
            name="ck_document_block_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'heading' AND heading_level BETWEEN 1 AND 6)"
            " OR (kind <> 'heading' AND heading_level IS NULL)",
            name="ck_document_block_heading_level",
        ),
        sa.ForeignKeyConstraint(
            ["document_projection_id"],
            ["document_projection.id"],
            name="document_block_document_projection_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="document_block_pkey"),
        sa.UniqueConstraint(
            "document_projection_id",
            "ordinal",
            name="uq_document_block_projection_ordinal",
        ),
    )
    # Self-FK requires the unique constraint above to exist first.
    op.create_foreign_key(
        "document_block_parent_ordinal_fkey",
        "document_block",
        "document_block",
        ["document_projection_id", "parent_ordinal"],
        ["document_projection_id", "ordinal"],
    )
    op.create_table(
        "filing_section",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_projection_id", sa.BigInteger(), nullable=False),
        sa.Column("section_key", sa.Text(), nullable=False),
        sa.Column("start_block_ordinal", sa.Integer(), nullable=False),
        sa.Column("end_block_ordinal_exclusive", sa.Integer(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "start_block_ordinal >= 0 AND end_block_ordinal_exclusive > start_block_ordinal",
            name="ck_filing_section_range",
        ),
        sa.CheckConstraint(
            "confidence_score BETWEEN 0 AND 100",
            name="ck_filing_section_confidence_score",
        ),
        sa.ForeignKeyConstraint(
            ["document_projection_id"],
            ["document_projection.id"],
            name="filing_section_document_projection_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["document_projection_id", "start_block_ordinal"],
            ["document_block.document_projection_id", "document_block.ordinal"],
            name="filing_section_start_block_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="filing_section_pkey"),
        sa.UniqueConstraint(
            "document_projection_id",
            "section_key",
            name="uq_filing_section_projection_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("filing_section")
    op.drop_constraint(
        "document_block_parent_ordinal_fkey",
        "document_block",
        type_="foreignkey",
    )
    op.drop_table("document_block")
    op.drop_table("document_issue")
    op.drop_table("document_projection_attempt")
    op.drop_table("document_projection")
    op.drop_table("filing_document")
