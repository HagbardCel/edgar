"""Application service: Git-authoritative metric registry sync and gated reads."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Connection, Engine

from edgar.config import Settings
from edgar.db.engine import create_db_engine
from edgar.db.metrics import (
    MappingRuleRow,
    MetricRegistryConflict,
    RegistryRevisionRow,
    SourceFactOccurrence,
    SyncResult,
    get_latest_revision,
    get_mapping,
    get_metric,
    get_supersession_chain,
    list_mappings,
    list_metrics,
    query_source_fact_occurrences,
    sync_registry,
    verify_materialization,
)
from edgar.metrics.registry import (
    LoadedRegistry,
    MappingRuleRecord,
    MetricDefinitionRecord,
    MetricFamilyRecord,
    load_registry,
    validate_registry,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_REGISTRY_DIR = _REPO_ROOT / "semantic-registry"


class RegistryNotSyncedError(RuntimeError):
    """Git registry_hash does not match the latest DB revision; run metrics sync."""


class RegistryIntegrityError(RuntimeError):
    """DB materialization does not match the authoritative Git registry."""


class MetricRegistryService:
    """Sync and query the curated metric ontology / mapping registry."""

    def __init__(
        self,
        settings: Settings,
        *,
        engine: Engine | None = None,
        registry_dir: Path | None = None,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._registry_dir = registry_dir if registry_dir is not None else _DEFAULT_REGISTRY_DIR

    def _require_engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        url = self._settings.require_database_url()
        self._engine = create_db_engine(url)
        return self._engine

    def load_git_registry(self) -> LoadedRegistry:
        registry = load_registry(self._registry_dir)
        validate_registry(registry)
        return registry

    def sync(self) -> SyncResult:
        registry = self.load_git_registry()
        engine = self._require_engine()
        with engine.begin() as conn:
            return sync_registry(conn, registry)

    def _require_synced(self, conn: Connection, registry: LoadedRegistry) -> RegistryRevisionRow:
        latest = get_latest_revision(conn)
        if latest is None or latest.registry_hash != registry.registry_hash:
            raise RegistryNotSyncedError(
                "registry changed; run `edgar metrics sync` "
                f"(git={registry.registry_hash}, "
                f"db={None if latest is None else latest.registry_hash})"
            )
        try:
            verify_materialization(conn, registry)
        except MetricRegistryConflict as exc:
            raise RegistryIntegrityError(str(exc)) from exc
        return latest

    def list_families(self) -> tuple[MetricFamilyRecord, ...]:
        registry = self.load_git_registry()
        engine = self._require_engine()
        with engine.connect() as conn:
            self._require_synced(conn, registry)
            return registry.families

    def list_metrics(self) -> tuple[MetricDefinitionRecord, ...]:
        registry = self.load_git_registry()
        engine = self._require_engine()
        with engine.connect() as conn:
            self._require_synced(conn, registry)
            return list_metrics(conn)

    def get_metric(
        self,
        metric_code: str,
        *,
        definition_version: int | None = None,
    ) -> tuple[MetricDefinitionRecord, ...]:
        registry = self.load_git_registry()
        engine = self._require_engine()
        with engine.connect() as conn:
            self._require_synced(conn, registry)
            matches = get_metric(conn, metric_code, definition_version=definition_version)
            if definition_version is None and len(matches) > 1:
                versions = sorted(d.definition_version for d in matches)
                raise ValueError(
                    f"metric {metric_code} has multiple definition versions {versions}; "
                    "pass --version"
                )
            if definition_version is None and len(matches) == 1:
                return matches
            if definition_version is not None:
                return matches
            git_matches = [d for d in registry.definitions if d.metric_code == metric_code]
            if len(git_matches) == 1:
                return (git_matches[0],)
            if len(git_matches) > 1:
                versions = sorted(d.definition_version for d in git_matches)
                raise ValueError(
                    f"metric {metric_code} has multiple definition versions {versions}; "
                    "pass --version"
                )
            return matches

    def list_mappings(
        self,
        *,
        metric_code: str | None = None,
        concept_namespace_uri: str | None = None,
        concept_local_name: str | None = None,
        cik: str | None = None,
        relationship_type: str | None = None,
    ) -> tuple[MappingRuleRow, ...]:
        registry = self.load_git_registry()
        engine = self._require_engine()
        with engine.connect() as conn:
            self._require_synced(conn, registry)
            return list_mappings(
                conn,
                metric_code=metric_code,
                concept_namespace_uri=concept_namespace_uri,
                concept_local_name=concept_local_name,
                cik=cik,
                relationship_type=relationship_type,
            )

    def get_mapping(self, rule_key: str) -> MappingRuleRow | None:
        registry = self.load_git_registry()
        engine = self._require_engine()
        with engine.connect() as conn:
            self._require_synced(conn, registry)
            return get_mapping(conn, rule_key)

    def get_supersession_chain(self, rule_key: str) -> tuple[MappingRuleRecord, ...]:
        registry = self.load_git_registry()
        engine = self._require_engine()
        with engine.connect() as conn:
            self._require_synced(conn, registry)
            return get_supersession_chain(conn, rule_key)

    def query_source_fact_occurrences(
        self,
        *,
        namespace_uri: str,
        local_name: str,
        limit: int | None = None,
    ) -> tuple[SourceFactOccurrence, ...]:
        registry = self.load_git_registry()
        engine = self._require_engine()
        with engine.connect() as conn:
            self._require_synced(conn, registry)
            return query_source_fact_occurrences(
                conn,
                namespace_uri=namespace_uri,
                local_name=local_name,
                limit=limit,
            )

    def latest_revision(self) -> RegistryRevisionRow | None:
        engine = self._require_engine()
        with engine.connect() as conn:
            return get_latest_revision(conn)

    def explain_mapping(self, rule_key: str) -> dict[str, object]:
        from edgar.metrics.export import mapping_rule_audit_payload

        registry = self.load_git_registry()
        engine = self._require_engine()
        with engine.connect() as conn:
            self._require_synced(conn, registry)
            row = get_mapping(conn, rule_key)
            if row is None:
                raise KeyError(f"unknown mapping rule: {rule_key}")
            chain = get_supersession_chain(conn, rule_key)
            ns = row.rule.source_concept.namespace_uri or ""
            occurrences = query_source_fact_occurrences(
                conn,
                namespace_uri=ns,
                local_name=row.rule.source_concept.local_name,
                limit=50,
            )
            return mapping_rule_audit_payload(
                row,
                supersession_chain=chain,
                source_occurrences=occurrences,
            )

    def export_mappings_audit(self) -> list[dict[str, object]]:
        from edgar.metrics.export import mapping_rule_audit_payload

        registry = self.load_git_registry()
        engine = self._require_engine()
        reports: list[dict[str, object]] = []
        with engine.connect() as conn:
            self._require_synced(conn, registry)
            for row in list_mappings(conn):
                chain = get_supersession_chain(conn, row.rule.rule_key)
                ns = row.rule.source_concept.namespace_uri or ""
                occurrences = query_source_fact_occurrences(
                    conn,
                    namespace_uri=ns,
                    local_name=row.rule.source_concept.local_name,
                    limit=20,
                )
                reports.append(
                    mapping_rule_audit_payload(
                        row,
                        supersession_chain=chain,
                        source_occurrences=occurrences,
                    )
                )
        return reports
