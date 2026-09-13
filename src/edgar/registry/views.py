"""Read models for mapping inspection, history, and live affected facts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from edgar.registry.mapping import (
    MappingEvidenceItem,
    MappingMethod,
    MappingStatus,
    Relation,
    ScopeKind,
)
from edgar.registry.models import (
    MetricKind,
    PeriodType,
    Statement,
    UnitDimension,
    ValueKind,
)

DEFAULT_SHOW_FACT_LIMIT = 25


class MappingScopeView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ScopeKind
    issuer_cik: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class MappingAssertionView(BaseModel):
    """One immutable mapping assertion revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    supersedes_id: int | None = None
    is_current: bool
    source_concept_id: UUID
    source_concept: str
    target_metric_key: str
    target_definition_hash: str
    relation: Relation
    scope: MappingScopeView
    status: MappingStatus
    method: MappingMethod
    rationale: str | None = None
    evidence: tuple[MappingEvidenceItem, ...] = ()
    created_at: datetime
    created_by: str


class SourceConceptView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    namespace_uri: str
    local_name: str
    clark_qname: str


class TargetMetricView(BaseModel):
    """Current YAML metric contract compared against the assertion hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    name: str
    kind: MetricKind
    statement: Statement
    period_type: PeriodType
    value_kind: ValueKind
    unit_dimension: UnitDimension
    definition: str
    includes: tuple[str, ...]
    excludes: tuple[str, ...]
    definition_hash: str


class DimensionMemberView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: str
    member: str | None = None
    member_kind: str
    context_element: str
    typed_member: dict[str, Any] | None = None


class UnitMeasureView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    side: str
    ordinal: int
    measure: str


class MappingFactView(BaseModel):
    """Live source fact occurrence. ``fact_id`` is current-extraction identity only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_id: int
    accession: str
    issuer_cik: str
    report_period_end: date | None = None
    period_kind: str
    period_instant: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    source_document: str | None = None
    source_locator: dict[str, Any] | None = None
    dimensions: tuple[DimensionMemberView, ...] = ()
    unit_measures: tuple[UnitMeasureView, ...] = ()
    raw_lexical_value: str | None = None
    resolved_value_kind: str | None = None
    resolved_numeric: Decimal | None = None
    resolved_text: str | None = None
    is_nil: bool


class AffectedFactSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    count: int
    shown: int
    truncated: bool
    accession_count: int
    issuer_count: int


class MappingReport(BaseModel):
    """Inspection report for a named assertion revision (never auto-resolved)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mapping: MappingAssertionView
    is_current: bool
    current_revision_id: int
    source_concept: SourceConceptView
    target_metric: TargetMetricView
    yaml_definition_hash: str
    definition_changed: bool
    mirror_out_of_sync: bool
    scope: MappingScopeView
    rationale: str | None = None
    evidence: tuple[MappingEvidenceItem, ...] = ()
    history: tuple[MappingAssertionView, ...]
    affected_fact_summary: AffectedFactSummary
    affected_facts: tuple[MappingFactView, ...] = Field(default=())
