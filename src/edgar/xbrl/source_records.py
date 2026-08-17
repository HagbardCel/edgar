"""Phase 2B source-layer extraction DTOs (no projection identity, no DB ids).

These records are the in-memory boundary between Arelle extraction and
``source.*`` persistence. Provenance uses FilingBundle ``logical_path`` values,
never PostgreSQL document ids.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from edgar.xbrl.records import (
    Balance,
    ContextElement,
    ExpandedQName,
    IssueSeverity,
    MeasureRole,
    MemberKind,
    NetworkType,
    PeriodKind,
    PeriodType,
    ResolvedValueKind,
    ValueStatus,
)

EXTRACTOR_VERSION = "source-extract-v2"

#: Wire schema for worker ``extraction_payload`` (not identity).
SOURCE_RECORDS_SCHEMA_VERSION = 2

LocatorScheme = Literal["xml_id", "unqualified_id", "expanded_element_path"]


@dataclass(frozen=True)
class ElementLocator:
    """Element identity within a document (scheme/value only; path is separate)."""

    scheme: LocatorScheme
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("locator value must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {"scheme": self.scheme, "value": self.value}


def _assert_locator_implies_path(
    path: str | None,
    locator: ElementLocator | None,
    *,
    what: str,
) -> None:
    """Paired provenance: a locator is meaningless without its document path."""
    if locator is not None and not path:
        raise ValueError(f"{what} locator requires a non-empty source_document_relative_path")


@dataclass(frozen=True)
class ReferencePartRecord:
    """One ordered reference part: Clark ``qname`` + lexical ``value``."""

    qname: str
    value: str

    def __post_init__(self) -> None:
        if not self.qname:
            raise ValueError("reference part qname must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {"qname": self.qname, "value": self.value}


@dataclass(frozen=True)
class ConceptRecord:
    """Global concept identity (namespace URI + local name)."""

    namespace_uri: str
    local_name: str

    def __post_init__(self) -> None:
        if not self.namespace_uri:
            raise ValueError("namespace_uri must be non-empty")
        if not self.local_name:
            raise ValueError("local_name must be non-empty")

    @property
    def as_qname(self) -> ExpandedQName:
        return ExpandedQName(namespace_uri=self.namespace_uri, local_name=self.local_name)


@dataclass(frozen=True)
class ConceptDeclarationRecord:
    """Report-scoped effective declaration of one global concept."""

    concept: ExpandedQName
    data_type: ExpandedQName | None = None
    substitution_group: ExpandedQName | None = None
    period_type: PeriodType | None = None
    balance: Balance | None = None
    abstract: bool | None = None
    nillable: bool | None = None
    source_document_relative_path: str | None = None
    source_locator: ElementLocator | None = None

    def __post_init__(self) -> None:
        _assert_locator_implies_path(
            self.source_document_relative_path,
            self.source_locator,
            what="concept declaration",
        )


@dataclass(frozen=True)
class ConceptLabelRecord:
    """One effective concept-label resource occurrence (no content uniqueness).

    ``link_role_uri`` (ELR), ``arcrole_uri``, and ``resource_role_uri`` are
    distinct. Resource provenance and arc provenance are independent pairs.
    """

    concept: ExpandedQName
    link_role_uri: str
    arcrole_uri: str
    text: str
    source_order: int
    language: str | None = None
    resource_role_uri: str | None = None
    order_value: Decimal | None = None
    source_document_relative_path: str | None = None
    source_locator: ElementLocator | None = None
    arc_document_relative_path: str | None = None
    arc_locator: ElementLocator | None = None

    def __post_init__(self) -> None:
        if not self.link_role_uri:
            raise ValueError("link_role_uri is required")
        if not self.arcrole_uri:
            raise ValueError("arcrole_uri is required")
        if self.source_order < 0:
            raise ValueError("source_order must be >= 0")
        if self.order_value is not None and not self.order_value.is_finite():
            raise ValueError(f"order_value must be finite: {self.order_value!r}")
        _assert_locator_implies_path(
            self.source_document_relative_path,
            self.source_locator,
            what="concept label resource",
        )
        _assert_locator_implies_path(
            self.arc_document_relative_path,
            self.arc_locator,
            what="concept label arc",
        )


@dataclass(frozen=True)
class ConceptReferenceRecord:
    """One effective concept-reference occurrence with ordered parts."""

    concept: ExpandedQName
    link_role_uri: str
    arcrole_uri: str
    source_order: int
    reference_parts: tuple[ReferencePartRecord, ...] = ()
    resource_role_uri: str | None = None
    order_value: Decimal | None = None
    source_document_relative_path: str | None = None
    source_locator: ElementLocator | None = None
    arc_document_relative_path: str | None = None
    arc_locator: ElementLocator | None = None

    def __post_init__(self) -> None:
        if not self.link_role_uri:
            raise ValueError("link_role_uri is required")
        if not self.arcrole_uri:
            raise ValueError("arcrole_uri is required")
        if self.source_order < 0:
            raise ValueError("source_order must be >= 0")
        if self.order_value is not None and not self.order_value.is_finite():
            raise ValueError(f"order_value must be finite: {self.order_value!r}")
        _assert_locator_implies_path(
            self.source_document_relative_path,
            self.source_locator,
            what="concept reference resource",
        )
        _assert_locator_implies_path(
            self.arc_document_relative_path,
            self.arc_locator,
            what="concept reference arc",
        )


@dataclass(frozen=True)
class ContextRecord:
    """One ``xbrli:context`` occurrence identified by filed ``source_context_id``."""

    source_context_id: str
    entity_scheme: str
    entity_identifier: str
    period_kind: PeriodKind
    period_instant: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    source_document_relative_path: str | None = None
    source_locator: ElementLocator | None = None

    def __post_init__(self) -> None:
        if not self.source_context_id:
            raise ValueError("source_context_id is required")
        _assert_locator_implies_path(
            self.source_document_relative_path,
            self.source_locator,
            what="context",
        )


@dataclass(frozen=True)
class ContextDimensionRecord:
    """One filed explicit or typed dimension occurrence within a context."""

    source_context_id: str
    dimension: ExpandedQName
    context_element: ContextElement
    member_kind: MemberKind
    member: ExpandedQName | None = None
    typed_member: Mapping[str, Any] | None = None
    source_document_relative_path: str | None = None
    source_locator: ElementLocator | None = None

    def __post_init__(self) -> None:
        if self.member_kind == "explicit":
            if self.member is None:
                raise ValueError("explicit dimension requires a member QName")
            if self.typed_member is not None:
                raise ValueError("explicit dimension must not carry typed_member")
        else:
            if self.typed_member is None:
                raise ValueError("typed dimension requires typed_member")
            if self.member is not None:
                raise ValueError("typed dimension must not carry an explicit member")
        _assert_locator_implies_path(
            self.source_document_relative_path,
            self.source_locator,
            what="context dimension",
        )


@dataclass(frozen=True)
class UnitRecord:
    """One ``xbrli:unit`` occurrence."""

    source_unit_id: str
    divide: bool = False
    source_document_relative_path: str | None = None
    source_locator: ElementLocator | None = None

    def __post_init__(self) -> None:
        if not self.source_unit_id:
            raise ValueError("source_unit_id is required")
        _assert_locator_implies_path(
            self.source_document_relative_path,
            self.source_locator,
            what="unit",
        )


@dataclass(frozen=True)
class UnitMeasureRecord:
    """One measure of a unit as an expanded QName."""

    source_unit_id: str
    side: MeasureRole
    ordinal: int
    measure: ExpandedQName

    def __post_init__(self) -> None:
        if self.ordinal < 1:
            raise ValueError("ordinal must be >= 1")


@dataclass(frozen=True)
class FactRecord:
    """One item-fact source occurrence (iterator ordinal = ``source_order``)."""

    source_order: int
    concept: ExpandedQName
    source_context_id: str
    value_status: ValueStatus
    is_nil: bool = False
    source_unit_id: str | None = None
    raw_lexical_value: str | None = None
    resolved_value_kind: ResolvedValueKind | None = None
    resolved_numeric: Decimal | None = None
    resolved_text: str | None = None
    decimals: str | None = None
    precision: str | None = None
    xml_lang: str | None = None
    scale: int | None = None
    sign: str | None = None
    format_namespace_uri: str | None = None
    format_local_name: str | None = None
    escape: bool | None = None
    continuation_provenance: tuple[Mapping[str, Any], ...] = ()
    source_xml_id: str | None = None
    source_document_relative_path: str | None = None
    source_locator: ElementLocator | None = None

    def __post_init__(self) -> None:
        if self.source_order < 0:
            raise ValueError("source_order must be >= 0")
        if self.is_nil != (self.value_status == "nil"):
            raise ValueError("is_nil and value_status == 'nil' must agree")
        if self.is_nil and (self.resolved_numeric is not None or self.resolved_text is not None):
            raise ValueError("a nil fact must not carry a resolved value")
        if self.resolved_numeric is not None and not self.resolved_numeric.is_finite():
            raise ValueError(f"resolved_numeric must be finite: {self.resolved_numeric!r}")
        _assert_locator_implies_path(
            self.source_document_relative_path,
            self.source_locator,
            what="fact",
        )


@dataclass(frozen=True)
class RelationshipRecord:
    """One effective presentation, calculation, or definition relationship."""

    source_order: int
    network_type: NetworkType
    link_role_uri: str
    arcrole_uri: str
    source_concept: ExpandedQName
    target_concept: ExpandedQName
    order_value: Decimal | None = None
    weight: Decimal | None = None
    preferred_label: str | None = None
    target_role: str | None = None
    attributes: Mapping[str, Any] | None = None
    source_document_relative_path: str | None = None
    source_locator: ElementLocator | None = None

    def __post_init__(self) -> None:
        if self.source_order < 0:
            raise ValueError("source_order must be >= 0")
        if not self.link_role_uri:
            raise ValueError("link_role_uri is required")
        if not self.arcrole_uri:
            raise ValueError("arcrole_uri is required")
        for label, value in (("order_value", self.order_value), ("weight", self.weight)):
            if value is not None and not value.is_finite():
                raise ValueError(f"{label} must be finite: {value!r}")
        _assert_locator_implies_path(
            self.source_document_relative_path,
            self.source_locator,
            what="relationship",
        )


@dataclass(frozen=True)
class ExtractionIssueRecord:
    """Quality issue retained with a source extraction snapshot."""

    component: str
    code: str
    severity: IssueSeverity
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)
    source_document_relative_path: str | None = None
    source_locator: ElementLocator | None = None

    def __post_init__(self) -> None:
        if not self.component:
            raise ValueError("component must be non-empty")
        if not self.code:
            raise ValueError("code must be non-empty")
        _assert_locator_implies_path(
            self.source_document_relative_path,
            self.source_locator,
            what="extraction issue",
        )


@dataclass(frozen=True)
class DocumentBlockRecord:
    """One semantic HTML block occurrence keyed by FilingBundle logical_path."""

    document_relative_path: str
    ordinal: int
    block_type: str
    text: str | None = None
    parent_ordinal: int | None = None
    heading_level: int | None = None
    source_locator: Mapping[str, Any] = field(default_factory=dict)
    parser_version: str = ""

    def __post_init__(self) -> None:
        if not self.document_relative_path:
            raise ValueError("document_relative_path must be non-empty")
        if self.ordinal < 0:
            raise ValueError("ordinal must be >= 0")
        if self.parent_ordinal is not None and self.parent_ordinal >= self.ordinal:
            raise ValueError("parent_ordinal must precede ordinal")
        if not self.block_type:
            raise ValueError("block_type must be non-empty")
        if self.block_type == "heading":
            if self.heading_level is None or not (1 <= self.heading_level <= 6):
                raise ValueError("heading blocks require heading_level 1..6")
        elif self.heading_level is not None:
            raise ValueError("non-heading blocks must have heading_level=None")
        if self.text is not None and self.text == "":
            raise ValueError("empty string text is forbidden; use NULL for structural blocks")
        if not self.parser_version:
            raise ValueError("parser_version must be non-empty")
        scheme = self.source_locator.get("scheme")
        value = self.source_locator.get("value")
        if scheme != "html-xpath-v1" or not isinstance(value, str) or not value:
            raise ValueError(
                "source_locator must be {scheme: 'html-xpath-v1', value: <non-empty str>}"
            )


@dataclass(frozen=True)
class FilingSectionRecord:
    """One regulatory section range over block ordinals within a document."""

    document_relative_path: str
    section_key: str
    start_block_ordinal: int
    end_block_ordinal_exclusive: int
    method: str
    confidence_score: int = 0

    def __post_init__(self) -> None:
        if not self.document_relative_path:
            raise ValueError("document_relative_path must be non-empty")
        if not self.section_key:
            raise ValueError("section_key must be non-empty")
        if not (0 <= self.start_block_ordinal < self.end_block_ordinal_exclusive):
            raise ValueError("invalid section range")
        if not self.method:
            raise ValueError("method must be non-empty")
        if not (0 <= self.confidence_score <= 100):
            raise ValueError("confidence_score must be 0..100")


@dataclass(frozen=True)
class ReportExtraction:
    """Complete source extraction for one XBRL report input."""

    report_input: dict[str, Any]
    report_key: str
    extractor_version: str
    arelle_version: str
    arelle_item_fact_count: int
    concepts: tuple[ConceptRecord, ...] = ()
    declarations: tuple[ConceptDeclarationRecord, ...] = ()
    labels: tuple[ConceptLabelRecord, ...] = ()
    references: tuple[ConceptReferenceRecord, ...] = ()
    contexts: tuple[ContextRecord, ...] = ()
    dimensions: tuple[ContextDimensionRecord, ...] = ()
    units: tuple[UnitRecord, ...] = ()
    measures: tuple[UnitMeasureRecord, ...] = ()
    facts: tuple[FactRecord, ...] = ()
    relationships: tuple[RelationshipRecord, ...] = ()
    issues: tuple[ExtractionIssueRecord, ...] = ()

    def __post_init__(self) -> None:
        if self.arelle_item_fact_count < 0:
            raise ValueError("arelle_item_fact_count must be >= 0")
        if len(self.report_key) != 64:
            raise ValueError("report_key must be a 64-char hex digest")


@dataclass(frozen=True)
class FilingExtraction:
    """Filing-scoped source extraction (XBRL reports + future document output)."""

    reports: tuple[ReportExtraction, ...]
    document_blocks: tuple[DocumentBlockRecord, ...] = ()
    filing_sections: tuple[FilingSectionRecord, ...] = ()
    issues: tuple[ExtractionIssueRecord, ...] = ()

    def __post_init__(self) -> None:
        if not self.reports:
            raise ValueError("FilingExtraction requires at least one report")
