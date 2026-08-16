"""Git-authoritative metric ontology and curated mapping registry (lean Phase 2A)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationInfo,
    field_validator,
    model_validator,
)

from edgar.domain.identifiers import accession_to_cik, validate_accession, validate_cik

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
AccountingBasis = Literal["us_gaap"]
DerivationPolicy = Literal["direct_only"]
ValueKind = Literal["monetary", "per_share", "shares"]
UnitKind = Literal["currency", "currency_per_share", "shares"]
EntityScope = Literal["consolidated"]
AggregationBehavior = Literal[
    "additive_over_disjoint_periods",
    "point_in_time_balance",
    "non_additive_per_share",
    "point_in_time_count",
    "weighted_average_non_additive",
]

FAMILIES_FILENAME = "metric-families.json"
DEFINITIONS_FILENAME = "metric-definitions.json"
RULES_FILENAME = "mapping-rules.json"
_HEX64 = frozenset("0123456789abcdef")
_V1_REJECTED_RELATIONSHIPS = frozenset({"derived_equivalent"})
PENDING_REVIEW_SENTINEL = "__pending_review__"

EXPECTED_V1_METRICS = frozenset(
    {
        "operating_company_revenue",
        "gross_profit",
        "operating_income",
        "pretax_income",
        "net_income_attributable_to_parent",
        "diluted_eps",
        "operating_cash_flow",
        "cash_purchases_of_ppe",
        "cash_and_cash_equivalents",
        "short_term_borrowings",
        "current_portion_long_term_debt",
        "long_term_debt_noncurrent",
        "stockholders_equity_attributable_to_parent",
        "shares_outstanding_period_end",
        "weighted_average_diluted_shares",
        "stock_based_compensation",
        "research_and_development_expense",
        "selling_general_and_administrative_expense",
        "cash_dividends_paid",
        "cash_share_repurchases",
    }
)


class RegistryValidationError(ValueError):
    """Raised when registry content fails cross-record or semantic validation."""


def _non_empty_str(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


class ExpandedQNameRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace_uri: str
    local_name: str

    @field_validator("namespace_uri", "local_name")
    @classmethod
    def _nonblank(cls, value: str, info: ValidationInfo) -> str:
        return _non_empty_str(value, str(info.field_name))

    @model_validator(mode="after")
    def _ncname(self) -> Self:
        if any(ch in self.local_name for ch in ":{}/ \t\r\n"):
            raise ValueError(f"local_name is not an NCName: {self.local_name!r}")
        return self


class MetricFamilyRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    name: str
    description: str
    parent_code: str | None = None

    @field_validator("code", "name", "description")
    @classmethod
    def _nonblank(cls, value: str, info: ValidationInfo) -> str:
        return _non_empty_str(value, str(info.field_name))

    @field_validator("parent_code")
    @classmethod
    def _parent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _non_empty_str(value, "parent_code")


class DefinitionConstraints(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    inclusion_rules: tuple[str, ...] = Field(min_length=1)
    exclusion_rules: tuple[str, ...] = Field(min_length=1)
    statement_expectations: tuple[str, ...] = ()
    industry_applicability: tuple[str, ...] = ()
    aggregation_behavior: AggregationBehavior
    derivation_policy: DerivationPolicy
    notes: str | None = None

    @field_validator(
        "inclusion_rules",
        "exclusion_rules",
        "statement_expectations",
        "industry_applicability",
    )
    @classmethod
    def _rule_entries(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        field_name = str(info.field_name)
        for entry in value:
            _non_empty_str(entry, field_name)
        if len(set(value)) != len(value):
            raise ValueError(f"duplicate entries in {field_name}")
        return value

    @field_validator("notes")
    @classmethod
    def _notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _non_empty_str(value, "notes")


class MetricDefinitionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_code: str
    definition_version: int = Field(gt=0)
    family_code: str
    name: str
    economic_definition: str
    accounting_basis: AccountingBasis
    period_type: PeriodType
    value_kind: ValueKind
    unit_kind: UnitKind
    entity_scope: EntityScope
    dimension_policy: DimensionPolicy
    sign_convention: str
    constraints: DefinitionConstraints

    @field_validator(
        "metric_code",
        "family_code",
        "name",
        "economic_definition",
        "sign_convention",
    )
    @classmethod
    def _nonblank(cls, value: str, info: ValidationInfo) -> str:
        return _non_empty_str(value, str(info.field_name))

    @model_validator(mode="after")
    def _value_unit_coherence(self) -> Self:
        expected: dict[ValueKind, UnitKind] = {
            "monetary": "currency",
            "per_share": "currency_per_share",
            "shares": "shares",
        }
        if self.unit_kind != expected[self.value_kind]:
            raise ValueError(
                f"{self.metric_code}: value_kind {self.value_kind!r} requires "
                f"unit_kind {expected[self.value_kind]!r}, got {self.unit_kind!r}"
            )
        return self


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

    @field_validator("projection_version", "arelle_version")
    @classmethod
    def _nonblank(cls, value: str, info: ValidationInfo) -> str:
        return _non_empty_str(value, str(info.field_name))

    @field_validator("bundle_fingerprint", "semantic_config_fingerprint")
    @classmethod
    def _hex64(cls, value: str) -> str:
        if len(value) != 64 or any(c not in _HEX64 for c in value):
            raise ValueError(f"invalid fingerprint: {value!r}")
        return value


class SupersedesRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_key: str

    @field_validator("rule_key")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        return _non_empty_str(value, "rule_key")


class MappingRuleRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_key: str
    source_concept: ExpandedQNameRecord
    target_metric_code: str
    target_definition_version: int = Field(gt=0)
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

    @field_validator("rule_key", "target_metric_code", "rationale", "reviewed_by")
    @classmethod
    def _nonblank(cls, value: str, info: ValidationInfo) -> str:
        return _non_empty_str(value, str(info.field_name))

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

    families: tuple[MetricFamilyRecord, ...]


class DefinitionsFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    definitions: tuple[MetricDefinitionRecord, ...]


class RulesFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rules: tuple[MappingRuleRecord, ...]


class LoadedRegistry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

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


def _qnames_equal(left: ExpandedQNameRecord, right: ExpandedQNameRecord) -> bool:
    return left.namespace_uri == right.namespace_uri and left.local_name == right.local_name


def _constraints_for_hash(constraints: DefinitionConstraints) -> dict[str, Any]:
    dumped = constraints.model_dump(mode="json")
    for key in (
        "inclusion_rules",
        "exclusion_rules",
        "statement_expectations",
        "industry_applicability",
    ):
        dumped[key] = sorted(dumped[key])
    return dumped


def _definition_for_hash(defn: MetricDefinitionRecord) -> dict[str, Any]:
    payload = defn.model_dump(mode="json")
    payload["constraints"] = _constraints_for_hash(defn.constraints)
    return payload


def _rule_for_hash(rule: MappingRuleRecord) -> dict[str, Any]:
    payload = rule.model_dump(mode="json")
    payload["reviewed_at"] = rule.reviewed_at.astimezone(UTC).isoformat()
    payload["evidence_snapshot"] = dict(sorted(rule.evidence_snapshot.root.items()))
    return payload


def fingerprint_registry_content(
    *,
    families: Sequence[MetricFamilyRecord],
    definitions: Sequence[MetricDefinitionRecord],
    rules: Sequence[MappingRuleRecord],
) -> str:
    payload = {
        "definitions": [
            _definition_for_hash(d)
            for d in sorted(
                definitions,
                key=lambda item: (item.metric_code, item.definition_version),
            )
        ],
        "families": [
            f.model_dump(mode="json") for f in sorted(families, key=lambda item: item.code)
        ],
        "rules": [_rule_for_hash(r) for r in sorted(rules, key=lambda item: item.rule_key)],
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
    registry_hash = fingerprint_registry_content(
        families=families_file.families,
        definitions=definitions_file.definitions,
        rules=rules_file.rules,
    )
    return LoadedRegistry(
        families=families_file.families,
        definitions=definitions_file.definitions,
        rules=rules_file.rules,
        registry_hash=registry_hash,
    )


def rule_state(rule_key: str, rules: Mapping[str, MappingRuleRecord]) -> RuleState:
    if rule_key not in rules:
        raise KeyError(f"unknown mapping rule: {rule_key}")
    for rule in rules.values():
        if rule.supersedes is not None and rule.supersedes.rule_key == rule_key:
            return "superseded"
    return "current"


def predecessor_chain(
    rule_key: str, rules_by_key: Mapping[str, MappingRuleRecord]
) -> tuple[MappingRuleRecord, ...]:
    if rule_key not in rules_by_key:
        raise KeyError(f"unknown mapping rule: {rule_key}")
    chain: list[MappingRuleRecord] = []
    seen: set[str] = set()
    current_key: str | None = rule_key
    while current_key is not None:
        if current_key in seen:
            raise RegistryValidationError(f"supersession cycle detected at {current_key!r}")
        seen.add(current_key)
        current = rules_by_key[current_key]
        chain.insert(0, current)
        current_key = None if current.supersedes is None else current.supersedes.rule_key
    return tuple(chain)


def scope_cik(scope: MappingScope) -> str | None:
    """Issuer CIK encoded by the rule's explicit stored scope, if any."""
    if isinstance(scope, FilingScope):
        return accession_to_cik(scope.accession_number)
    return getattr(scope, "cik", None)


def _expected_aggregation(period_type: PeriodType, value_kind: ValueKind) -> AggregationBehavior:
    if value_kind == "per_share":
        return "non_additive_per_share"
    if value_kind == "shares":
        if period_type == "instant":
            return "point_in_time_count"
        return "weighted_average_non_additive"
    if period_type == "instant":
        return "point_in_time_balance"
    return "additive_over_disjoint_periods"


def _validate_family_graph(families_by_code: Mapping[str, MetricFamilyRecord]) -> None:
    for family in families_by_code.values():
        if family.parent_code is None:
            continue
        if family.parent_code == family.code:
            raise RegistryValidationError(f"family {family.code} cannot be its own parent")
        if family.parent_code not in families_by_code:
            raise RegistryValidationError(f"family {family.code} has unknown parent_code")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(code: str) -> None:
        if code in visited:
            return
        if code in visiting:
            raise RegistryValidationError(f"family parent cycle detected at {code!r}")
        visiting.add(code)
        parent = families_by_code[code].parent_code
        if parent is not None:
            visit(parent)
        visiting.remove(code)
        visited.add(code)

    for code in families_by_code:
        visit(code)


def _validate_supersession_graph(rules_by_key: Mapping[str, MappingRuleRecord]) -> None:
    for rule in rules_by_key.values():
        if rule.supersedes is None:
            continue
        predecessor_key = rule.supersedes.rule_key
        if predecessor_key == rule.rule_key:
            raise RegistryValidationError(f"{rule.rule_key}: cannot supersede itself")
        if predecessor_key not in rules_by_key:
            raise RegistryValidationError(f"{rule.rule_key}: unknown supersedes target")
        predecessor = rules_by_key[predecessor_key]
        if not _qnames_equal(rule.source_concept, predecessor.source_concept):
            raise RegistryValidationError(
                f"{rule.rule_key}: source_concept must match predecessor {predecessor_key}"
            )
    for rule_key in rules_by_key:
        predecessor_chain(rule_key, rules_by_key)


def _validate_scope_evidence_coherence(rule: MappingRuleRecord) -> None:
    evidence_accession = rule.evidence.accession_number
    scope = rule.scope
    if isinstance(scope, FilingScope):
        if scope.accession_number != evidence_accession:
            raise RegistryValidationError(
                f"{rule.rule_key}: filing scope accession must match evidence.accession_number"
            )
        return
    if isinstance(scope, (IssuerScope, IssuerPeriodScope)):
        evidence_cik = accession_to_cik(evidence_accession)
        if scope.cik != evidence_cik:
            raise RegistryValidationError(
                f"{rule.rule_key}: scope.cik must match CIK encoded by evidence.accession_number"
            )


def validate_registry(registry: LoadedRegistry) -> None:
    families_by_code = {f.code: f for f in registry.families}
    if len(families_by_code) != len(registry.families):
        raise RegistryValidationError("duplicate family code")
    _validate_family_graph(families_by_code)

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

    for rule in registry.rules:
        if rule.relationship_type in _V1_REJECTED_RELATIONSHIPS:
            raise RegistryValidationError(
                f"{rule.rule_key}: relationship_type {rule.relationship_type!r} "
                "is not allowed in v1"
            )
        if rule.relationship_type == "issuer_equivalent" and rule.scope_kind not in {
            "issuer_period",
            "filing",
        }:
            raise RegistryValidationError(
                f"{rule.rule_key}: issuer_equivalent requires issuer_period or filing scope"
            )
        if (rule.target_metric_code, rule.target_definition_version) not in definitions_by_key:
            raise RegistryValidationError(f"{rule.rule_key}: unknown target metric definition")
        if not _qnames_equal(rule.evidence.concept, rule.source_concept):
            raise RegistryValidationError(
                f"{rule.rule_key}: evidence.concept must match source_concept"
            )
        _validate_scope_evidence_coherence(rule)

    if rules_by_key:
        _validate_supersession_graph(rules_by_key)
