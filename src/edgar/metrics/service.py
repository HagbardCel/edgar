"""Application service: Git-authoritative metric registry (lean Phase 2A)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from edgar.config import Settings
from edgar.db.engine import create_db_engine
from edgar.db.mapping_evidence import (
    MappingEvidenceError,
    enrich_pinned_evidence,
    enrichment_to_payload,
    resolve_pinned_concept,
)
from edgar.metrics.export import export_registry_audit, mapping_rule_audit_payload
from edgar.metrics.registry import (
    IssuerPeriodScope,
    LoadedRegistry,
    MappingRuleRecord,
    MetricDefinitionRecord,
    MetricFamilyRecord,
    RuleState,
    load_registry,
    predecessor_chain,
    rule_state,
    scope_cik,
    validate_registry,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_REGISTRY_DIR = _REPO_ROOT / "semantic-registry"


@dataclass(frozen=True)
class MappingRuleView:
    rule: MappingRuleRecord
    state: RuleState


class MetricRegistryService:
    """Load and query the Git semantic registry; explain resolves pinned evidence only."""

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

    def _rules_by_key(self, registry: LoadedRegistry) -> dict[str, MappingRuleRecord]:
        return {rule.rule_key: rule for rule in registry.rules}

    def list_families(self) -> tuple[MetricFamilyRecord, ...]:
        return self.load_git_registry().families

    def list_metrics(self) -> tuple[MetricDefinitionRecord, ...]:
        registry = self.load_git_registry()
        return tuple(
            sorted(registry.definitions, key=lambda d: (d.metric_code, d.definition_version))
        )

    def get_metric(
        self,
        metric_code: str,
        *,
        definition_version: int | None = None,
        registry: LoadedRegistry | None = None,
    ) -> tuple[MetricDefinitionRecord, ...]:
        loaded = registry if registry is not None else self.load_git_registry()
        matches = [
            d
            for d in loaded.definitions
            if d.metric_code == metric_code
            and (definition_version is None or d.definition_version == definition_version)
        ]
        if definition_version is None and len(matches) > 1:
            versions = sorted(d.definition_version for d in matches)
            raise ValueError(
                f"metric {metric_code} has multiple definition versions {versions}; pass --version"
            )
        return tuple(matches)

    def list_mappings(
        self,
        *,
        metric_code: str | None = None,
        concept_local_name: str | None = None,
        cik: str | None = None,
        relationship_type: str | None = None,
        registry: LoadedRegistry | None = None,
    ) -> tuple[MappingRuleView, ...]:
        loaded = registry if registry is not None else self.load_git_registry()
        rules_by_key = self._rules_by_key(loaded)
        views: list[MappingRuleView] = []
        for rule in loaded.rules:
            if metric_code is not None and rule.target_metric_code != metric_code:
                continue
            if (
                concept_local_name is not None
                and rule.source_concept.local_name != concept_local_name
            ):
                continue
            if relationship_type is not None and rule.relationship_type != relationship_type:
                continue
            if cik is not None and scope_cik(rule.scope) != cik:
                continue
            views.append(MappingRuleView(rule=rule, state=rule_state(rule.rule_key, rules_by_key)))
        return tuple(sorted(views, key=lambda v: v.rule.rule_key))

    def get_mapping(
        self,
        rule_key: str,
        *,
        registry: LoadedRegistry | None = None,
    ) -> MappingRuleView | None:
        loaded = registry if registry is not None else self.load_git_registry()
        rules_by_key = self._rules_by_key(loaded)
        rule = rules_by_key.get(rule_key)
        if rule is None:
            return None
        return MappingRuleView(rule=rule, state=rule_state(rule_key, rules_by_key))

    def get_predecessor_chain(
        self,
        rule_key: str,
        *,
        registry: LoadedRegistry | None = None,
    ) -> tuple[MappingRuleRecord, ...]:
        loaded = registry if registry is not None else self.load_git_registry()
        return predecessor_chain(rule_key, self._rules_by_key(loaded))

    def _assert_issuer_period_evidence(
        self,
        rule: MappingRuleRecord,
        *,
        report_period_end: date | None,
    ) -> None:
        if not isinstance(rule.scope, IssuerPeriodScope):
            return
        if report_period_end is None:
            raise MappingEvidenceError(
                f"{rule.rule_key}: issuer_period evidence requires non-null "
                "filing.report_period_end"
            )
        if not (
            rule.scope.report_period_from <= report_period_end <= rule.scope.report_period_through
        ):
            raise MappingEvidenceError(
                f"{rule.rule_key}: filing.report_period_end {report_period_end.isoformat()} "
                "is outside issuer_period scope "
                f"[{rule.scope.report_period_from.isoformat()}, "
                f"{rule.scope.report_period_through.isoformat()}]"
            )

    def explain_mapping(self, rule_key: str) -> dict[str, Any]:
        registry = self.load_git_registry()
        rules_by_key = self._rules_by_key(registry)
        rule = rules_by_key.get(rule_key)
        if rule is None:
            raise KeyError(f"unknown mapping rule: {rule_key}")
        state = rule_state(rule_key, rules_by_key)
        chain = predecessor_chain(rule_key, rules_by_key)
        engine = self._require_engine()
        with engine.connect() as conn:
            try:
                pinned = resolve_pinned_concept(conn, rule.evidence)
                self._assert_issuer_period_evidence(
                    rule, report_period_end=pinned.report_period_end
                )
                enrichment = enrich_pinned_evidence(conn, pinned)
                enrichment_payload = enrichment_to_payload(enrichment)
            except MappingEvidenceError as exc:
                raise MappingEvidenceError(
                    f"pinned evidence resolution failed for {rule_key}: {exc}"
                ) from exc
        return mapping_rule_audit_payload(
            rule,
            state=state,
            supersession_chain=chain,
            registry_hash=registry.registry_hash,
            pinned_evidence=enrichment_payload,
        )

    def export_mappings_audit(self) -> dict[str, Any]:
        registry = self.load_git_registry()
        return export_registry_audit(
            registry_hash=registry.registry_hash,
            rules=registry.rules,
        )

    def export_mappings_audit_markdown(self) -> str:
        from edgar.metrics.export import export_registry_audit_markdown

        registry = self.load_git_registry()
        return export_registry_audit_markdown(
            registry_hash=registry.registry_hash,
            rules=registry.rules,
        )
