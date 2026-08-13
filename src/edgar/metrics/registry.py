"""Git-authoritative metric ontology and curated mapping registry (lean Phase 2A)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

from edgar.domain.identifiers import validate_accession, validate_cik

REGISTRY_SCHEMA_VERSION = 1
DEFINITION_SCHEMA_VERSION = 1
RULE_SCHEMA_VERSION = 1

RelationshipType = Literal[
    "equivalent",
    "issuer_equivalent",
    "narrower_than",
    "broader_than",
    "component_of",
    "derived_equivalent",
    "presentation_alias",
    "proxy_for",
    "incompatible",
    "unresolved",
]
ScopeKind = Literal["global", "issuer", "issuer_period", "filing"]
ConfidenceTier = Literal["high", "medium", "low"]
PeriodType = Literal["instant", "duration"]
RuleState = Literal["current", "superseded"]
DimensionPolicy = Literal["undimensioned_only"]

RELATIONSHIP_TYPES = frozenset(
    {
        "equivalent",
        "issuer_equivalent",
        "narrower_than",
        "broader_than",
        "component_of",
        "derived_equivalent",
        "presentation_alias",
        "proxy_for",
        "incompatible",
        "unresolved",
    }
)
AGGREGATION_BEHAVIORS = frozenset(
    {
        "additive_over_disjoint_periods",
        "point_in_time_balance",
        "non_additive_per_share",
        "point_in_time_count",
        "weighted_average_non_additive",
    }
)

FAMILIES_FILENAME = "metric-families.json"
DEFINITIONS_FILENAME = "metric-definitions.json"
RULES_FILENAME = "mapping-rules.json"
_HEX64 = frozenset("0123456789abcdef")


class RegistryValidationError(ValueError):
    """Raised when registry content fails cross-record or semantic validation."""


class ExpandedQNameRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace_uri: str | None = None
    local_name: str

    @field_validator("local_name")
    @classmethod
    def _local_name(cls, value: str) -> str:
        if not value:
            raise ValueError("local_name must be non-empty")
        if any(ch in value for ch in ":{}/ \t\r\n"):
            raise ValueError(f"local_name is not an NCName: {value!r}")
        return value


class MetricFamilyRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    name: str
    description: str
    parent_code: str | None = None


class DefinitionConstraints(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    inclusion_rules: tuple[str, ...]
    exclusion_rules: tuple[str, ...]
    statement_expectations: tuple[str, ...] = ()
    industry_applicability: tuple[str, ...] = ()
    aggregation_behavior: str
    derivation_policy: str
    notes: str | None = None


class MetricDefinitionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    definition_schema_version: int
    metric_code: str
    definition_version: int
    family_code: str
    name: str
    economic_definition: str
    accounting_basis: str
    period_type: PeriodType
    value_kind: str
    unit_kind: str
    entity_scope: str
    dimension_policy: DimensionPolicy
    sign_convention: str
    constraints: DefinitionConstraints


class GlobalScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["global"] = "global"


class IssuerScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["issuer"] = "issuer"
    cik: str

    @field_validator("cik")
    @classmethod
    def _cik(cls, value: str) -> str:
        normalized = validate_cik(value)
        if value != normalized:
            raise ValueError(f"cik must be zero-padded: {value!r}")
        return normalized


class IssuerPeriodScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["issuer_period"] = "issuer_period"
    cik: str
    report_period_from: date
    report_period_through: date

    @field_validator("cik")
    @classmethod
    def _cik(cls, value: str) -> str:
        normalized = validate_cik(value)
        if value != normalized:
            raise ValueError(f"cik must be zero-padded: {value!r}")
        return normalized

    @model_validator(mode="after")
    def _period_order(self) -> Self:
        if self.report_period_from > self.report_period_through:
            raise ValueError("report_period_from must be <= report_period_through")
        return self


class FilingScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["filing"] = "filing"
    accession_number: str

    @field_validator("accession_number")
    @classmethod
    def _accession(cls, value: str) -> str:
        normalized = validate_accession(value)
        if value != normalized:
            raise ValueError(f"accession must be canonical dashed form: {value!r}")
        return normalized


MappingScope = Annotated[
    GlobalScope | IssuerScope | IssuerPeriodScope | FilingScope,
    Field(discriminator="kind"),
]


class EvidenceSnapshot(RootModel[dict[str, Any]]):
    @model_validator(mode="after")
    def _non_empty(self) -> Self:
        if not self.root:
            raise ValueError("evidence_snapshot must be non-empty")
        return self


class ProjectionConceptEvidence(BaseModel):
    """Pinned semantic projection evidence (v1 only evidence type)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accession_number: str
    bundle_fingerprint: str
    projection_version: str
    arelle_version: str
    semantic_config_fingerprint: str
    concept: ExpandedQNameRecord

    @field_validator("accession_number")
    @classmethod
    def _accession(cls, value: str) -> str:
        normalized = validate_accession(value)
        if value != normalized:
            raise ValueError(f"accession must be canonical dashed form: {value!r}")
        return normalized

    @field_validator("bundle_fingerprint", "semantic_config_fingerprint")
    @classmethod
    def _hex64(cls, value: str) -> str:
        if len(value) != 64 or any(c not in _HEX64 for c in value):
            raise ValueError(f"invalid fingerprint: {value!r}")
        return value


class SupersedesRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_key: str


class MappingRuleRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_schema_version: int
    rule_key: str
    source_concept: ExpandedQNameRecord
    target_metric_code: str
    target_definition_version: int
    relationship_type: RelationshipType
    scope_kind: ScopeKind
    scope: MappingScope
    confidence_tier: ConfidenceTier
    rationale: str
    evidence_snapshot: EvidenceSnapshot
    evidence: ProjectionConceptEvidence
    reviewed_by: str
    reviewed_at: datetime
    supersedes: SupersedesRef | None = None

    @field_validator("reviewed_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _scope_kind_matches(self) -> Self:
        if self.scope_kind != self.scope.kind:
            raise ValueError("scope_kind does not match scope.kind")
        return self


class FamiliesFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_schema_version: int
    families: tuple[MetricFamilyRecord, ...]


class DefinitionsFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_schema_version: int
    definitions: tuple[MetricDefinitionRecord, ...]


class RulesFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_schema_version: int
    rules: tuple[MappingRuleRecord, ...]


class LoadedRegistry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_schema_version: int
    families: tuple[MetricFamilyRecord, ...]
    definitions: tuple[MetricDefinitionRecord, ...]
    rules: tuple[MappingRuleRecord, ...]
    registry_hash: str


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonicalize_qname(qname: ExpandedQNameRecord) -> dict[str, Any]:
    return {"local_name": qname.local_name, "namespace_uri": qname.namespace_uri}


def _qnames_equal(left: ExpandedQNameRecord, right: ExpandedQNameRecord) -> bool:
    return left.namespace_uri == right.namespace_uri and left.local_name == right.local_name


def _canonicalize_scope(scope: MappingScope) -> dict[str, Any]:
    if isinstance(scope, GlobalScope):
        return {"kind": scope.kind}
    if isinstance(scope, IssuerScope):
        return {"cik": scope.cik, "kind": scope.kind}
    if isinstance(scope, IssuerPeriodScope):
        return {
            "cik": scope.cik,
            "kind": scope.kind,
            "report_period_from": scope.report_period_from.isoformat(),
            "report_period_through": scope.report_period_through.isoformat(),
        }
    scope = cast(FilingScope, scope)
    return {"accession_number": scope.accession_number, "kind": scope.kind}


def _canonicalize_constraints(constraints: DefinitionConstraints) -> dict[str, Any]:
    return {
        "aggregation_behavior": constraints.aggregation_behavior,
        "derivation_policy": constraints.derivation_policy,
        "exclusion_rules": sorted(constraints.exclusion_rules),
        "inclusion_rules": sorted(constraints.inclusion_rules),
        "industry_applicability": sorted(constraints.industry_applicability),
        "notes": constraints.notes,
        "statement_expectations": sorted(constraints.statement_expectations),
    }


def _canonicalize_definition(defn: MetricDefinitionRecord) -> dict[str, Any]:
    return {
        "accounting_basis": defn.accounting_basis,
        "constraints": _canonicalize_constraints(defn.constraints),
        "definition_schema_version": defn.definition_schema_version,
        "definition_version": defn.definition_version,
        "dimension_policy": defn.dimension_policy,
        "economic_definition": defn.economic_definition,
        "entity_scope": defn.entity_scope,
        "family_code": defn.family_code,
        "metric_code": defn.metric_code,
        "name": defn.name,
        "period_type": defn.period_type,
        "sign_convention": defn.sign_convention,
        "unit_kind": defn.unit_kind,
        "value_kind": defn.value_kind,
    }


def _canonicalize_evidence(evidence: ProjectionConceptEvidence) -> dict[str, Any]:
    return {
        "accession_number": evidence.accession_number,
        "arelle_version": evidence.arelle_version,
        "bundle_fingerprint": evidence.bundle_fingerprint,
        "concept": _canonicalize_qname(evidence.concept),
        "projection_version": evidence.projection_version,
        "semantic_config_fingerprint": evidence.semantic_config_fingerprint,
    }


def _canonicalize_rule(rule: MappingRuleRecord) -> dict[str, Any]:
    return {
        "confidence_tier": rule.confidence_tier,
        "evidence": _canonicalize_evidence(rule.evidence),
        "evidence_snapshot": dict(sorted(rule.evidence_snapshot.root.items())),
        "rationale": rule.rationale,
        "relationship_type": rule.relationship_type,
        "reviewed_at": rule.reviewed_at.astimezone(UTC).isoformat(),
        "reviewed_by": rule.reviewed_by,
        "rule_key": rule.rule_key,
        "rule_schema_version": rule.rule_schema_version,
        "scope": _canonicalize_scope(rule.scope),
        "scope_kind": rule.scope_kind,
        "source_concept": _canonicalize_qname(rule.source_concept),
        "supersedes": None if rule.supersedes is None else {"rule_key": rule.supersedes.rule_key},
        "target_definition_version": rule.target_definition_version,
        "target_metric_code": rule.target_metric_code,
    }


def fingerprint_registry_content(
    *,
    families: Sequence[MetricFamilyRecord],
    definitions: Sequence[MetricDefinitionRecord],
    rules: Sequence[MappingRuleRecord],
) -> str:
    sorted_definitions = sorted(definitions, key=lambda d: (d.metric_code, d.definition_version))
    payload = {
        "definitions": [_canonicalize_definition(d) for d in sorted_definitions],
        "families": [
            {
                "code": f.code,
                "description": f.description,
                "name": f.name,
                "parent_code": f.parent_code,
            }
            for f in sorted(families, key=lambda f: f.code)
        ],
        "rules": [_canonicalize_rule(r) for r in sorted(rules, key=lambda r: r.rule_key)],
    }
    return sha256_hex(canonical_json_bytes(payload))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_registry(registry_dir: Path) -> LoadedRegistry:
    families_file = FamiliesFile.model_validate(_load_json(registry_dir / FAMILIES_FILENAME))
    definitions_file = DefinitionsFile.model_validate(
        _load_json(registry_dir / DEFINITIONS_FILENAME)
    )
    rules_file = RulesFile.model_validate(_load_json(registry_dir / RULES_FILENAME))
    versions = {
        families_file.registry_schema_version,
        definitions_file.registry_schema_version,
        rules_file.registry_schema_version,
    }
    if len(versions) != 1 or next(iter(versions)) != REGISTRY_SCHEMA_VERSION:
        raise RegistryValidationError(f"unsupported registry_schema_version: {versions}")
    registry_hash = fingerprint_registry_content(
        families=families_file.families,
        definitions=definitions_file.definitions,
        rules=rules_file.rules,
    )
    return LoadedRegistry(
        registry_schema_version=REGISTRY_SCHEMA_VERSION,
        families=families_file.families,
        definitions=definitions_file.definitions,
        rules=rules_file.rules,
        registry_hash=registry_hash,
    )


def rule_state(rule_key: str, rules: Mapping[str, MappingRuleRecord]) -> RuleState:
    for rule in rules.values():
        if rule.supersedes is not None and rule.supersedes.rule_key == rule_key:
            return "superseded"
    return "current"


def _expected_aggregation(period_type: str, value_kind: str) -> str:
    if value_kind == "per_share":
        return "non_additive_per_share"
    if value_kind == "shares":
        if period_type == "instant":
            return "point_in_time_count"
        return "weighted_average_non_additive"
    if period_type == "instant":
        return "point_in_time_balance"
    return "additive_over_disjoint_periods"


def validate_registry(registry: LoadedRegistry) -> None:
    families_by_code = {f.code: f for f in registry.families}
    if len(families_by_code) != len(registry.families):
        raise RegistryValidationError("duplicate family code")

    definitions_by_key = {(d.metric_code, d.definition_version): d for d in registry.definitions}
    if len(definitions_by_key) != len(registry.definitions):
        raise RegistryValidationError("duplicate metric definition key")

    rules_by_key = {r.rule_key: r for r in registry.rules}
    if len(rules_by_key) != len(registry.rules):
        raise RegistryValidationError("duplicate rule_key")

    for defn in registry.definitions:
        if defn.family_code not in families_by_code:
            raise RegistryValidationError(f"unknown family_code for {defn.metric_code}")
        expected = _expected_aggregation(defn.period_type, defn.value_kind)
        if defn.constraints.aggregation_behavior != expected:
            raise RegistryValidationError(
                f"{defn.metric_code}: aggregation_behavior must be {expected!r}, "
                f"got {defn.constraints.aggregation_behavior!r}"
            )
        if defn.constraints.aggregation_behavior not in AGGREGATION_BEHAVIORS:
            raise RegistryValidationError(f"{defn.metric_code}: invalid aggregation_behavior")

    for rule in registry.rules:
        if rule.rule_schema_version != RULE_SCHEMA_VERSION:
            raise RegistryValidationError(f"{rule.rule_key}: unsupported rule_schema_version")
        if rule.relationship_type not in RELATIONSHIP_TYPES:
            raise RegistryValidationError(f"{rule.rule_key}: invalid relationship_type")
        if rule.relationship_type == "issuer_equivalent" and rule.scope_kind == "global":
            raise RegistryValidationError(
                f"{rule.rule_key}: issuer_equivalent cannot use global scope"
            )
        if (rule.target_metric_code, rule.target_definition_version) not in definitions_by_key:
            raise RegistryValidationError(f"{rule.rule_key}: unknown target metric definition")
        if not _qnames_equal(rule.evidence.concept, rule.source_concept):
            raise RegistryValidationError(
                f"{rule.rule_key}: evidence.concept must match source_concept"
            )
        if rule.supersedes is not None and rule.supersedes.rule_key not in rules_by_key:
            raise RegistryValidationError(f"{rule.rule_key}: unknown supersedes target")

    for rule_key in rules_by_key:
        if rule_state(rule_key, rules_by_key) == "current":
            continue
        # superseded rules remain in JSON for audit; no further checks
