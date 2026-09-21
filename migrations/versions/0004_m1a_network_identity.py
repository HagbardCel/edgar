"""M1A-2: Clark link_qname/arc_qname on supported networks.

Revision ID: 0004_m1a_network_identity
Revises: 0003_m1a_extraction_receipt
Create Date: 2026-09-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_m1a_network_identity"
down_revision: str | Sequence[str] | None = "0003_m1a_extraction_receipt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK_SQL = (
    "(link_qname IS NULL AND arc_qname IS NULL) OR "
    "(link_qname IS NOT NULL AND arc_qname IS NOT NULL "
    "AND link_qname <> '' AND arc_qname <> '')"
)

_TABLES: tuple[tuple[str, str], ...] = (
    ("relationship", "ck_source_relationship_link_arc_qname"),
    ("concept_label", "ck_source_concept_label_link_arc_qname"),
    ("concept_reference", "ck_source_concept_reference_link_arc_qname"),
)


def upgrade() -> None:
    for table, check_name in _TABLES:
        op.add_column(
            table,
            sa.Column("link_qname", sa.Text(), nullable=True),
            schema="source",
        )
        op.add_column(
            table,
            sa.Column("arc_qname", sa.Text(), nullable=True),
            schema="source",
        )
        op.create_check_constraint(check_name, table, _CHECK_SQL, schema="source")


def downgrade() -> None:
    for table, check_name in reversed(_TABLES):
        op.drop_constraint(check_name, table, schema="source", type_="check")
        op.drop_column(table, "arc_qname", schema="source")
        op.drop_column(table, "link_qname", schema="source")
