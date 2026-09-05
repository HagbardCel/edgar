"""Pydantic contracts for mapping assertions and evidence."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from edgar.domain.identifiers import validate_accession, validate_cik
from edgar.xbrl.records import ExpandedQName

Relation = Literal["exact", "narrower", "broader", "related"]
ScopeKind = Literal["global", "issuer"]
MappingStatus = Literal["candidate", "accepted", "rejected"]
MappingMethod = Literal[
    "curated",
    "deterministic_rule",
    "lexical_candidate",
    "structural_candidate",
    "model_candidate",
    "human_review",
]
EvidenceKind = Literal[
    "taxonomy_identity",
    "label",
    "documentation",
    "data_type",
    "period_type",
    "balance",
    "presentation_path",
    "calculation_relationship",
    "definition_relationship",
    "unit_usage",
    "dimension_usage",
    "historical_consistency",
    "value_reconciliation",
    "human_analysis",
    "model_analysis",
]

CLAIM_FIELDS: tuple[str, ...] = (
    "source_concept_id",
    "target_metric_key",
    "target_definition_hash",
    "relation",
    "scope_kind",
    "issuer_cik",
    "valid_from",
    "valid_to",
)


def parse_clark_qname(value: str) -> tuple[str, str]:
    """Parse Clark ``{namespace-uri}LocalName``; reject prefix or local-name-only identity."""
    text = value.strip()
    if not text.startswith("{") or "}" not in text:
        raise ValueError(
            "source concept must be an exact expanded QName in Clark notation "
            "'{namespace-uri}LocalName'"
        )
    parsed = ExpandedQName.from_clark(text)
    if parsed.namespace_uri is None or not parsed.namespace_uri:
        raise ValueError(
            "source concept must include a non-empty namespace URI; "
            "local-name-only identity is forbidden"
        )
    return parsed.namespace_uri, parsed.local_name


class MappingEvidenceItem(BaseModel):
    """Structured evidence snapshot. Must not persist unstable source fact ids."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EvidenceKind
    summary: str | None = None
    data: dict[str, Any]
    accessions: tuple[str, ...] = ()

    @field_validator("summary")
    @classmethod
    def _summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("summary must be non-empty when provided")
        return stripped

    @field_validator("accessions")
    @classmethod
    def _accessions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(validate_accession(item) for item in value)

    @field_validator("data")
    @classmethod
    def _no_fact_ids(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value:
            lowered = str(key).lower()
            if "fact_id" in lowered or lowered in {"source_fact_ids", "fact_ids"}:
                raise ValueError("durable evidence must not contain source fact ids")
        return value

    def has_snapshot(self) -> bool:
        return bool(self.data)


class MappingAssertionCreate(BaseModel):
    """Inputs for proposing a mapping assertion root."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    concept: str
    target_metric_key: str
    relation: Relation
    scope_kind: ScopeKind
    issuer_cik: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    method: MappingMethod
    rationale: str | None = None
    evidence: tuple[MappingEvidenceItem, ...] = ()
    created_by: str

    @field_validator("concept")
    @classmethod
    def _concept(cls, value: str) -> str:
        parse_clark_qname(value)
        return value

    @field_validator("target_metric_key", "created_by")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must be non-empty")
        return stripped

    @field_validator("rationale")
    @classmethod
    def _rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("rationale must be non-empty when provided")
        return stripped

    @field_validator("issuer_cik")
    @classmethod
    def _cik(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = validate_cik(value)
        if value != normalized:
            raise ValueError(f"cik must be zero-padded: {value!r}")
        return normalized

    @model_validator(mode="after")
    def _scope_and_dates(self) -> Self:
        if self.scope_kind == "global" and self.issuer_cik is not None:
            raise ValueError("global scope requires issuer_cik to be omitted")
        if self.scope_kind == "issuer" and self.issuer_cik is None:
            raise ValueError("issuer scope requires issuer_cik")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_from > self.valid_to
        ):
            raise ValueError("valid_from must be <= valid_to")
        return self

    def clark_parts(self) -> tuple[str, str]:
        return parse_clark_qname(self.concept)


class MappingAssertionRevision(BaseModel):
    """Decision fields for an accept or reject successor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: MappingMethod
    rationale: str | None = None
    evidence: tuple[MappingEvidenceItem, ...] = ()
    created_by: str

    @field_validator("created_by")
    @classmethod
    def _created_by(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("created_by must be non-empty")
        return stripped

    @field_validator("rationale")
    @classmethod
    def _rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("rationale must be non-empty when provided")
        return stripped
