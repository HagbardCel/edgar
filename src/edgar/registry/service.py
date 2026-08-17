"""Application service for the canonical registry and mapping ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine

from edgar.config import Settings
from edgar.db.engine import create_db_engine
from edgar.db.registry import (
    delete_canonical_metrics,
    fetch_canonical_metrics,
    insert_canonical_metric,
    referenced_metric_keys,
    update_canonical_metric,
)
from edgar.registry.hashing import definition_hash
from edgar.registry.loader import LoadedCanonicalRegistry, load_canonical_registry
from edgar.registry.models import CanonicalMetric, RegistryValidationError

_MIRROR_FIELDS = (
    "key",
    "name",
    "kind",
    "statement",
    "period_type",
    "value_kind",
    "unit_dimension",
    "definition",
    "includes",
    "excludes",
    "definition_hash",
)


class RegistryError(RuntimeError):
    """Base error for registry service operations."""


class RegistryOutOfSyncError(RegistryError):
    """YAML canonical metrics do not match the PostgreSQL mirror."""


class UnsafeMetricDeletionError(RegistryError):
    """A YAML-removed metric is still referenced by mapping assertions."""


@dataclass(frozen=True)
class CanonicalSyncResult:
    added: tuple[str, ...]
    changed: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "added": len(self.added),
            "changed": len(self.changed),
            "removed": len(self.removed),
            "unchanged": len(self.unchanged),
        }


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(item) for item in value]


def mirror_payload(metric: CanonicalMetric) -> dict[str, Any]:
    return {
        "key": metric.key,
        "name": metric.name,
        "kind": metric.kind,
        "statement": metric.statement,
        "period_type": metric.period_type,
        "value_kind": metric.value_kind,
        "unit_dimension": metric.unit_dimension,
        "definition": metric.definition,
        "includes": list(metric.includes),
        "excludes": list(metric.excludes),
        "definition_hash": definition_hash(metric),
    }


def row_mirror_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(row["key"]),
        "name": str(row["name"]),
        "kind": str(row["kind"]),
        "statement": str(row["statement"]),
        "period_type": str(row["period_type"]),
        "value_kind": str(row["value_kind"]),
        "unit_dimension": str(row["unit_dimension"]),
        "definition": str(row["definition"]),
        "includes": _as_str_list(row["includes"]),
        "excludes": _as_str_list(row["excludes"]),
        "definition_hash": str(row["definition_hash"]),
    }


def require_yaml_mirror_match(metric: CanonicalMetric, row: dict[str, Any] | None) -> None:
    if row is None:
        raise RegistryOutOfSyncError("registry out of sync; run edgar registry sync")
    if mirror_payload(metric) != row_mirror_payload(row):
        raise RegistryOutOfSyncError("registry out of sync; run edgar registry sync")


class RegistryService:
    """Owns registry writes. Canonical metrics are YAML-authoritative."""

    def __init__(
        self,
        settings: Settings,
        *,
        engine: Engine | None = None,
        registry_dir: Path | None = None,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._registry_dir = registry_dir

    def _require_engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        url = self._settings.require_database_url()
        self._engine = create_db_engine(url)
        return self._engine

    def load_yaml(self) -> LoadedCanonicalRegistry:
        try:
            return load_canonical_registry(self._registry_dir)
        except (OSError, RegistryValidationError) as exc:
            raise RegistryError(str(exc)) from exc

    def sync_canonical_metrics(
        self,
        *,
        conn: Connection | None = None,
        now: datetime | None = None,
    ) -> CanonicalSyncResult:
        yaml_registry = self.load_yaml()
        if conn is not None:
            return self._sync(conn, yaml_registry, now=now)
        engine = self._require_engine()
        with engine.begin() as owned:
            return self._sync(owned, yaml_registry, now=now)

    def _sync(
        self,
        conn: Connection,
        yaml_registry: LoadedCanonicalRegistry,
        *,
        now: datetime | None,
    ) -> CanonicalSyncResult:
        from datetime import UTC

        synced_at = now if now is not None else datetime.now(UTC)
        existing = fetch_canonical_metrics(conn)
        yaml_by_key = yaml_registry.by_key()
        added: list[str] = []
        changed: list[str] = []
        unchanged: list[str] = []
        for key, metric in yaml_by_key.items():
            payload = mirror_payload(metric)
            row = existing.get(key)
            if row is None:
                insert_canonical_metric(conn, {**payload, "synced_at": synced_at})
                added.append(key)
                continue
            if row_mirror_payload(row) == payload:
                unchanged.append(key)
                continue
            update_canonical_metric(conn, key, {**payload, "synced_at": synced_at})
            changed.append(key)

        removed = sorted(set(existing) - set(yaml_by_key))
        if removed:
            referenced = referenced_metric_keys(conn)
            blocked = sorted(set(removed) & referenced)
            if blocked:
                raise UnsafeMetricDeletionError(
                    "cannot remove canonical metrics referenced by mapping "
                    f"assertions: {', '.join(blocked)}"
                )
            delete_canonical_metrics(conn, removed)

        return CanonicalSyncResult(
            added=tuple(sorted(added)),
            changed=tuple(sorted(changed)),
            removed=tuple(removed),
            unchanged=tuple(sorted(unchanged)),
        )


def format_sync_result(result: CanonicalSyncResult) -> str:
    counts = result.counts
    return (
        f"Added:     {counts['added']}\n"
        f"Changed:   {counts['changed']}\n"
        f"Removed:   {counts['removed']}\n"
        f"Unchanged: {counts['unchanged']}"
    )
