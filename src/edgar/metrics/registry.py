"""Git-authoritative metric ontology and curated mapping registry (Phase 2A).

Pure validation, canonicalization, and hashing — no database or network I/O.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator,
    model_validator,
)

from edgar.domain.identifiers import validate_accession, validate_cik, validate_uuid4_hex

# ---------------------------------------------------------------------------
# Schema versions and vocabularies
# ---------------------------------------------------------------------------

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
LocatorScheme = Literal["xml_id", "unqualified_id", "expanded_element_path"]
NetworkType = Literal["presentation", "calculation", "definition"]
CitationKind = Literal[
    "concept_declaration",
    "fact",
    "relationship",
    "label",
    "reference",
    "raw_artifact",
]

RELATIONSHIP_TYPES: frozenset[str] = frozenset(
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

SCOPE_KINDS: frozenset[str] = frozenset({"global", "issuer", "issuer_period", "filing"})
CONFIDENCE_TIERS: frozenset[str] = frozenset({"high", "medium", "low"})
PERIOD_TYPES: frozenset[str] = frozenset({"instant", "duration"})

FAMILIES_FILENAME = "metric-families.json"
DEFINITIONS_FILENAME = "metric-definitions.json"
RULES_FILENAME = "mapping-rules.json"

_HEX64 = frozenset("0123456789abcdef")


class RegistryValidationError(ValueError):
    """Raised when registry content fails cross-record or semantic validation."""


# ---------------------------------------------------------------------------
# Shared record types
# ---------------------------------------------------------------------------


class ExpandedQNameRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace_uri: str | None = None
    local_name: str

    @field_validator("local_name")
    @classmethod
    def _non_empty_local_name(cls, value: str) -> str:
        if not value:
            raise ValueError("local_name must be non-empty")
        if any(ch in value for ch in ":{}/ \t\r\n"):
            raise ValueError(f"local_name is not an NCName: {value!r}")
        return value

    @field_validator("namespace_uri")
    @classmethod
    def _namespace_uri(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("namespace_uri must be None or non-empty")
        return value


class SourceLocatorRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_uri: str
    scheme: LocatorScheme
    value: str

    @field_validator("value")
    @classmethod
    def _non_empty_value(cls, value: str) -> str:
        if not value:
            raise ValueError("locator value must be non-empty")
        return value


class MetricFamilyRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    name: str
    description: str
    parent_code: str | None = None

    @field_validator("code", "name", "description")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must be non-empty")
        return value


class DefinitionConstraints(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    inclusion_rules: tuple[str, ...]
    exclusion_rules: tuple[str, ...]
    allowed_dimensions: tuple[str, ...] = ()
    statement_expectations: tuple[str, ...] = ()
    industry_applicability: tuple[str, ...] = ()
    aggregation_behavior: str | None = None
    derivation_policy: str
    operations_policy: str | None = None
    notes: str | None = None

    @field_validator("inclusion_rules", "exclusion_rules")
    @classmethod
    def _non_empty_clause_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("inclusion_rules and exclusion_rules must be non-empty")
        for item in value:
            if not item.strip():
                raise ValueError("constraint clause must be non-empty")
        return value

    @field_validator("derivation_policy")
    @classmethod
    def _derivation_policy(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("derivation_policy must be non-empty")
        return value


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
    sign_convention: str
    constraints: DefinitionConstraints

    @field_validator("definition_schema_version", "definition_version")
    @classmethod
    def _positive_version(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("schema and definition versions must be positive")
        return value

    @field_validator(
        "metric_code",
        "family_code",
        "name",
        "economic_definition",
        "accounting_basis",
        "value_kind",
        "unit_kind",
        "entity_scope",
        "sign_convention",
    )
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must be non-empty")
        return value


class GlobalScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["global"] = "global"


class IssuerScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["issuer"] = "issuer"
    cik: str

    @field_validator("cik")
    @classmethod
    def _canonical_cik(cls, value: str) -> str:
        normalized = validate_cik(value)
        if value != normalized:
            raise ValueError(f"cik must be zero-padded ten-digit form: {value!r}")
        return normalized


class IssuerPeriodScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["issuer_period"] = "issuer_period"
    cik: str
    report_period_from: date
    report_period_through: date

    @field_validator("cik")
    @classmethod
    def _canonical_cik(cls, value: str) -> str:
        normalized = validate_cik(value)
        if value != normalized:
            raise ValueError(f"cik must be zero-padded ten-digit form: {value!r}")
        return normalized

    @model_validator(mode="after")
    def _period_order(self) -> Self:
        if self.report_period_from > self.report_period_through:
            raise ValueError(
                "report_period_from must be <= report_period_through "
                f"({self.report_period_from} > {self.report_period_through})"
            )
        return self


class FilingScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["filing"] = "filing"
    accession_number: str

    @field_validator("accession_number")
    @classmethod
    def _canonical_accession(cls, value: str) -> str:
        normalized = validate_accession(value)
        if value != normalized:
            raise ValueError(f"accession_number must be canonical dashed form: {value!r}")
        return normalized


MappingScope = Annotated[
    GlobalScope | IssuerScope | IssuerPeriodScope | FilingScope,
    Field(discriminator="kind"),
]


class EvidenceSnapshot(RootModel[dict[str, Any]]):
    @model_validator(mode="after")
    def _non_empty_object(self) -> Self:
        if not self.root:
            raise ValueError("evidence_snapshot must be a non-empty JSON object")
        return self


class ProjectionEvidenceCitationBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accession_number: str
    filing_bundle_opaque_id: str
    xbrl_report_input_ordinal: int
    projection_version: str
    arelle_version: str
    semantic_config_fingerprint: str

    @field_validator("accession_number")
    @classmethod
    def _canonical_accession(cls, value: str) -> str:
        normalized = validate_accession(value)
        if value != normalized:
            raise ValueError(f"accession_number must be canonical dashed form: {value!r}")
        return normalized

    @field_validator("filing_bundle_opaque_id")
    @classmethod
    def _bundle_id(cls, value: str) -> str:
        return validate_uuid4_hex(value)

    @field_validator("xbrl_report_input_ordinal")
    @classmethod
    def _ordinal(cls, value: int) -> int:
        if value < 0:
            raise ValueError("xbrl_report_input_ordinal must be non-negative")
        return value

    @field_validator("semantic_config_fingerprint")
    @classmethod
    def _fingerprint(cls, value: str) -> str:
        if len(value) != 64 or any(c not in _HEX64 for c in value):
            raise ValueError(f"invalid semantic_config_fingerprint: {value!r}")
        return value

    @field_validator("projection_version", "arelle_version")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must be non-empty")
        return value


class ConceptDeclarationCitation(ProjectionEvidenceCitationBase):
    kind: Literal["concept_declaration"] = "concept_declaration"
    concept: ExpandedQNameRecord
    source_locator: SourceLocatorRecord


class FactCitation(ProjectionEvidenceCitationBase):
    kind: Literal["fact"] = "fact"
    concept: ExpandedQNameRecord
    source_locator: SourceLocatorRecord


class RelationshipCitation(ProjectionEvidenceCitationBase):
    kind: Literal["relationship"] = "relationship"
    network_type: NetworkType
    link_role_uri: str
    arcrole_uri: str
    source_concept: ExpandedQNameRecord
    target_concept: ExpandedQNameRecord
    source_locator: SourceLocatorRecord

    @field_validator("link_role_uri", "arcrole_uri")
    @classmethod
    def _non_empty_uri(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("URI field must be non-empty")
        return value


class LabelCitation(ProjectionEvidenceCitationBase):
    kind: Literal["label"] = "label"
    concept: ExpandedQNameRecord
    link_role_uri: str
    arcrole_uri: str
    source_locator: SourceLocatorRecord
    arc_locator: SourceLocatorRecord
    resource_role_uri: str | None = None
    language: str | None = None

    @field_validator("link_role_uri", "arcrole_uri")
    @classmethod
    def _non_empty_uri(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("URI field must be non-empty")
        return value


class ReferenceCitation(ProjectionEvidenceCitationBase):
    kind: Literal["reference"] = "reference"
    concept: ExpandedQNameRecord
    link_role_uri: str
    arcrole_uri: str
    source_locator: SourceLocatorRecord
    arc_locator: SourceLocatorRecord
    resource_role_uri: str | None = None

    @field_validator("link_role_uri", "arcrole_uri")
    @classmethod
    def _non_empty_uri(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("URI field must be non-empty")
        return value


class RawArtifactCitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["raw_artifact"] = "raw_artifact"
    accession_number: str
    filing_bundle_opaque_id: str
    logical_path: str
    artifact_sha256: str
    document_uri: str | None = None

    @field_validator("accession_number")
    @classmethod
    def _canonical_accession(cls, value: str) -> str:
        normalized = validate_accession(value)
        if value != normalized:
            raise ValueError(f"accession_number must be canonical dashed form: {value!r}")
        return normalized

    @field_validator("filing_bundle_opaque_id")
    @classmethod
    def _bundle_id(cls, value: str) -> str:
        return validate_uuid4_hex(value)

    @field_validator("logical_path")
    @classmethod
    def _logical_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("logical_path must be non-empty")
        return value

    @field_validator("artifact_sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        lowered = value.lower()
        if len(lowered) != 64 or any(c not in _HEX64 for c in lowered):
            raise ValueError(f"invalid artifact_sha256: {value!r}")
        return lowered


EvidenceCitation = Annotated[
    ConceptDeclarationCitation
    | FactCitation
    | RelationshipCitation
    | LabelCitation
    | ReferenceCitation
    | RawArtifactCitation,
    Field(discriminator="kind"),
]


class SupersedesRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_key: str

    @field_validator("rule_key")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("supersedes.rule_key must be non-empty")
        return value


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
    evidence_citations: tuple[EvidenceCitation, ...]
    reviewed_by: str
    reviewed_at: datetime
    supersedes: SupersedesRef | None = None

    @field_validator("rule_schema_version", "target_definition_version")
    @classmethod
    def _positive_version(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("schema and target definition versions must be positive")
        return value

    @field_validator("rule_key", "target_metric_code", "rationale", "reviewed_by")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must be non-empty")
        return value

    @field_validator("reviewed_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("evidence_citations")
    @classmethod
    def _non_empty_citations(
        cls, value: tuple[EvidenceCitation, ...]
    ) -> tuple[EvidenceCitation, ...]:
        if not value:
            raise ValueError("evidence_citations must be non-empty")
        return value

    @model_validator(mode="after")
    def _scope_kind_matches(self) -> Self:
        if self.scope_kind != self.scope.kind:
            raise ValueError(
                f"scope_kind {self.scope_kind!r} does not match scope.kind {self.scope.kind!r}"
            )
        return self


# ---------------------------------------------------------------------------
# Envelope files
# ---------------------------------------------------------------------------


class FamiliesFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_schema_version: int
    families: tuple[MetricFamilyRecord, ...]

    @field_validator("registry_schema_version")
    @classmethod
    def _positive_version(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("registry_schema_version must be positive")
        return value


class DefinitionsFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_schema_version: int
    definitions: tuple[MetricDefinitionRecord, ...]

    @field_validator("registry_schema_version")
    @classmethod
    def _positive_version(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("registry_schema_version must be positive")
        return value


class RulesFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_schema_version: int
    rules: tuple[MappingRuleRecord, ...]

    @field_validator("registry_schema_version")
    @classmethod
    def _positive_version(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("registry_schema_version must be positive")
        return value


class LoadedRegistry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registry_schema_version: int
    families: tuple[MetricFamilyRecord, ...]
    definitions: tuple[MetricDefinitionRecord, ...]
    rules: tuple[MappingRuleRecord, ...]
    families_file_hash: str
    definitions_file_hash: str
    rules_file_hash: str
    registry_hash: str


# ---------------------------------------------------------------------------
# Canonical JSON and hashing
# ---------------------------------------------------------------------------


def canonical_json_bytes(value: Any) -> bytes:
    """Return UTF-8 JSON bytes with deterministic key order and separators."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonicalize_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _canonicalize_date(value: date) -> str:
    return value.isoformat()


def _canonicalize_qname(qname: ExpandedQNameRecord) -> dict[str, Any]:
    return {"local_name": qname.local_name, "namespace_uri": qname.namespace_uri}


def _qnames_equal(left: ExpandedQNameRecord, right: ExpandedQNameRecord) -> bool:
    return left.namespace_uri == right.namespace_uri and left.local_name == right.local_name


def _canonicalize_locator(locator: SourceLocatorRecord) -> dict[str, Any]:
    return {
        "document_uri": locator.document_uri,
        "scheme": locator.scheme,
        "value": locator.value,
    }


def _canonicalize_projection_base(citation: ProjectionEvidenceCitationBase) -> dict[str, Any]:
    return {
        "accession_number": citation.accession_number,
        "arelle_version": citation.arelle_version,
        "filing_bundle_opaque_id": citation.filing_bundle_opaque_id,
        "projection_version": citation.projection_version,
        "semantic_config_fingerprint": citation.semantic_config_fingerprint,
        "xbrl_report_input_ordinal": citation.xbrl_report_input_ordinal,
    }


def _canonicalize_citation(citation: EvidenceCitation) -> dict[str, Any]:
    if isinstance(citation, ConceptDeclarationCitation):
        payload = _canonicalize_projection_base(citation)
        payload.update(
            {
                "concept": _canonicalize_qname(citation.concept),
                "kind": citation.kind,
                "source_locator": _canonicalize_locator(citation.source_locator),
            }
        )
        return payload
    if isinstance(citation, FactCitation):
        payload = _canonicalize_projection_base(citation)
        payload.update(
            {
                "concept": _canonicalize_qname(citation.concept),
                "kind": citation.kind,
                "source_locator": _canonicalize_locator(citation.source_locator),
            }
        )
        return payload
    if isinstance(citation, RelationshipCitation):
        payload = _canonicalize_projection_base(citation)
        payload.update(
            {
                "arcrole_uri": citation.arcrole_uri,
                "kind": citation.kind,
                "link_role_uri": citation.link_role_uri,
                "network_type": citation.network_type,
                "source_concept": _canonicalize_qname(citation.source_concept),
                "source_locator": _canonicalize_locator(citation.source_locator),
                "target_concept": _canonicalize_qname(citation.target_concept),
            }
        )
        return payload
    if isinstance(citation, LabelCitation):
        payload = _canonicalize_projection_base(citation)
        payload.update(
            {
                "arc_locator": _canonicalize_locator(citation.arc_locator),
                "arcrole_uri": citation.arcrole_uri,
                "concept": _canonicalize_qname(citation.concept),
                "kind": citation.kind,
                "language": citation.language,
                "link_role_uri": citation.link_role_uri,
                "resource_role_uri": citation.resource_role_uri,
                "source_locator": _canonicalize_locator(citation.source_locator),
            }
        )
        return payload
    if isinstance(citation, ReferenceCitation):
        payload = _canonicalize_projection_base(citation)
        payload.update(
            {
                "arc_locator": _canonicalize_locator(citation.arc_locator),
                "arcrole_uri": citation.arcrole_uri,
                "concept": _canonicalize_qname(citation.concept),
                "kind": citation.kind,
                "link_role_uri": citation.link_role_uri,
                "resource_role_uri": citation.resource_role_uri,
                "source_locator": _canonicalize_locator(citation.source_locator),
            }
        )
        return payload
    citation = cast(RawArtifactCitation, citation)
    return {
        "accession_number": citation.accession_number,
        "artifact_sha256": citation.artifact_sha256,
        "document_uri": citation.document_uri,
        "filing_bundle_opaque_id": citation.filing_bundle_opaque_id,
        "kind": citation.kind,
        "logical_path": citation.logical_path,
    }


def _canonicalize_scope(scope: MappingScope) -> dict[str, Any]:
    if isinstance(scope, GlobalScope):
        return {"kind": scope.kind}
    if isinstance(scope, IssuerScope):
        return {"cik": scope.cik, "kind": scope.kind}
    if isinstance(scope, IssuerPeriodScope):
        return {
            "cik": scope.cik,
            "kind": scope.kind,
            "report_period_from": _canonicalize_date(scope.report_period_from),
            "report_period_through": _canonicalize_date(scope.report_period_through),
        }
    scope = cast(FilingScope, scope)
    return {"accession_number": scope.accession_number, "kind": scope.kind}


def _canonicalize_string_set(values: Sequence[str], *, label: str) -> list[str]:
    normalized = sorted(values)
    if len(normalized) != len(set(normalized)):
        raise RegistryValidationError(f"duplicate elements in {label}")
    return normalized


def _canonicalize_constraints(constraints: DefinitionConstraints) -> dict[str, Any]:
    return {
        "aggregation_behavior": constraints.aggregation_behavior,
        "allowed_dimensions": _canonicalize_string_set(
            constraints.allowed_dimensions, label="constraints.allowed_dimensions"
        ),
        "derivation_policy": constraints.derivation_policy,
        "exclusion_rules": _canonicalize_string_set(
            constraints.exclusion_rules, label="constraints.exclusion_rules"
        ),
        "inclusion_rules": _canonicalize_string_set(
            constraints.inclusion_rules, label="constraints.inclusion_rules"
        ),
        "industry_applicability": _canonicalize_string_set(
            constraints.industry_applicability, label="constraints.industry_applicability"
        ),
        "notes": constraints.notes,
        "operations_policy": constraints.operations_policy,
        "statement_expectations": list(constraints.statement_expectations),
    }


def _canonicalize_object_set(
    items: Sequence[dict[str, Any]],
    *,
    label: str,
    sort_key: Any,
) -> list[dict[str, Any]]:
    keyed: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for item in items:
        encoded = sha256_hex(canonical_json_bytes(item))
        if encoded in seen:
            raise RegistryValidationError(f"duplicate elements in {label}")
        seen.add(encoded)
        keyed.append((sort_key(item), item))
    keyed.sort(key=lambda pair: pair[0])
    return [item for _, item in keyed]


def canonicalize_family(registry_schema_version: int, family: MetricFamilyRecord) -> dict[str, Any]:
    return {
        "code": family.code,
        "description": family.description,
        "name": family.name,
        "parent_code": family.parent_code,
        "registry_schema_version": registry_schema_version,
    }


def canonicalize_definition_v1(defn: MetricDefinitionRecord) -> dict[str, Any]:
    if defn.definition_schema_version != DEFINITION_SCHEMA_VERSION:
        raise RegistryValidationError(
            f"unsupported definition_schema_version: {defn.definition_schema_version}"
        )
    return {
        "accounting_basis": defn.accounting_basis,
        "constraints": _canonicalize_constraints(defn.constraints),
        "definition_schema_version": defn.definition_schema_version,
        "definition_version": defn.definition_version,
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


def canonicalize_rule_v1(rule: MappingRuleRecord) -> dict[str, Any]:
    if rule.rule_schema_version != RULE_SCHEMA_VERSION:
        raise RegistryValidationError(
            f"unsupported rule_schema_version: {rule.rule_schema_version}"
        )
    citations = _canonicalize_object_set(
        [_canonicalize_citation(c) for c in rule.evidence_citations],
        label=f"rule {rule.rule_key!r} evidence_citations",
        sort_key=lambda item: canonical_json_bytes(item).decode(),
    )
    payload: dict[str, Any] = {
        "confidence_tier": rule.confidence_tier,
        "evidence_citations": citations,
        "evidence_snapshot": rule.evidence_snapshot.root,
        "rationale": rule.rationale,
        "relationship_type": rule.relationship_type,
        "reviewed_at": _canonicalize_datetime(rule.reviewed_at),
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
    return payload


def fingerprint_family(registry_schema_version: int, family: MetricFamilyRecord) -> str:
    return sha256_hex(canonical_json_bytes(canonicalize_family(registry_schema_version, family)))


def fingerprint_definition(defn: MetricDefinitionRecord) -> str:
    return sha256_hex(canonical_json_bytes(canonicalize_definition_v1(defn)))


def fingerprint_rule(rule: MappingRuleRecord) -> str:
    return sha256_hex(canonical_json_bytes(canonicalize_rule_v1(rule)))


def _canonicalize_families_file(file: FamiliesFile) -> dict[str, Any]:
    if file.registry_schema_version != REGISTRY_SCHEMA_VERSION:
        raise RegistryValidationError(
            f"unsupported registry_schema_version in families file: {file.registry_schema_version}"
        )
    families = _canonicalize_object_set(
        [canonicalize_family(file.registry_schema_version, family) for family in file.families],
        label="families",
        sort_key=lambda item: item["code"],
    )
    return {"families": families, "registry_schema_version": file.registry_schema_version}


def _canonicalize_definitions_file(file: DefinitionsFile) -> dict[str, Any]:
    if file.registry_schema_version != REGISTRY_SCHEMA_VERSION:
        raise RegistryValidationError(
            f"unsupported registry_schema_version in definitions file: "
            f"{file.registry_schema_version}"
        )
    definitions = _canonicalize_object_set(
        [canonicalize_definition_v1(defn) for defn in file.definitions],
        label="definitions",
        sort_key=lambda item: (item["metric_code"], item["definition_version"]),
    )
    return {
        "definitions": definitions,
        "registry_schema_version": file.registry_schema_version,
    }


def _canonicalize_rules_file(file: RulesFile) -> dict[str, Any]:
    if file.registry_schema_version != REGISTRY_SCHEMA_VERSION:
        raise RegistryValidationError(
            f"unsupported registry_schema_version in rules file: {file.registry_schema_version}"
        )
    rules = _canonicalize_object_set(
        [canonicalize_rule_v1(rule) for rule in file.rules],
        label="rules",
        sort_key=lambda item: item["rule_key"],
    )
    return {"registry_schema_version": file.registry_schema_version, "rules": rules}


def fingerprint_families_file(file: FamiliesFile) -> str:
    return sha256_hex(canonical_json_bytes(_canonicalize_families_file(file)))


def fingerprint_definitions_file(file: DefinitionsFile) -> str:
    return sha256_hex(canonical_json_bytes(_canonicalize_definitions_file(file)))


def fingerprint_rules_file(file: RulesFile) -> str:
    return sha256_hex(canonical_json_bytes(_canonicalize_rules_file(file)))


def fingerprint_registry(
    *,
    registry_schema_version: int,
    families_file_hash: str,
    definitions_file_hash: str,
    rules_file_hash: str,
) -> str:
    payload = {
        "definitions_file_hash": definitions_file_hash,
        "families_file_hash": families_file_hash,
        "registry_schema_version": registry_schema_version,
        "rules_file_hash": rules_file_hash,
    }
    return sha256_hex(canonical_json_bytes(payload))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_registry(registry_dir: Path) -> LoadedRegistry:
    """Load and hash the three Git registry files under ``registry_dir``."""
    families_path = registry_dir / FAMILIES_FILENAME
    definitions_path = registry_dir / DEFINITIONS_FILENAME
    rules_path = registry_dir / RULES_FILENAME

    families_file = FamiliesFile.model_validate(_load_json(families_path))
    definitions_file = DefinitionsFile.model_validate(_load_json(definitions_path))
    rules_file = RulesFile.model_validate(_load_json(rules_path))

    versions = {
        families_file.registry_schema_version,
        definitions_file.registry_schema_version,
        rules_file.registry_schema_version,
    }
    if len(versions) != 1:
        raise RegistryValidationError(
            "mixed registry_schema_version across files: "
            f"families={families_file.registry_schema_version}, "
            f"definitions={definitions_file.registry_schema_version}, "
            f"rules={rules_file.registry_schema_version}"
        )
    registry_schema_version = families_file.registry_schema_version
    if registry_schema_version != REGISTRY_SCHEMA_VERSION:
        raise RegistryValidationError(
            f"unsupported registry_schema_version: {registry_schema_version}"
        )

    families_file_hash = fingerprint_families_file(families_file)
    definitions_file_hash = fingerprint_definitions_file(definitions_file)
    rules_file_hash = fingerprint_rules_file(rules_file)
    registry_hash = fingerprint_registry(
        registry_schema_version=registry_schema_version,
        families_file_hash=families_file_hash,
        definitions_file_hash=definitions_file_hash,
        rules_file_hash=rules_file_hash,
    )

    return LoadedRegistry(
        registry_schema_version=registry_schema_version,
        families=families_file.families,
        definitions=definitions_file.definitions,
        rules=rules_file.rules,
        families_file_hash=families_file_hash,
        definitions_file_hash=definitions_file_hash,
        rules_file_hash=rules_file_hash,
        registry_hash=registry_hash,
    )


# ---------------------------------------------------------------------------
# Cross-record validation
# ---------------------------------------------------------------------------


def rule_state(
    rule_key: str,
    rules: Mapping[str, MappingRuleRecord],
) -> RuleState:
    """Return ``current`` unless another rule supersedes ``rule_key``."""
    for rule in rules.values():
        if rule.supersedes is not None and rule.supersedes.rule_key == rule_key:
            return "superseded"
    return "current"


def _validate_unique_keys(registry: LoadedRegistry) -> None:
    family_codes = [family.code for family in registry.families]
    if len(family_codes) != len(set(family_codes)):
        raise RegistryValidationError("duplicate family code")

    definition_keys = [(d.metric_code, d.definition_version) for d in registry.definitions]
    if len(definition_keys) != len(set(definition_keys)):
        raise RegistryValidationError(
            "duplicate metric definition key (metric_code, definition_version)"
        )

    rule_keys = [rule.rule_key for rule in registry.rules]
    if len(rule_keys) != len(set(rule_keys)):
        raise RegistryValidationError("duplicate rule_key")


def _validate_set_duplicates(registry: LoadedRegistry) -> None:
    for defn in registry.definitions:
        constraints = defn.constraints
        for label, values in (
            ("inclusion_rules", constraints.inclusion_rules),
            ("exclusion_rules", constraints.exclusion_rules),
            ("allowed_dimensions", constraints.allowed_dimensions),
            ("industry_applicability", constraints.industry_applicability),
        ):
            if len(values) != len(set(values)):
                raise RegistryValidationError(
                    f"duplicate elements in {defn.metric_code} constraints.{label}"
                )
    for rule in registry.rules:
        encoded = [
            sha256_hex(canonical_json_bytes(_canonicalize_citation(c)))
            for c in rule.evidence_citations
        ]
        if len(encoded) != len(set(encoded)):
            raise RegistryValidationError(f"duplicate evidence_citations in rule {rule.rule_key!r}")


def _validate_families(registry: LoadedRegistry) -> dict[str, MetricFamilyRecord]:
    by_code = {family.code: family for family in registry.families}
    for family in registry.families:
        if family.parent_code == family.code:
            raise RegistryValidationError(f"family {family.code!r} cannot be its own parent")
        if family.parent_code is not None and family.parent_code not in by_code:
            raise RegistryValidationError(
                f"family {family.code!r} references unknown parent_code {family.parent_code!r}"
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(code: str) -> None:
        if code in visited:
            return
        if code in visiting:
            raise RegistryValidationError(f"family hierarchy cycle involving {code!r}")
        visiting.add(code)
        parent = by_code[code].parent_code
        if parent is not None:
            visit(parent)
        visiting.remove(code)
        visited.add(code)

    for code in by_code:
        visit(code)
    return by_code


def _validate_definitions(
    registry: LoadedRegistry,
    families_by_code: Mapping[str, MetricFamilyRecord],
) -> dict[tuple[str, int], MetricDefinitionRecord]:
    definitions_by_key: dict[tuple[str, int], MetricDefinitionRecord] = {}
    for defn in registry.definitions:
        if defn.definition_schema_version != DEFINITION_SCHEMA_VERSION:
            raise RegistryValidationError(
                f"definition {defn.metric_code} v{defn.definition_version}: "
                f"unsupported definition_schema_version {defn.definition_schema_version}"
            )
        if defn.family_code not in families_by_code:
            raise RegistryValidationError(
                f"definition {defn.metric_code} v{defn.definition_version}: "
                f"unknown family_code {defn.family_code!r}"
            )
        if defn.period_type not in PERIOD_TYPES:
            raise RegistryValidationError(
                f"definition {defn.metric_code} v{defn.definition_version}: "
                f"invalid period_type {defn.period_type!r}"
            )
        definitions_by_key[(defn.metric_code, defn.definition_version)] = defn
    return definitions_by_key


def _citation_involves_source_concept(
    citation: EvidenceCitation,
    source: ExpandedQNameRecord,
) -> bool:
    if isinstance(citation, RawArtifactCitation):
        return False
    if isinstance(citation, ConceptDeclarationCitation):
        return _qnames_equal(citation.concept, source)
    if isinstance(citation, FactCitation):
        return _qnames_equal(citation.concept, source)
    if isinstance(citation, LabelCitation):
        return _qnames_equal(citation.concept, source)
    if isinstance(citation, ReferenceCitation):
        return _qnames_equal(citation.concept, source)
    if isinstance(citation, RelationshipCitation):
        return _qnames_equal(citation.source_concept, source) or _qnames_equal(
            citation.target_concept, source
        )
    return False


def _validate_rules(
    registry: LoadedRegistry,
    definitions_by_key: Mapping[tuple[str, int], MetricDefinitionRecord],
) -> dict[str, MappingRuleRecord]:
    rules_by_key = {rule.rule_key: rule for rule in registry.rules}
    for rule in registry.rules:
        if rule.rule_schema_version != RULE_SCHEMA_VERSION:
            raise RegistryValidationError(
                f"rule {rule.rule_key!r}: unsupported rule_schema_version "
                f"{rule.rule_schema_version}"
            )
        if rule.relationship_type == "derived_equivalent":
            raise RegistryValidationError(
                f"rule {rule.rule_key!r}: derived_equivalent is not permitted in Phase 2A data"
            )
        if rule.relationship_type == "issuer_equivalent" and rule.scope_kind == "issuer":
            raise RegistryValidationError(
                f"rule {rule.rule_key!r}: issuer_equivalent requires issuer_period or filing scope"
            )
        target_key = (rule.target_metric_code, rule.target_definition_version)
        if target_key not in definitions_by_key:
            raise RegistryValidationError(
                f"rule {rule.rule_key!r}: unknown target definition {target_key}"
            )
        if rule.supersedes is not None:
            if rule.supersedes.rule_key == rule.rule_key:
                raise RegistryValidationError(f"rule {rule.rule_key!r}: cannot supersede itself")
            predecessor = rules_by_key.get(rule.supersedes.rule_key)
            if predecessor is None:
                raise RegistryValidationError(
                    f"rule {rule.rule_key!r}: unknown supersedes target "
                    f"{rule.supersedes.rule_key!r}"
                )
            if not _qnames_equal(predecessor.source_concept, rule.source_concept):
                raise RegistryValidationError(
                    f"rule {rule.rule_key!r}: supersedes {rule.supersedes.rule_key!r} "
                    "but source concepts differ"
                )

        if not any(
            _citation_involves_source_concept(c, rule.source_concept)
            for c in rule.evidence_citations
        ):
            raise RegistryValidationError(
                f"rule {rule.rule_key!r}: at least one projection-backed citation must "
                "involve the source concept"
            )

    successors: dict[str, list[str]] = {key: [] for key in rules_by_key}
    for rule in registry.rules:
        if rule.supersedes is not None:
            successors[rule.supersedes.rule_key].append(rule.rule_key)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        if key in visiting:
            raise RegistryValidationError(f"supersession cycle involving rule {key!r}")
        visiting.add(key)
        rule = rules_by_key[key]
        if rule.supersedes is not None:
            visit(rule.supersedes.rule_key)
        visiting.remove(key)
        visited.add(key)

    for key in rules_by_key:
        visit(key)

    return rules_by_key


def validate_registry(registry: LoadedRegistry) -> None:
    """Validate cross-record invariants for a loaded registry."""
    _validate_unique_keys(registry)
    _validate_set_duplicates(registry)
    families_by_code = _validate_families(registry)
    definitions_by_key = _validate_definitions(registry, families_by_code)
    _validate_rules(registry, definitions_by_key)
