"""In-memory models for P1 resolve/select."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

Relation = Literal["exact", "narrower", "broader", "related"]
ObservationStatus = Literal["value", "missing", "unsupported", "conflict"]
ObservationReason = Literal[
    "broader_only",
    "decision_scope",
    "wrong_form",
]


@dataclass(frozen=True)
class UnitMeasureRow:
    side: str
    ordinal: int
    measure_namespace_uri: str | None
    measure_local_name: str


@dataclass(frozen=True)
class FactRow:
    fact_id: int
    concept_namespace: str
    concept_local_name: str
    source_qname: str
    context_id: int
    value_status: str
    resolved_numeric: Decimal | None
    is_nil: bool
    decimals: str | None
    lexical_value: str | None
    entity_scheme: str
    entity_identifier: str
    period_kind: str
    instant_lexical: str | None
    start_lexical: str | None
    end_lexical: str | None
    has_dimensions: bool
    unit_measures: tuple[UnitMeasureRow, ...]


@dataclass(frozen=True)
class Support:
    fact_id: int
    accession: str
    concept_namespace: str
    concept_local_name: str
    source_qname: str
    metric: str
    relation: Relation
    decision_id: str
    application_method: str
    tier: int


@dataclass(frozen=True)
class SupportRef:
    fact_id: int
    decision_id: str
    relation: Relation
    tier: int
    source_qname: str
    application_method: str


@dataclass
class Observation:
    cik: str
    accession: str
    metric: str
    fy: str | None
    report_focus: str | None
    period_role: str | None
    period_start: str | None
    period_end: str | None
    status: ObservationStatus
    reason: str | None
    numeric: Decimal | None
    decimals: str | None
    unit: str | None
    decision_ids: tuple[str, ...]
    fact_ids: tuple[int, ...]
    supports: tuple[SupportRef, ...]
    relation: Relation | None
    tier: int | None
    available_at: str | None
    view: str = "as-filed"
