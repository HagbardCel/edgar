"""M1A-3: upstream inventory columns, context/unit uniqueness, same-report FKs.

Revision ID: 0005_m1a_integrity
Revises: 0004_m1a_network_identity
Create Date: 2026-09-22

Preflight (read-only before upgrade on production @0004):
  - duplicate (report_id, id) on source.context / source.unit
  - prospective composite FK violations for fact/label/reference/relationship
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_m1a_integrity"
down_revision: str | Sequence[str] | None = "0004_m1a_network_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPSTREAM_CHECK = (
    "(upstream_item_fact_count IS NULL AND upstream_inventory_version IS NULL) OR "
    "(upstream_item_fact_count IS NOT NULL AND upstream_inventory_version IS NOT NULL "
    "AND upstream_inventory_version = 'upstream-v1' "
    "AND upstream_item_fact_count = arelle_item_fact_count)"
)

_COMPOSITE_FKS: tuple[tuple[str, str, tuple[str, ...], str, tuple[str, ...]], ...] = (
    (
        "fact",
        "fact_report_context_fkey",
        ("report_id", "context_id"),
        "context",
        ("report_id", "id"),
    ),
    (
        "fact",
        "fact_report_unit_fkey",
        ("report_id", "unit_id"),
        "unit",
        ("report_id", "id"),
    ),
    (
        "fact",
        "fact_report_concept_declaration_fkey",
        ("report_id", "concept_id"),
        "concept_declaration",
        ("report_id", "concept_id"),
    ),
    (
        "concept_label",
        "concept_label_report_concept_declaration_fkey",
        ("report_id", "concept_id"),
        "concept_declaration",
        ("report_id", "concept_id"),
    ),
    (
        "concept_reference",
        "concept_reference_report_concept_declaration_fkey",
        ("report_id", "concept_id"),
        "concept_declaration",
        ("report_id", "concept_id"),
    ),
    (
        "relationship",
        "relationship_report_source_concept_declaration_fkey",
        ("report_id", "source_concept_id"),
        "concept_declaration",
        ("report_id", "concept_id"),
    ),
    (
        "relationship",
        "relationship_report_target_concept_declaration_fkey",
        ("report_id", "target_concept_id"),
        "concept_declaration",
        ("report_id", "concept_id"),
    ),
)


def upgrade() -> None:
    op.add_column(
        "xbrl_report",
        sa.Column("upstream_item_fact_count", sa.Integer(), nullable=True),
        schema="source",
    )
    op.add_column(
        "xbrl_report",
        sa.Column("upstream_inventory_version", sa.Text(), nullable=True),
        schema="source",
    )
    op.create_check_constraint(
        "ck_source_xbrl_report_upstream_inventory",
        "xbrl_report",
        _UPSTREAM_CHECK,
        schema="source",
    )

    op.create_unique_constraint(
        "uq_source_context_report_id",
        "context",
        ["report_id", "id"],
        schema="source",
    )
    op.create_unique_constraint(
        "uq_source_unit_report_id",
        "unit",
        ["report_id", "id"],
        schema="source",
    )

    for table, name, local_cols, ref_table, ref_cols in _COMPOSITE_FKS:
        op.create_foreign_key(
            name,
            table,
            ref_table,
            local_cols,
            ref_cols,
            source_schema="source",
            referent_schema="source",
            ondelete="NO ACTION",
        )


def downgrade() -> None:
    for table, name, *_ in reversed(_COMPOSITE_FKS):
        op.drop_constraint(name, table, schema="source", type_="foreignkey")

    op.drop_constraint("uq_source_unit_report_id", "unit", schema="source", type_="unique")
    op.drop_constraint("uq_source_context_report_id", "context", schema="source", type_="unique")

    op.drop_constraint(
        "ck_source_xbrl_report_upstream_inventory",
        "xbrl_report",
        schema="source",
        type_="check",
    )
    op.drop_column("xbrl_report", "upstream_inventory_version", schema="source")
    op.drop_column("xbrl_report", "upstream_item_fact_count", schema="source")
