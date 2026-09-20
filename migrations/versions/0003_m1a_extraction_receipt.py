"""M1A-1: nullable extraction receipt on source.xbrl_report.

Revision ID: 0003_m1a_extraction_receipt
Revises: 0002_registry
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_m1a_extraction_receipt"
down_revision: str | Sequence[str] | None = "0002_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "xbrl_report",
        sa.Column("extraction_receipt", postgresql.JSONB(), nullable=True),
        schema="source",
    )


def downgrade() -> None:
    op.drop_column("xbrl_report", "extraction_receipt", schema="source")
