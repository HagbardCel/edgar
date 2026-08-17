"""Application service for the canonical registry and mapping ledger."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine

from edgar.config import Settings
from edgar.db.engine import create_db_engine
from edgar.db.registry import (
    delete_canonical_metrics,
    fetch_canonical_metric,
    fetch_canonical_metrics,
    fetch_chain,
    fetch_concept_by_id,
    fetch_concept_by_qname,
    fetch_concepts_by_ids,
    fetch_current_assertions,
    fetch_dimensions_for_contexts,
    fetch_facts_for_concept,
    fetch_issuer,
    fetch_mapping_assertion,
    fetch_measures_for_units,
    insert_canonical_metric,
    insert_mapping_assertion,
    list_current_assertions,
    lock_source_concept,
    referenced_metric_keys,
    successor_id,
    update_canonical_metric,
)
from edgar.registry.hashing import definition_hash
from edgar.registry.interval import interval_contains, scopes_overlap
from edgar.registry.loader import LoadedCanonicalRegistry, load_canonical_registry
from edgar.registry.mapping import (
    CLAIM_FIELDS,
    MappingAssertionCreate,
    MappingAssertionRevision,
    MappingEvidenceItem,
    parse_clark_qname,
)
from edgar.registry.models import CanonicalMetric, RegistryValidationError
from edgar.registry.views import (
    DEFAULT_SHOW_FACT_LIMIT,
    AffectedFactSummary,
    DimensionMemberView,
    MappingAssertionView,
    MappingFactView,
    MappingReport,
    MappingScopeView,
    SourceConceptView,
    TargetMetricView,
    UnitMeasureView,
)


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

    def get_mapping(self, assertion_id: int, *, include_facts: bool = False) -> MappingReport:
        engine = self._require_engine()
        with engine.connect() as conn:
            return self._get_mapping(conn, assertion_id, include_facts=include_facts)

    def list_mappings(
        self,
        *,
        status: str | None = None,
        relation: str | None = None,
        metric_key: str | None = None,
        issuer_cik: str | None = None,
        concept: str | None = None,
    ) -> list[MappingAssertionView]:
        engine = self._require_engine()
        with engine.connect() as conn:
            return self._list_mappings(
                conn,
                status=status,
                relation=relation,
                metric_key=metric_key,
                issuer_cik=issuer_cik,
                concept=concept,
            )

    def mapping_history(self, assertion_id: int) -> list[MappingAssertionView]:
        engine = self._require_engine()
        with engine.connect() as conn:
            chain = fetch_chain(conn, assertion_id)
            if not chain:
                raise MappingDecisionError(f"mapping assertion {assertion_id} not found")
            return self._views_for_rows(conn, chain)

    def affected_facts(self, assertion_id: int) -> list[MappingFactView]:
        engine = self._require_engine()
        with engine.connect() as conn:
            row = fetch_mapping_assertion(conn, assertion_id)
            if row is None:
                raise MappingDecisionError(f"mapping assertion {assertion_id} not found")
            return self._affected_facts(conn, row)

    def _get_mapping(
        self, conn: Connection, assertion_id: int, *, include_facts: bool
    ) -> MappingReport:
        row = fetch_mapping_assertion(conn, assertion_id)
        if row is None:
            raise MappingDecisionError(f"mapping assertion {assertion_id} not found")
        chain = fetch_chain(conn, assertion_id)
        history = self._views_for_rows(conn, chain)
        named = next(view for view in history if view.id == assertion_id)
        concept_row = fetch_concept_by_id(conn, row["source_concept_id"])
        if concept_row is None:
            raise MappingDecisionError(
                f"source concept {row['source_concept_id']} not found for assertion {assertion_id}"
            )
        yaml_registry = self.load_yaml()
        metric = yaml_registry.get(str(row["target_metric_key"]))
        if metric is None:
            raise MappingDecisionError(f"unknown canonical metric: {row['target_metric_key']}")
        mirror = fetch_canonical_metric(conn, metric.key)
        yaml_hash = definition_hash(metric)
        facts = self._affected_facts(conn, row)
        limit = None if include_facts else DEFAULT_SHOW_FACT_LIMIT
        shown = facts if limit is None else facts[:limit]
        accessions = {item.accession for item in facts}
        issuers = {item.issuer_cik for item in facts}
        return MappingReport(
            mapping=named,
            is_current=named.is_current,
            current_revision_id=history[-1].id,
            source_concept=_concept_view(concept_row),
            target_metric=_target_metric_view(metric, yaml_hash),
            yaml_definition_hash=yaml_hash,
            definition_changed=str(row["target_definition_hash"]) != yaml_hash,
            mirror_out_of_sync=(
                mirror is None or row_mirror_payload(mirror) != mirror_payload(metric)
            ),
            scope=named.scope,
            rationale=named.rationale,
            evidence=named.evidence,
            history=tuple(history),
            affected_fact_summary=AffectedFactSummary(
                count=len(facts),
                shown=len(shown),
                truncated=len(shown) < len(facts),
                accession_count=len(accessions),
                issuer_count=len(issuers),
            ),
            affected_facts=tuple(shown),
        )

    def _list_mappings(
        self,
        conn: Connection,
        *,
        status: str | None,
        relation: str | None,
        metric_key: str | None,
        issuer_cik: str | None,
        concept: str | None,
    ) -> list[MappingAssertionView]:
        concept_id = None
        if concept is not None:
            try:
                namespace_uri, local_name = parse_clark_qname(concept)
            except ValueError as exc:
                raise MappingDecisionError(str(exc)) from exc
            found = fetch_concept_by_qname(conn, namespace_uri, local_name)
            if found is None:
                return []
            concept_id = found["id"]
        rows = list_current_assertions(
            conn,
            status=status,
            relation=relation,
            metric_key=metric_key,
            issuer_cik=issuer_cik,
            concept_id=concept_id,
        )
        views = self._views_for_rows(conn, rows)
        return sorted(views, key=_assertion_sort_key)

    def _views_for_rows(
        self, conn: Connection, rows: list[dict[str, Any]]
    ) -> list[MappingAssertionView]:
        concept_ids = [row["source_concept_id"] for row in rows]
        concepts = fetch_concepts_by_ids(conn, concept_ids)
        current_ids = {item["id"] for item in fetch_current_assertions(conn)}
        views: list[MappingAssertionView] = []
        for row in rows:
            concept = concepts.get(row["source_concept_id"])
            if concept is None:
                raise MappingDecisionError(
                    f"source concept {row['source_concept_id']} not found for assertion {row['id']}"
                )
            views.append(_assertion_view(row, concept, is_current=row["id"] in current_ids))
        return views

    def _affected_facts(self, conn: Connection, assertion: dict[str, Any]) -> list[MappingFactView]:
        issuer_cik = assertion["issuer_cik"] if assertion["scope_kind"] == "issuer" else None
        rows = fetch_facts_for_concept(
            conn,
            concept_id=assertion["source_concept_id"],
            issuer_cik=issuer_cik,
        )
        matching = [
            row
            for row in rows
            if interval_contains(
                valid_from=_as_date(assertion["valid_from"]),
                valid_to=_as_date(assertion["valid_to"]),
                report_period_end=_as_date(row["report_period_end"]),
            )
        ]
        context_ids = [int(row["context_id"]) for row in matching]
        unit_ids = [int(row["unit_id"]) for row in matching if row["unit_id"] is not None]
        dimensions = fetch_dimensions_for_contexts(conn, context_ids)
        measures = fetch_measures_for_units(conn, unit_ids)
        facts = [
            _fact_view(
                row,
                dimensions=dimensions.get(int(row["context_id"]), []),
                measures=(
                    measures.get(int(row["unit_id"]), []) if row["unit_id"] is not None else []
                ),
            )
            for row in matching
        ]
        return sorted(facts, key=_fact_sort_key)


def _clark(namespace_uri: str | None, local_name: str) -> str:
    if namespace_uri:
        return f"{{{namespace_uri}}}{local_name}"
    return local_name


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _locator_sort_key(locator: Any) -> str:
    if locator is None:
        return ""
    return json.dumps(locator, sort_keys=True, separators=(",", ":"), default=str)


def _assertion_sort_key(view: MappingAssertionView) -> tuple[str, str, str, str, str, str, int]:
    ns, local = parse_clark_qname(view.source_concept)
    return (
        ns,
        local,
        view.scope.kind,
        view.scope.issuer_cik or "",
        view.target_metric_key,
        view.relation,
        view.id,
    )


def _fact_sort_key(
    fact: MappingFactView,
) -> tuple[str, bool, date, str, str, int]:
    period = fact.report_period_end
    return (
        fact.accession,
        period is None,
        period or date.min,
        fact.source_document or "",
        _locator_sort_key(fact.source_locator),
        fact.fact_id,
    )


def _concept_view(row: dict[str, Any]) -> SourceConceptView:
    namespace_uri = str(row["namespace_uri"])
    local_name = str(row["local_name"])
    return SourceConceptView(
        id=row["id"],
        namespace_uri=namespace_uri,
        local_name=local_name,
        clark_qname=_clark(namespace_uri, local_name),
    )


def _target_metric_view(metric: CanonicalMetric, yaml_hash: str) -> TargetMetricView:
    return TargetMetricView(
        key=metric.key,
        name=metric.name,
        kind=metric.kind,
        statement=metric.statement,
        period_type=metric.period_type,
        value_kind=metric.value_kind,
        unit_dimension=metric.unit_dimension,
        definition=metric.definition,
        includes=metric.includes,
        excludes=metric.excludes,
        definition_hash=yaml_hash,
    )


def _scope_view(row: dict[str, Any]) -> MappingScopeView:
    return MappingScopeView(
        kind=row["scope_kind"],
        issuer_cik=row["issuer_cik"],
        valid_from=_as_date(row["valid_from"]),
        valid_to=_as_date(row["valid_to"]),
    )


def _assertion_view(
    row: dict[str, Any], concept: dict[str, Any], *, is_current: bool
) -> MappingAssertionView:
    evidence_raw = row["evidence"] or []
    evidence = tuple(MappingEvidenceItem.model_validate(item) for item in evidence_raw)
    return MappingAssertionView(
        id=int(row["id"]),
        supersedes_id=None if row["supersedes_id"] is None else int(row["supersedes_id"]),
        is_current=is_current,
        source_concept_id=row["source_concept_id"],
        source_concept=_clark(str(concept["namespace_uri"]), str(concept["local_name"])),
        target_metric_key=str(row["target_metric_key"]),
        target_definition_hash=str(row["target_definition_hash"]),
        relation=row["relation"],
        scope=_scope_view(row),
        status=row["status"],
        method=row["method"],
        rationale=row["rationale"],
        evidence=evidence,
        created_at=row["created_at"],
        created_by=str(row["created_by"]),
    )


def _dimension_view(row: dict[str, Any]) -> DimensionMemberView:
    member: str | None = None
    if row["member_local_name"] is not None:
        member = _clark(row["member_namespace_uri"], str(row["member_local_name"]))
    typed = row["typed_member"]
    return DimensionMemberView(
        dimension=_clark(str(row["dimension_namespace_uri"]), str(row["dimension_local_name"])),
        member=member,
        member_kind=str(row["member_kind"]),
        context_element=str(row["context_element"]),
        typed_member=dict(typed) if typed else None,
    )


def _measure_view(row: dict[str, Any]) -> UnitMeasureView:
    return UnitMeasureView(
        side=str(row["side"]),
        ordinal=int(row["ordinal"]),
        measure=_clark(row["measure_namespace_uri"], str(row["measure_local_name"])),
    )


def _fact_view(
    row: dict[str, Any],
    *,
    dimensions: list[dict[str, Any]],
    measures: list[dict[str, Any]],
) -> MappingFactView:
    locator = row["source_locator"]
    return MappingFactView(
        fact_id=int(row["fact_id"]),
        accession=str(row["accession"]),
        issuer_cik=str(row["issuer_cik"]),
        report_period_end=_as_date(row["report_period_end"]),
        period_kind=str(row["period_kind"]),
        period_instant=row["instant_lexical"],
        period_start=row["start_lexical"],
        period_end=row["end_lexical"],
        source_document=row["source_document"],
        source_locator=dict(locator) if locator else None,
        dimensions=tuple(_dimension_view(item) for item in dimensions),
        unit_measures=tuple(_measure_view(item) for item in measures),
        raw_lexical_value=row["raw_lexical_value"],
        resolved_value_kind=row["resolved_value_kind"],
        resolved_numeric=row["resolved_numeric"],
        resolved_text=row["resolved_text"],
        is_nil=bool(row["is_nil"]),
    )


def format_sync_result(result: CanonicalSyncResult) -> str:
    counts = result.counts
    return (
        f"Added:     {counts['added']}\n"
        f"Changed:   {counts['changed']}\n"
        f"Removed:   {counts['removed']}\n"
        f"Unchanged: {counts['unchanged']}"
    )
