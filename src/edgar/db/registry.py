"""SQL helpers for ``registry.*`` (no semantic decision logic)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
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


def now_utc() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
