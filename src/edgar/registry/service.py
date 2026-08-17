"""Application service for the canonical registry and mapping ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine

from edgar.config import Settings
from edgar.db.engine import create_db_engine
from edgar.db.registry import (
    delete_canonical_metrics,
    fetch_canonical_metric,
    fetch_canonical_metrics,
    fetch_concept_by_qname,
    fetch_current_assertions,
    fetch_issuer,
    fetch_mapping_assertion,
    insert_canonical_metric,
    insert_mapping_assertion,
    lock_source_concept,
    referenced_metric_keys,
    successor_id,
    update_canonical_metric,
)
from edgar.registry.hashing import definition_hash
from edgar.registry.interval import scopes_overlap
from edgar.registry.loader import LoadedCanonicalRegistry, load_canonical_registry
from edgar.registry.mapping import (
    CLAIM_FIELDS,
    MappingAssertionCreate,
    MappingAssertionRevision,
    MappingEvidenceItem,
)
from edgar.registry.models import CanonicalMetric, RegistryValidationError


class RegistryError(RuntimeError):
    """Base error for registry service operations."""


class RegistryOutOfSyncError(RegistryError):
    """YAML canonical metrics do not match the PostgreSQL mirror."""


class UnsafeMetricDeletionError(RegistryError):
    """A YAML-removed metric is still referenced by mapping assertions."""


class MappingDecisionError(RegistryError):
    """Mapping propose/accept/reject invariant violation."""


class ConceptNotFoundError(MappingDecisionError):
    """Source concept QName is not present in source.concept."""


class ConflictingExactMappingError(MappingDecisionError):
    """A current accepted exact mapping already covers overlapping scope."""


class MetricDefinitionChangedError(MappingDecisionError):
    """Candidate target_definition_hash does not match current YAML."""


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

    def propose_mapping(self, create: MappingAssertionCreate) -> int:
        engine = self._require_engine()
        with engine.begin() as conn:
            return self._propose_mapping(conn, create)

    def accept_mapping(self, assertion_id: int, revision: MappingAssertionRevision) -> int:
        engine = self._require_engine()
        with engine.begin() as conn:
            return self._accept_mapping(conn, assertion_id, revision)

    def reject_mapping(self, assertion_id: int, revision: MappingAssertionRevision) -> int:
        engine = self._require_engine()
        with engine.begin() as conn:
            return self._reject_mapping(conn, assertion_id, revision)

    def _require_current(self, conn: Connection, assertion_id: int) -> dict[str, Any]:
        row = fetch_mapping_assertion(conn, assertion_id)
        if row is None:
            raise MappingDecisionError(f"mapping assertion {assertion_id} not found")
        if successor_id(conn, assertion_id) is not None:
            raise MappingDecisionError(
                f"mapping assertion {assertion_id} is not the current revision"
            )
        return row

    def _require_yaml_metric(self, conn: Connection, key: str) -> CanonicalMetric:
        yaml_registry = self.load_yaml()
        metric = yaml_registry.get(key)
        if metric is None:
            raise MappingDecisionError(f"unknown canonical metric: {key}")
        require_yaml_mirror_match(metric, fetch_canonical_metric(conn, key))
        return metric

    def _evidence_payload(self, items: tuple[MappingEvidenceItem, ...]) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in items]

    def _claim_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {field: row[field] for field in CLAIM_FIELDS}

    def _propose_mapping(self, conn: Connection, create: MappingAssertionCreate) -> int:
        namespace_uri, local_name = create.clark_parts()
        concept = fetch_concept_by_qname(conn, namespace_uri, local_name)
        if concept is None:
            raise ConceptNotFoundError(f"source concept not found: {{{namespace_uri}}}{local_name}")
        if create.issuer_cik is not None and fetch_issuer(conn, create.issuer_cik) is None:
            raise MappingDecisionError(f"unknown issuer CIK: {create.issuer_cik}")
        metric = self._require_yaml_metric(conn, create.target_metric_key)
        row = {
            "supersedes_id": None,
            "source_concept_id": concept["id"],
            "target_metric_key": metric.key,
            "target_definition_hash": definition_hash(metric),
            "relation": create.relation,
            "scope_kind": create.scope_kind,
            "issuer_cik": create.issuer_cik,
            "valid_from": create.valid_from,
            "valid_to": create.valid_to,
            "status": "candidate",
            "method": create.method,
            "rationale": create.rationale,
            "evidence": self._evidence_payload(create.evidence),
            "created_at": datetime.now(UTC),
            "created_by": create.created_by,
        }
        return insert_mapping_assertion(conn, row)

    def _require_accepted_evidence(
        self, revision: MappingAssertionRevision, *, yaml_hash: str, candidate_hash: str
    ) -> None:
        if candidate_hash != yaml_hash:
            raise MetricDefinitionChangedError(
                "canonical metric changed since proposal; candidate requires re-review/re-proposal"
            )
        if revision.rationale is None or not revision.rationale.strip():
            raise MappingDecisionError("accepted mappings require a non-empty rationale")
        if not revision.evidence:
            raise MappingDecisionError("accepted mappings require non-empty evidence")
        if any(not item.has_snapshot() for item in revision.evidence):
            raise MappingDecisionError("accepted evidence must contain snapshots, not empty data")

    def _conflict_if_needed(
        self,
        conn: Connection,
        *,
        candidate: dict[str, Any],
        ignore_id: int,
    ) -> None:
        if candidate["relation"] != "exact":
            return
        for other in fetch_current_assertions(conn):
            if int(other["id"]) == ignore_id:
                continue
            if other["status"] != "accepted" or other["relation"] != "exact":
                continue
            if other["source_concept_id"] != candidate["source_concept_id"]:
                continue
            if not scopes_overlap(
                left_scope=str(candidate["scope_kind"]),
                left_issuer_cik=candidate["issuer_cik"],
                left_from=candidate["valid_from"],
                left_to=candidate["valid_to"],
                right_scope=str(other["scope_kind"]),
                right_issuer_cik=other["issuer_cik"],
                right_from=other["valid_from"],
                right_to=other["valid_to"],
            ):
                continue
            raise ConflictingExactMappingError(
                "conflicting current accepted exact mapping "
                f"{other['id']} already applies to this source concept"
            )

    def _accept_mapping(
        self, conn: Connection, assertion_id: int, revision: MappingAssertionRevision
    ) -> int:
        current = self._require_current(conn, assertion_id)
        if current["status"] != "candidate":
            raise MappingDecisionError("only a current candidate can be accepted")
        metric = self._require_yaml_metric(conn, str(current["target_metric_key"]))
        yaml_hash = definition_hash(metric)
        self._require_accepted_evidence(
            revision,
            yaml_hash=yaml_hash,
            candidate_hash=str(current["target_definition_hash"]),
        )
        lock_source_concept(conn, current["source_concept_id"])
        self._conflict_if_needed(conn, candidate=current, ignore_id=assertion_id)
        payload = self._claim_from_row(current)
        payload.update(
            {
                "supersedes_id": assertion_id,
                "status": "accepted",
                "method": revision.method,
                "rationale": revision.rationale,
                "evidence": self._evidence_payload(revision.evidence),
                "created_at": datetime.now(UTC),
                "created_by": revision.created_by,
            }
        )
        return insert_mapping_assertion(conn, payload)

    def _reject_mapping(
        self, conn: Connection, assertion_id: int, revision: MappingAssertionRevision
    ) -> int:
        current = self._require_current(conn, assertion_id)
        if current["status"] not in {"candidate", "accepted"}:
            raise MappingDecisionError("rejected assertions are terminal")
        if revision.rationale is None or not revision.rationale.strip():
            raise MappingDecisionError("rejected mappings require a non-empty rationale")
        payload = self._claim_from_row(current)
        payload.update(
            {
                "supersedes_id": assertion_id,
                "status": "rejected",
                "method": revision.method,
                "rationale": revision.rationale,
                "evidence": self._evidence_payload(revision.evidence),
                "created_at": datetime.now(UTC),
                "created_by": revision.created_by,
            }
        )
        return insert_mapping_assertion(conn, payload)


def format_sync_result(result: CanonicalSyncResult) -> str:
    counts = result.counts
    return (
        f"Added:     {counts['added']}\n"
        f"Changed:   {counts['changed']}\n"
        f"Removed:   {counts['removed']}\n"
        f"Unchanged: {counts['unchanged']}"
    )
