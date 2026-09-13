"""SQL helpers for ``registry.*`` (no semantic decision logic)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, delete, select
from sqlalchemy.dialects.postgresql import insert

from edgar.db import registry_schema as reg


def fetch_canonical_metrics(conn: Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(select(reg.registry_canonical_metric)).mappings().all()
    return {str(row["key"]): dict(row) for row in rows}


def referenced_metric_keys(conn: Connection) -> set[str]:
    rows = conn.execute(select(reg.registry_mapping_assertion.c.target_metric_key)).all()
    return {str(row[0]) for row in rows}


def insert_canonical_metric(conn: Connection, row: Mapping[str, Any]) -> None:
    conn.execute(insert(reg.registry_canonical_metric).values(dict(row)))


def update_canonical_metric(conn: Connection, key: str, row: Mapping[str, Any]) -> None:
    conn.execute(
        reg.registry_canonical_metric.update()
        .where(reg.registry_canonical_metric.c.key == key)
        .values(dict(row))
    )


def delete_canonical_metrics(conn: Connection, keys: Sequence[str]) -> None:
    if not keys:
        return
    conn.execute(
        delete(reg.registry_canonical_metric).where(
            reg.registry_canonical_metric.c.key.in_(tuple(keys))
        )
    )


def fetch_canonical_metric(conn: Connection, key: str) -> dict[str, Any] | None:
    row = (
        conn.execute(
            select(reg.registry_canonical_metric).where(reg.registry_canonical_metric.c.key == key)
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def fetch_concept_by_qname(
    conn: Connection, namespace_uri: str, local_name: str
) -> dict[str, Any] | None:
    from edgar.db import source_schema as src

    row = (
        conn.execute(
            select(src.source_concept).where(
                src.source_concept.c.namespace_uri == namespace_uri,
                src.source_concept.c.local_name == local_name,
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def fetch_issuer(conn: Connection, cik: str) -> dict[str, Any] | None:
    from edgar.db import source_schema as src

    row = (
        conn.execute(select(src.source_issuer).where(src.source_issuer.c.cik == cik))
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def insert_mapping_assertion(conn: Connection, row: Mapping[str, Any]) -> int:
    result = conn.execute(
        insert(reg.registry_mapping_assertion)
        .values(dict(row))
        .returning(reg.registry_mapping_assertion.c.id)
    )
    return int(result.scalar_one())


def fetch_mapping_assertion(conn: Connection, assertion_id: int) -> dict[str, Any] | None:
    row = (
        conn.execute(
            select(reg.registry_mapping_assertion).where(
                reg.registry_mapping_assertion.c.id == assertion_id
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def lock_source_concept(conn: Connection, concept_id: UUID) -> None:
    from edgar.db import source_schema as src

    locked = conn.execute(
        select(src.source_concept.c.id)
        .where(src.source_concept.c.id == concept_id)
        .with_for_update()
    ).scalar_one_or_none()
    if locked is None:
        raise LookupError(f"source.concept id={concept_id} not found")


def successor_id(conn: Connection, assertion_id: int) -> int | None:
    value = conn.execute(
        select(reg.registry_mapping_assertion.c.id).where(
            reg.registry_mapping_assertion.c.supersedes_id == assertion_id
        )
    ).scalar_one_or_none()
    return int(value) if value is not None else None


def fetch_current_assertions(conn: Connection) -> list[dict[str, Any]]:
    successor = reg.registry_mapping_assertion.alias("successor")
    rows = (
        conn.execute(
            select(reg.registry_mapping_assertion)
            .select_from(
                reg.registry_mapping_assertion.outerjoin(
                    successor,
                    successor.c.supersedes_id == reg.registry_mapping_assertion.c.id,
                )
            )
            .where(successor.c.id.is_(None))
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def fetch_chain(conn: Connection, assertion_id: int) -> list[dict[str, Any]]:
    """Return the full revision chain containing ``assertion_id``, oldest first."""
    current = fetch_mapping_assertion(conn, assertion_id)
    if current is None:
        return []
    root = current
    while root["supersedes_id"] is not None:
        predecessor = fetch_mapping_assertion(conn, int(root["supersedes_id"]))
        if predecessor is None:
            break
        root = predecessor
    chain = [root]
    while True:
        nxt = successor_id(conn, int(chain[-1]["id"]))
        if nxt is None:
            break
        row = fetch_mapping_assertion(conn, nxt)
        if row is None:
            break
        chain.append(row)
    return chain


def list_current_assertions(
    conn: Connection,
    *,
    status: str | None = None,
    relation: str | None = None,
    metric_key: str | None = None,
    issuer_cik: str | None = None,
    concept_id: UUID | None = None,
) -> list[dict[str, Any]]:
    rows = fetch_current_assertions(conn)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if status is not None and row["status"] != status:
            continue
        if relation is not None and row["relation"] != relation:
            continue
        if metric_key is not None and row["target_metric_key"] != metric_key:
            continue
        if issuer_cik is not None and row["issuer_cik"] != issuer_cik:
            continue
        if concept_id is not None and row["source_concept_id"] != concept_id:
            continue
        filtered.append(row)
    return filtered


def fetch_concept_by_id(conn: Connection, concept_id: UUID) -> dict[str, Any] | None:
    from edgar.db import source_schema as src

    row = (
        conn.execute(select(src.source_concept).where(src.source_concept.c.id == concept_id))
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def fetch_concepts_by_ids(
    conn: Connection, concept_ids: Sequence[UUID]
) -> dict[UUID, dict[str, Any]]:
    from edgar.db import source_schema as src

    if not concept_ids:
        return {}
    rows = (
        conn.execute(
            select(src.source_concept).where(src.source_concept.c.id.in_(tuple(concept_ids)))
        )
        .mappings()
        .all()
    )
    return {row["id"]: dict(row) for row in rows}


def fetch_facts_for_concept(
    conn: Connection,
    *,
    concept_id: UUID,
    issuer_cik: str | None = None,
) -> list[dict[str, Any]]:
    """Return live fact occurrences for a concept. Caller applies interval contains()."""
    from edgar.db import source_schema as src

    stmt = (
        select(
            src.source_fact.c.id.label("fact_id"),
            src.source_fact.c.source_locator,
            src.source_fact.c.raw_lexical_value,
            src.source_fact.c.resolved_value_kind,
            src.source_fact.c.resolved_numeric,
            src.source_fact.c.resolved_text,
            src.source_fact.c.is_nil,
            src.source_fact.c.context_id,
            src.source_fact.c.unit_id,
            src.source_filing.c.accession,
            src.source_filing.c.issuer_cik,
            src.source_filing.c.report_period_end,
            src.source_document.c.relative_path.label("source_document"),
            src.source_context.c.period_kind,
            src.source_context.c.instant_lexical,
            src.source_context.c.start_lexical,
            src.source_context.c.end_lexical,
        )
        .select_from(
            src.source_fact.join(
                src.source_xbrl_report,
                src.source_xbrl_report.c.id == src.source_fact.c.report_id,
            )
            .join(src.source_filing, src.source_filing.c.id == src.source_xbrl_report.c.filing_id)
            .join(src.source_context, src.source_context.c.id == src.source_fact.c.context_id)
            .outerjoin(
                src.source_document,
                src.source_document.c.id == src.source_fact.c.source_document_id,
            )
        )
        .where(src.source_fact.c.concept_id == concept_id)
    )
    if issuer_cik is not None:
        stmt = stmt.where(src.source_filing.c.issuer_cik == issuer_cik)
    rows = conn.execute(stmt).mappings().all()
    return [dict(row) for row in rows]


def fetch_dimensions_for_contexts(
    conn: Connection, context_ids: Sequence[int]
) -> dict[int, list[dict[str, Any]]]:
    from edgar.db import source_schema as src

    if not context_ids:
        return {}
    dim_concept = src.source_concept.alias("dim_concept")
    member_concept = src.source_concept.alias("member_concept")
    rows = (
        conn.execute(
            select(
                src.source_context_dimension.c.context_id,
                src.source_context_dimension.c.context_element,
                src.source_context_dimension.c.member_kind,
                src.source_context_dimension.c.typed_member,
                dim_concept.c.namespace_uri.label("dimension_namespace_uri"),
                dim_concept.c.local_name.label("dimension_local_name"),
                member_concept.c.namespace_uri.label("member_namespace_uri"),
                member_concept.c.local_name.label("member_local_name"),
            )
            .select_from(
                src.source_context_dimension.join(
                    dim_concept,
                    dim_concept.c.id == src.source_context_dimension.c.dimension_concept_id,
                ).outerjoin(
                    member_concept,
                    member_concept.c.id
                    == src.source_context_dimension.c.explicit_member_concept_id,
                )
            )
            .where(src.source_context_dimension.c.context_id.in_(tuple(context_ids)))
            .order_by(
                src.source_context_dimension.c.context_id,
                src.source_context_dimension.c.id,
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["context_id"]), []).append(dict(row))
    return grouped


def fetch_measures_for_units(
    conn: Connection, unit_ids: Sequence[int]
) -> dict[int, list[dict[str, Any]]]:
    from edgar.db import source_schema as src

    if not unit_ids:
        return {}
    rows = (
        conn.execute(
            select(src.source_unit_measure)
            .where(src.source_unit_measure.c.unit_id.in_(tuple(unit_ids)))
            .order_by(
                src.source_unit_measure.c.unit_id,
                src.source_unit_measure.c.side,
                src.source_unit_measure.c.ordinal,
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["unit_id"]), []).append(dict(row))
    return grouped
