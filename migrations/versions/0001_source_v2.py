"""V2 Alembic baseline: create source.* schema and all SOURCE_TABLES.

Revision ID: 0001_source_v2
Revises:
Create Date: 2026-08-16

Fresh ``alembic upgrade head`` creates only ``source.*`` (no Phase-1
projection/catalog tables). Existing Phase-1 databases must be recreated;
do not upgrade from the deleted 0001–0004 lineage.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from edgar.db.source_schema import SOURCE_TABLES

revision: str = "0001_source_v2"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS source"))
    bind = op.get_bind()
    for table in SOURCE_TABLES:
        table.create(bind, checkfirst=False)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(SOURCE_TABLES):
        table.drop(bind, checkfirst=True)
    op.execute(sa.text("DROP SCHEMA IF EXISTS source CASCADE"))
