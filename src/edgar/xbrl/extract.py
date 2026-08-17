"""Arelle ``ModelXbrl`` → native ``ReportExtraction`` (ADR 0011).

This module is the only place that reads Arelle in-memory objects. Everything it
emits is a plain source-layer record from :mod:`edgar.xbrl.source_records`, so no
engine object can cross the adapter boundary.

Interpretation rules this extraction commits to:

- **Attribution.** Every record is attributed to the canonical
  ``UriBinding.document_uri`` that owns the bytes. Alias URIs are mapped to
  their primary binding; the Arelle IXDS surrogate is never a source document
  because it has no bytes of its own. An unattributable document is incoherent.
- **Periods.** Period fields keep the *filed lexical* value of ``xbrli:instant``
  / ``startDate`` / ``endDate``. Arelle determines period kind and whether the
  context is representable. ``instantDatetime`` / ``endDatetime`` may be used
  only to establish that Arelle successfully represents a dateTime-valued
  boundary; they are never copied into source fields or compared as though
  their calendar date were the filed lexical date. A period Arelle cannot
  represent is incoherent.
- **Dimensions.** Only *filed* occurrences are read, from ``segDimValues`` /
  ``scenDimValues`` plus ``errorDimValues`` (duplicate or unresolvable filed
  occurrences). ``dimValue()``, ``dimMemberQname(includeDefaults=True)``, and
  ``qnameDimensionDefaults`` are never consulted, so an axis whose default is
  declared in the DTS but not filed in a context yields zero dimension rows.
- **Facts.** One record per source occurrence, never deduplicated. Tuples are
  unsupported in Phase 1: they raise an incompleteness issue and their item
  children are still projected. ``decimals`` / ``precision`` come from the filed
  attributes rather than Arelle's type-default-aware properties, and stay
  textual because ``INF`` is legal. ``xml:lang`` is the filed or inherited
  attribute only, never a disclosure-system default.
- **Numerics.** Only exact ``Decimal`` / ``int`` resolved values are persisted
  as numerics; binary floating point is never coerced.
- **QNames.** Resolved QName-valued content is serialized in Clark notation
  (``{namespace}local``) and every QName-valued field is prefix-independent.
- **Relationships.** Exactly one pass per *exact* base set (both the link QName
  and the arc QName slots non-``None``); aggregate base-set keys are never
  enumerated. Only presentation, calculation, and definition networks are
  projected as relationships, plus the supported concept-label and
  concept-reference resource classes. Other arcroles are either documented
  exclusions or explicit incompleteness.

Two failure modes are distinguished:

- *Incompleteness* — the evidence is projected but the projection cannot be
  marked complete. Recorded as a ``fatal`` :class:`SemanticIssueRecord`; see
  :func:`semantic_status`.
- *Incoherence* — a faithful projection cannot be materialized at all. Raised
  as :class:`SemanticExtractionError`; per ADR 0008 §10 such a report may
  legitimately leave no projection.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal, cast

import lxml.etree as etree

from edgar.domain.bundle import UriBinding, XbrlReportInput
from edgar.xbrl._source_build import SourceBuildError, build_report_extraction
from edgar.xbrl.arelle_env import arelle_version
from edgar.xbrl.config import (
    SemanticConfig,
    build_semantic_config,
)
from edgar.xbrl.diagnostics import UNSTRUCTURED_CODE, classify_diagnostic
from edgar.xbrl.locators import LocatorError, element_locator
from edgar.xbrl.records import (
    ArcroleDeclarationRecord,
    ConceptDeclarationRecord,
    ConceptLabelRecord,
    ConceptReferenceRecord,
    ContextDimensionRecord,
    ContextElement,
    ContextRecord,
    CyclesAllowed,
    DiagnosticRecord,
    DiagnosticSeverity,
    ExpandedQName,
    FactRecord,
    IssueSeverity,
    MeasureRole,
    NetworkType,
    PeriodKind,
    PeriodType,
    ReferencePartRecord,
    RelationshipRecord,
    ResolvedValueKind,
    RoleDeclarationRecord,
    SemanticIssueRecord,
    SourceLocator,
    UnitMeasureRecord,
    UnitRecord,
    ValueStatus,
)
from edgar.xbrl.source_records import EXTRACTOR_VERSION, ReportExtraction
from edgar.xbrl.uri import UriIdentityError, normalize_uri

ENGINE_NAME = "arelle"

XBRLI_NS = "http://www.xbrl.org/2003/instance"
XBRLDT_NS = "http://xbrl.org/2005/xbrldt"
LINK_NS = "http://www.xbrl.org/2003/linkbase"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"

XML_LANG_ATTRIBUTE = f"{{{XML_NS}}}lang"
XLINK_ROLE_ATTRIBUTE = f"{{{XLINK_NS}}}role"

MEASURE_TAG = f"{{{XBRLI_NS}}}measure"
DIVIDE_TAG = f"{{{XBRLI_NS}}}divide"
UNIT_NUMERATOR_TAG = f"{{{XBRLI_NS}}}unitNumerator"
UNIT_DENOMINATOR_TAG = f"{{{XBRLI_NS}}}unitDenominator"
PERIOD_TAG = f"{{{XBRLI_NS}}}period"
INSTANT_TAG = f"{{{XBRLI_NS}}}instant"
START_DATE_TAG = f"{{{XBRLI_NS}}}startDate"
END_DATE_TAG = f"{{{XBRLI_NS}}}endDate"
FOREVER_TAG = f"{{{XBRLI_NS}}}forever"
ENTITY_TAG = f"{{{XBRLI_NS}}}entity"
IDENTIFIER_TAG = f"{{{XBRLI_NS}}}identifier"

DEFINITION_LINK_TAG = f"{{{LINK_NS}}}definitionLink"
LABEL_RESOURCE_TAG = f"{{{LINK_NS}}}label"
REFERENCE_RESOURCE_TAG = f"{{{LINK_NS}}}reference"

CLOSED_ATTRIBUTE = f"{{{XBRLDT_NS}}}closed"
USABLE_ATTRIBUTE = f"{{{XBRLDT_NS}}}usable"
TARGET_ROLE_ATTRIBUTE = f"{{{XBRLDT_NS}}}targetRole"
CONTEXT_ELEMENT_ATTRIBUTE = f"{{{XBRLDT_NS}}}contextElement"

# Arelle validity codes (arelle.XmlValidateConst); values >= VALID are valid.
_ARELLE_INVALID = 2
_ARELLE_VALID = 4

_MAX_CONTINUATION_DEPTH = 10_000

SemanticStatus = Literal["complete", "incomplete"]

# --- Incoherence codes: a faithful projection cannot be materialized. --------
UNATTRIBUTABLE_SOURCE_DOCUMENT = "UNATTRIBUTABLE_SOURCE_DOCUMENT"
SOURCE_LOCATOR_UNAVAILABLE = "SOURCE_LOCATOR_UNAVAILABLE"
INCOHERENT_CONCEPT_DECLARATION = "INCOHERENT_CONCEPT_DECLARATION"
INCOHERENT_CONTEXT_IDENTITY = "INCOHERENT_CONTEXT_IDENTITY"
INCOHERENT_CONTEXT_PERIOD = "INCOHERENT_CONTEXT_PERIOD"
INCOHERENT_CONTEXT_ENTITY = "INCOHERENT_CONTEXT_ENTITY"
UNREPRESENTABLE_CONTEXT_DIMENSION = "UNREPRESENTABLE_CONTEXT_DIMENSION"
INCOHERENT_UNIT_IDENTITY = "INCOHERENT_UNIT_IDENTITY"
UNRESOLVED_UNIT_MEASURE = "UNRESOLVED_UNIT_MEASURE"
UNRESOLVED_FACT_CONCEPT = "UNRESOLVED_FACT_CONCEPT"
UNRESOLVED_FACT_CONTEXT = "UNRESOLVED_FACT_CONTEXT"
UNRESOLVED_FACT_UNIT_ROW = "UNRESOLVED_FACT_UNIT_ROW"
UNDEFINED_FACT_ELEMENT = "UNDEFINED_FACT_ELEMENT"
RECORD_SET_INVALID = "RECORD_SET_INVALID"
RELATIONSHIP_SET_LOAD_FAILED = "RELATIONSHIP_SET_LOAD_FAILED"
ENDPOINT_FAMILY_MISMATCH = "ENDPOINT_FAMILY_MISMATCH"
MISSING_NETWORK_ROLE = "MISSING_NETWORK_ROLE"
UNAVAILABLE_ARC_OCCURRENCE = "UNAVAILABLE_ARC_OCCURRENCE"

# --- Incompleteness codes: evidence is kept; severity depends on V2 allow-list. -
UNSUPPORTED_TUPLE_FACT = "UNSUPPORTED_TUPLE_FACT"
UNSUPPORTED_FRACTION_FACT = "UNSUPPORTED_FRACTION_FACT"
UNRESOLVED_REQUIRED_UNIT = "UNRESOLVED_REQUIRED_UNIT"
UNEXPECTED_UNIT_REFERENCE = "UNEXPECTED_UNIT_REFERENCE"
INEXACT_NUMERIC_VALUE = "INEXACT_NUMERIC_VALUE"
UNSUPPORTED_RESOLVED_VALUE = "UNSUPPORTED_RESOLVED_VALUE"
UNAVAILABLE_FACT_LEXICAL_VALUE = "UNAVAILABLE_FACT_LEXICAL_VALUE"
UNSUPPORTED_INLINE_SIGN = "UNSUPPORTED_INLINE_SIGN"
INVALID_INLINE_SCALE = "INVALID_INLINE_SCALE"
UNRESOLVED_INLINE_FORMAT = "UNRESOLVED_INLINE_FORMAT"
UNSUPPORTED_NON_DIMENSIONAL_CONTEXT_CONTENT = "UNSUPPORTED_NON_DIMENSIONAL_CONTEXT_CONTENT"
DUPLICATE_CONCEPT_DECLARATION = "DUPLICATE_CONCEPT_DECLARATION"
UNSUPPORTED_ARCROLE = "UNSUPPORTED_ARCROLE"
EXCLUDED_ARCROLE = "EXCLUDED_ARCROLE"
DEFERRED_ARCROLE = "DEFERRED_ARCROLE"
INVALID_ARC_ORDER = "INVALID_ARC_ORDER"
INVALID_ARC_WEIGHT = "INVALID_ARC_WEIGHT"
INVALID_ARC_ATTRIBUTE = "INVALID_ARC_ATTRIBUTE"
UNSUPPORTED_CYCLES_ALLOWED = "UNSUPPORTED_CYCLES_ALLOWED"
UNSUPPORTED_RESOURCE_CLASS = "UNSUPPORTED_RESOURCE_CLASS"
UNPRESERVED_REFERENCE_PART = "UNPRESERVED_REFERENCE_PART"
BLOCKING_ENGINE_DIAGNOSTIC = "BLOCKING_ENGINE_DIAGNOSTIC"

# Fail-closed: former Phase-1 incomplete codes are fatal unless listed here.
NONFATAL_ISSUE_CODES: frozenset[str] = frozenset(
    {
        DEFERRED_ARCROLE,
        UNSUPPORTED_ARCROLE,
        EXCLUDED_ARCROLE,
        UNSUPPORTED_TUPLE_FACT,
        UNSUPPORTED_FRACTION_FACT,
        UNSUPPORTED_INLINE_SIGN,
        INVALID_INLINE_SCALE,
        UNRESOLVED_INLINE_FORMAT,
        UNAVAILABLE_FACT_LEXICAL_VALUE,
        INEXACT_NUMERIC_VALUE,
        UNSUPPORTED_RESOLVED_VALUE,
        UNRESOLVED_REQUIRED_UNIT,
        UNEXPECTED_UNIT_REFERENCE,
    }
)

_SUPPORTED_CONCEPT_NETWORKS = frozenset({"presentation", "calculation", "definition"})


class UnattributableSourceDocument(ValueError):
    """Raised when a model object cannot be attributed to a bound source document."""


class SemanticExtractionError(RuntimeError):
    """Raised when a coherent semantic projection cannot be materialized.

    ``issues`` carries the incoherence evidence so a projection attempt can
    still persist quality issues even though no projection exists.
    """

    def __init__(self, message: str, issues: Sequence[SemanticIssueRecord] = ()) -> None:
        super().__init__(message)
        self.issues: tuple[SemanticIssueRecord, ...] = tuple(issues)


@lru_cache(maxsize=1)
def _ixds_markers() -> tuple[str, str]:
    """``(document separator, surrogate basename)`` of Arelle's IXDS pseudo-URI."""
    from arelle.UrlUtil import IXDS_DOC_SEPARATOR, IXDS_SURROGATE

    return IXDS_DOC_SEPARATOR, IXDS_SURROGATE.partition(IXDS_DOC_SEPARATOR)[0]


def _is_ixds_surrogate(uri: str) -> bool:
    separator, surrogate_name = _ixds_markers()
    return separator in uri or uri.rpartition("/")[2] == surrogate_name


def _owning_document(model_object: Any) -> Any:
    document = getattr(model_object, "modelDocument", None)
    return model_object if document is None else document


def canonical_source_document_uri(model_object: Any, bound_inputs: Any) -> str:
    """Canonical binding URI of the document owning ``model_object``'s bytes.

    ``bound_inputs`` is the worker's bound-input view: ``aliases`` maps an alias
    URI to its primary binding URI, and ``documents`` (when present) is keyed by
    primary binding URI. The Arelle IXDS surrogate is never returned.

    Raises :class:`UnattributableSourceDocument` when no canonical binding URI
    can be established.
    """
    document = _owning_document(model_object)
    raw_uri = getattr(document, "uri", None)
    if not isinstance(raw_uri, str) or not raw_uri:
        raise UnattributableSourceDocument(
            f"model object has no source document URI: {type(model_object).__name__}"
        )
    if _is_ixds_surrogate(raw_uri):
        raise UnattributableSourceDocument(f"IXDS surrogate is not a source document: {raw_uri!r}")
    try:
        canonical = normalize_uri(raw_uri.split("#", 1)[0])
    except UriIdentityError as exc:
        raise UnattributableSourceDocument(f"non-canonical source document URI: {exc}") from exc
    aliases = getattr(bound_inputs, "aliases", None)
    if isinstance(aliases, Mapping):
        canonical = str(aliases.get(canonical, canonical))
    documents = getattr(bound_inputs, "documents", None)
    if isinstance(documents, Mapping) and canonical not in documents:
        raise UnattributableSourceDocument(f"document URI is not a bound input: {canonical}")
    return canonical


class _DocumentUriResolver:
    """Alias-aware, binding-validated document attribution with memoization."""

    def __init__(self, bound_inputs: Any, primary_uris: frozenset[str]) -> None:
        self._bound_inputs = bound_inputs
        self._primary_uris = primary_uris
        self._cache: dict[str, str] = {}

    def resolve(self, model_object: Any) -> str:
        raw_uri = getattr(_owning_document(model_object), "uri", None)
        key = raw_uri if isinstance(raw_uri, str) else ""
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        canonical = canonical_source_document_uri(model_object, self._bound_inputs)
        if canonical not in self._primary_uris:
            raise UnattributableSourceDocument(
                f"document URI is not an authoritative binding: {canonical}"
            )
        if key:
            self._cache[key] = canonical
        return canonical

    def resolve_uri(self, text: str) -> str | None:
        """Map a raw reference URI to its primary binding, or ``None``."""
        if not text or _is_ixds_surrogate(text):
            return None
        try:
            canonical = normalize_uri(text.split("#", 1)[0])
        except UriIdentityError:
            return None
        aliases = getattr(self._bound_inputs, "aliases", None)
        if isinstance(aliases, Mapping):
            canonical = str(aliases.get(canonical, canonical))
        return canonical if canonical in self._primary_uris else None


@dataclass
class _Extraction:
    """Mutable extraction state: attribution, issues, and incoherence evidence."""

    config: SemanticConfig
    resolver: _DocumentUriResolver
    issues: list[SemanticIssueRecord] = field(default_factory=list)
    errors: list[SemanticIssueRecord] = field(default_factory=list)

    def incomplete(
        self,
        code: str,
        message: str,
        *,
        locator: SourceLocator | None = None,
        context: Mapping[str, Any] | None = None,
        severity: IssueSeverity | None = None,
    ) -> None:
        if severity is None:
            if code in NONFATAL_ISSUE_CODES:
                severity = "info" if code == EXCLUDED_ARCROLE else "warning"
            else:
                severity = "fatal"
        self.issues.append(
            SemanticIssueRecord(
                severity=severity,
                code=code,
                message=message,
                locator=locator,
                context=dict(context or {}),
            )
        )

    def observe(
        self,
        code: str,
        message: str,
        *,
        locator: SourceLocator | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        """Record evidence that does not refuse semantic completeness."""
        self.incomplete(code, message, locator=locator, context=context, severity="info")

    def incoherent(
        self,
        code: str,
        message: str,
        *,
        locator: SourceLocator | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        record = SemanticIssueRecord(
            severity="fatal",
            code=code,
            message=message,
            locator=locator,
            context=dict(context or {}),
        )
        self.errors.append(record)
        self.issues.append(record)

    def locator(self, element: Any, *, what: str) -> SourceLocator | None:
        """Locator for one element, or ``None`` after recording incoherence."""
        try:
            document_uri = self.resolver.resolve(element)
        except UnattributableSourceDocument as exc:
            self.incoherent(UNATTRIBUTABLE_SOURCE_DOCUMENT, f"{what}: {exc}")
            return None
        try:
            return element_locator(element, document_uri=document_uri)
        except (LocatorError, ValueError) as exc:
            self.incoherent(SOURCE_LOCATOR_UNAVAILABLE, f"{what}: {exc}")
            return None


def _expanded_qname(qname: Any) -> ExpandedQName | None:
    """Prefix-independent identity of an Arelle ``QName``; ``None`` if unusable."""
    if qname is None:
        return None
    local_name = getattr(qname, "localName", None)
    namespace_uri = getattr(qname, "namespaceURI", None)
    if not isinstance(local_name, str) or not local_name:
        return None
    namespace = namespace_uri if isinstance(namespace_uri, str) and namespace_uri else None
    try:
        return ExpandedQName(namespace_uri=namespace, local_name=local_name)
    except ValueError:
        return None


def _clark(qname: Any) -> str | None:
    expanded = _expanded_qname(qname)
    return None if expanded is None else expanded.clark


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _text_content(element: Any) -> str:
    """Exact concatenated character data of a subtree (comment text excluded)."""
    parts: list[str] = [element.text or ""]
    for child in element:
        if isinstance(child.tag, str):
            parts.append(_text_content(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _serialize_fragment(element: Any) -> str | None:
    """Namespace-complete serialization (``xml-fragment-v1``) of one subtree.

    Inclusive XML C14N 1.0 is used because it emits every in-scope namespace
    declaration, so the fragment stays self-contained even when its content is
    QName-valued.
    """
    try:
        serialized = etree.tostring(element, method="c14n", with_comments=True)
    except (etree.C14NError, ValueError, TypeError):
        return None
    return serialized.decode("utf-8") if isinstance(serialized, bytes) else str(serialized)


def _inherited_xml_lang(element: Any) -> str | None:
    """Filed or inherited ``xml:lang``; a disclosure-system default is never used."""
    current = element
    while current is not None and isinstance(getattr(current, "tag", None), str):
        value = current.get(XML_LANG_ATTRIBUTE)
        if value is not None:
            return value or None
        current = current.getparent()
    return None


def _optional_bool_attribute(raw: str | None) -> bool | None:
    if raw in ("true", "1"):
        return True
    if raw in ("false", "0"):
        return False
    return None


def _finite_decimal(value: Any) -> Decimal | None:
    if isinstance(value, Decimal) and value.is_finite():
        return value
    return None


def _exact_numeric(value: Any) -> Decimal | int | None:
    """Exact filed numeric only: binary floating point is never coerced."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return _finite_decimal(value)


def _resolved_non_numeric(
    value: Any, *, type_local_name: str | None = None
) -> tuple[str | None, str | None, bool]:
    """``(text, kind, supported)`` for an Arelle-resolved non-numeric typed value.

    Kind is assigned from the runtime type; string content is never inspected to
    invent a ``qname`` kind (ordinary ``{ns}local`` text stays ``text``).

    Arelle resolves ``dateItemType`` values as midnight ``datetime`` objects;
    when the concept type is ``dateItemType``, kind is ``date`` (not ``datetime``).
    """
    if value is None:
        return None, None, True
    if isinstance(value, bool):
        return ("true" if value else "false"), "boolean", True
    if isinstance(value, datetime):
        if type_local_name == "dateItemType":
            return value.date().isoformat(), "date", True
        return value.isoformat(), "datetime", True
    if isinstance(value, date):
        return value.isoformat(), "date", True
    if isinstance(value, time):
        return value.isoformat(), "time", True
    if isinstance(value, str):
        return value, "text", True
    if isinstance(value, Decimal | int):
        return str(value), "text", True
    clark = _clark(value)
    if clark is not None:
        return clark, "qname", True
    from edgar.xbrl.resolved_text import encode_list, encode_supported_resolved

    if isinstance(value, list):
        text = encode_list(value)
        if text is None:
            return None, None, False
        return text, "text", True
    text, supported = encode_supported_resolved(value)
    if supported and text is not None:
        return text, "text", True
    return None, None, False


# --------------------------------------------------------------------------- #
# Concept declarations
# --------------------------------------------------------------------------- #


def _concept_declarations(
    model_xbrl: Any, extraction: _Extraction
) -> tuple[ConceptDeclarationRecord, ...]:
    """Projection-scoped effective declaration of every DTS element identity."""
    records: dict[ExpandedQName, ConceptDeclarationRecord] = {}
    for key, concept in (getattr(model_xbrl, "qnameConcepts", None) or {}).items():
        identity = _expanded_qname(getattr(concept, "qname", None)) or _expanded_qname(key)
        if identity is None:
            extraction.incoherent(
                INCOHERENT_CONCEPT_DECLARATION,
                f"concept declaration without a usable QName: {key!r}",
            )
            continue
        locator = extraction.locator(concept, what=f"concept {identity.clark}")
        if locator is None:
            continue
        period_type = getattr(concept, "periodType", None)
        balance = getattr(concept, "balance", None)
        record = ConceptDeclarationRecord(
            concept=identity,
            source_locator=locator,
            data_type=_expanded_qname(getattr(concept, "typeQname", None)),
            substitution_group=_expanded_qname(getattr(concept, "substitutionGroupQname", None)),
            period_type=(
                cast(PeriodType, period_type) if period_type in ("instant", "duration") else None
            ),
            balance=(cast(Any, balance) if balance in ("debit", "credit") else None),
            abstract=_optional_bool(getattr(concept, "isAbstract", None)),
            nillable=_optional_bool(getattr(concept, "isNillable", None)),
        )
        existing = records.get(identity)
        if existing is None:
            records[identity] = record
            continue
        if existing.source_locator == record.source_locator:
            continue
        extraction.incomplete(
            DUPLICATE_CONCEPT_DECLARATION,
            f"concept {identity.clark} is declared by more than one element of this DTS",
            locator=record.source_locator,
            context={"other_locator": existing.source_locator.to_dict()},
        )
        if record.source_locator.sort_key() < existing.source_locator.sort_key():
            records[identity] = record
    return tuple(sorted(records.values(), key=lambda item: item.concept.sort_key()))


# --------------------------------------------------------------------------- #
# Role and arcrole declarations
# --------------------------------------------------------------------------- #


def _used_on(role_type: Any) -> tuple[ExpandedQName, ...]:
    used = {
        expanded
        for expanded in (
            _expanded_qname(value) for value in getattr(role_type, "usedOns", None) or ()
        )
        if expanded is not None
    }
    return tuple(sorted(used, key=lambda item: item.sort_key()))


def _role_declarations(
    model_xbrl: Any, extraction: _Extraction
) -> tuple[RoleDeclarationRecord, ...]:
    records: list[RoleDeclarationRecord] = []
    for uri, role_types in (getattr(model_xbrl, "roleTypes", None) or {}).items():
        for role_type in role_types:
            role_uri = getattr(role_type, "roleURI", None) or uri
            if not isinstance(role_uri, str) or not role_uri:
                continue
            locator = extraction.locator(role_type, what=f"roleType {role_uri}")
            if locator is None:
                continue
            records.append(
                RoleDeclarationRecord(
                    role_uri=role_uri,
                    source_locator=locator,
                    definition=_optional_str(getattr(role_type, "definition", None)),
                    used_on=_used_on(role_type),
                )
            )
    records.sort(key=lambda item: (item.role_uri, item.source_locator.sort_key()))
    return tuple(records)


def _arcrole_declarations(
    model_xbrl: Any, extraction: _Extraction
) -> tuple[ArcroleDeclarationRecord, ...]:
    records: list[ArcroleDeclarationRecord] = []
    for uri, role_types in (getattr(model_xbrl, "arcroleTypes", None) or {}).items():
        for role_type in role_types:
            arcrole_uri = getattr(role_type, "arcroleURI", None) or uri
            if not isinstance(arcrole_uri, str) or not arcrole_uri:
                continue
            locator = extraction.locator(role_type, what=f"arcroleType {arcrole_uri}")
            if locator is None:
                continue
            cycles = getattr(role_type, "cyclesAllowed", None)
            if cycles is not None and cycles not in ("any", "undirected", "none"):
                extraction.incomplete(
                    UNSUPPORTED_CYCLES_ALLOWED,
                    f"arcrole {arcrole_uri} declares unsupported cyclesAllowed {cycles!r}",
                    locator=locator,
                )
                cycles = None
            records.append(
                ArcroleDeclarationRecord(
                    arcrole_uri=arcrole_uri,
                    source_locator=locator,
                    definition=_optional_str(getattr(role_type, "definition", None)),
                    used_on=_used_on(role_type),
                    cycles_allowed=cast(CyclesAllowed | None, cycles),
                )
            )
    records.sort(key=lambda item: (item.arcrole_uri, item.source_locator.sort_key()))
    return tuple(records)


# --------------------------------------------------------------------------- #
# Contexts and filed dimensions
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _ContextProjection:
    contexts: tuple[ContextRecord, ...]
    dimensions: tuple[ContextDimensionRecord, ...]
    locators: Mapping[str, SourceLocator]


def _period_fields(
    context: Any, extraction: _Extraction, locator: SourceLocator
) -> tuple[PeriodKind, str | None, str | None, str | None] | None:
    """Filed lexical period fields, cross-checked against unadjusted engine dates."""
    period = context.find(PERIOD_TAG)
    if period is None:
        extraction.incoherent(
            INCOHERENT_CONTEXT_PERIOD, "context has no xbrli:period", locator=locator
        )
        return None
    forever = period.find(FOREVER_TAG)
    instant = period.find(INSTANT_TAG)
    start = period.find(START_DATE_TAG)
    end = period.find(END_DATE_TAG)
    present = [
        kind for kind, node in (("forever", forever), ("instant", instant)) if node is not None
    ]
    if start is not None or end is not None:
        present.append("duration")
    if len(present) != 1:
        extraction.incoherent(
            INCOHERENT_CONTEXT_PERIOD,
            f"context period is not exactly one of forever/instant/duration: {present}",
            locator=locator,
        )
        return None
    if forever is not None:
        return "forever", None, None, None
    if instant is not None:
        lexical = _text_content(instant).strip()
        representable = (
            getattr(context, "instantDate", None) is not None
            or getattr(context, "instantDatetime", None) is not None
        )
        if not lexical or not representable:
            extraction.incoherent(
                INCOHERENT_CONTEXT_PERIOD,
                f"instant period is not representable: {lexical!r}",
                locator=locator,
            )
            return None
        return "instant", lexical, None, None
    if start is None or end is None:
        extraction.incoherent(
            INCOHERENT_CONTEXT_PERIOD,
            "duration period requires both startDate and endDate",
            locator=locator,
        )
        return None
    start_lexical = _text_content(start).strip()
    end_lexical = _text_content(end).strip()
    start_representable = getattr(context, "startDatetime", None) is not None
    end_representable = (
        getattr(context, "endDate", None) is not None
        or getattr(context, "endDatetime", None) is not None
    )
    if not start_lexical or not end_lexical or not start_representable or not end_representable:
        extraction.incoherent(
            INCOHERENT_CONTEXT_PERIOD,
            f"duration period is not representable: {start_lexical!r}..{end_lexical!r}",
            locator=locator,
        )
        return None
    return "duration", None, start_lexical, end_lexical


def _entity_fields(
    context: Any, extraction: _Extraction, locator: SourceLocator
) -> tuple[str, str] | None:
    entity = context.find(ENTITY_TAG)
    identifier = None if entity is None else entity.find(IDENTIFIER_TAG)
    if identifier is None:
        extraction.incoherent(
            INCOHERENT_CONTEXT_ENTITY,
            "context has no xbrli:entity/xbrli:identifier",
            locator=locator,
        )
        return None
    scheme = identifier.get("scheme")
    resolved = getattr(identifier, "xValue", None)
    # xbrli:identifier is xs:token, so the collapsed form is the filed value.
    value = resolved if isinstance(resolved, str) else " ".join(_text_content(identifier).split())
    if not scheme or not value:
        extraction.incoherent(
            INCOHERENT_CONTEXT_ENTITY,
            f"context entity identifier is incomplete: scheme={scheme!r} value={value!r}",
            locator=locator,
        )
        return None
    return scheme, value


def _mark_non_dimensional_content(
    nodes: Sequence[Any],
    extraction: _Extraction,
    *,
    element: str,
    locator: SourceLocator,
) -> None:
    """Phase 1B: detect non-dimensional segment/scenario → incomplete (no XML)."""
    if any(isinstance(getattr(node, "tag", None), str) for node in nodes):
        extraction.incomplete(
            UNSUPPORTED_NON_DIMENSIONAL_CONTEXT_CONTENT,
            f"non-dimensional {element} content is not projected under "
            "non_dimensional_context_policy=incomplete",
            locator=locator,
        )


def _context_element_of(
    dim_value: Any, extraction: _Extraction, locator: SourceLocator
) -> str | None:
    parent = dim_value.getparent()
    local_name = getattr(parent, "tag", "")
    local_name = local_name.rpartition("}")[2] if isinstance(local_name, str) else ""
    if local_name in ("segment", "scenario"):
        return local_name
    extraction.incoherent(
        UNREPRESENTABLE_CONTEXT_DIMENSION,
        f"filed dimension is not inside a segment or scenario: {local_name!r}",
        locator=locator,
    )
    return None


def _dimension_record(
    dim_value: Any, *, context_locator: SourceLocator, extraction: _Extraction
) -> ContextDimensionRecord | None:
    locator = extraction.locator(dim_value, what="context dimension")
    if locator is None:
        return None
    dimension = _expanded_qname(getattr(dim_value, "dimensionQname", None))
    if dimension is None:
        extraction.incoherent(
            UNREPRESENTABLE_CONTEXT_DIMENSION,
            "filed dimension has no resolvable dimension QName",
            locator=locator,
        )
        return None
    context_element = _context_element_of(dim_value, extraction, locator)
    if context_element is None:
        return None
    if getattr(dim_value, "isExplicit", False):
        member = _expanded_qname(getattr(dim_value, "memberQname", None))
        if member is None:
            extraction.incoherent(
                UNREPRESENTABLE_CONTEXT_DIMENSION,
                f"explicit member of {dimension.clark} has no resolvable QName",
                locator=locator,
            )
            return None
        return ContextDimensionRecord(
            context_locator=context_locator,
            dimension=dimension,
            context_element=cast(ContextElement, context_element),
            member_kind="explicit",
            source_locator=locator,
            member=member,
        )
    typed_member = getattr(dim_value, "typedMember", None)
    fragment = None if typed_member is None else _serialize_fragment(typed_member)
    if fragment is None:
        extraction.incoherent(
            UNREPRESENTABLE_CONTEXT_DIMENSION,
            f"typed member of {dimension.clark} could not be preserved losslessly",
            locator=locator,
        )
        return None
    return ContextDimensionRecord(
        context_locator=context_locator,
        dimension=dimension,
        context_element=cast(ContextElement, context_element),
        member_kind="typed",
        source_locator=locator,
        typed_member_xml=fragment,
        typed_member_sha256=hashlib.sha256(fragment.encode("utf-8")).hexdigest(),
    )


def _context_projection(model_xbrl: Any, extraction: _Extraction) -> _ContextProjection:
    contexts: list[ContextRecord] = []
    dimensions: list[ContextDimensionRecord] = []
    locators: dict[str, SourceLocator] = {}
    for context_id, context in (getattr(model_xbrl, "contexts", None) or {}).items():
        locator = extraction.locator(context, what=f"context {context_id}")
        if locator is None:
            continue
        source_context_id = _optional_str(getattr(context, "id", None)) or _optional_str(context_id)
        if source_context_id is None:
            extraction.incoherent(
                INCOHERENT_CONTEXT_IDENTITY, "context has no id attribute", locator=locator
            )
            continue
        period = _period_fields(context, extraction, locator)
        entity = _entity_fields(context, extraction, locator)
        if period is None or entity is None:
            continue
        period_kind, instant, start, end = period
        scheme, identifier = entity
        contexts.append(
            ContextRecord(
                source_context_id=source_context_id,
                entity_scheme=scheme,
                entity_identifier=identifier,
                period_kind=period_kind,
                source_locator=locator,
                period_instant=instant,
                period_start=start,
                period_end=end,
            )
        )
        _mark_non_dimensional_content(
            list(getattr(context, "segNonDimValues", None) or ()),
            extraction,
            element="segment",
            locator=locator,
        )
        _mark_non_dimensional_content(
            list(getattr(context, "scenNonDimValues", None) or ()),
            extraction,
            element="scenario",
            locator=locator,
        )
        locators[source_context_id] = locator
        # Filed occurrences only: segment/scenario dimension values plus the
        # duplicate or unresolvable occurrences Arelle diverts to errorDimValues.
        filed: list[Any] = []
        filed.extend((getattr(context, "segDimValues", None) or {}).values())
        filed.extend((getattr(context, "scenDimValues", None) or {}).values())
        filed.extend(getattr(context, "errorDimValues", None) or ())
        for dim_value in filed:
            record = _dimension_record(dim_value, context_locator=locator, extraction=extraction)
            if record is not None:
                dimensions.append(record)
    contexts.sort(key=lambda item: item.source_locator.sort_key())
    dimensions.sort(
        key=lambda item: (
            item.context_locator.sort_key(),
            item.source_locator.sort_key(),
            item.dimension.sort_key(),
        )
    )
    return _ContextProjection(
        contexts=tuple(contexts), dimensions=tuple(dimensions), locators=locators
    )


# --------------------------------------------------------------------------- #
# Units and measures
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _UnitProjection:
    units: tuple[UnitRecord, ...]
    measures: tuple[UnitMeasureRecord, ...]
    locators: Mapping[str, SourceLocator]


def _filed_measure_count(parent: Any) -> int:
    return sum(1 for _ in parent.iterchildren(MEASURE_TAG))


def _measure_rows(
    unit: Any,
    *,
    unit_locator: SourceLocator,
    divide: bool,
    extraction: _Extraction,
) -> list[UnitMeasureRecord]:
    """Expanded measure QNames, ordered by ``(namespace, local)``; duplicates kept."""
    numerator, denominator = getattr(unit, "measures", ((), ()))
    if divide:
        divide_element = unit.find(DIVIDE_TAG)
        numerator_parent = (
            None if divide_element is None else divide_element.find(UNIT_NUMERATOR_TAG)
        )
        denominator_parent = (
            None if divide_element is None else divide_element.find(UNIT_DENOMINATOR_TAG)
        )
        filed_counts = (
            0 if numerator_parent is None else _filed_measure_count(numerator_parent),
            0 if denominator_parent is None else _filed_measure_count(denominator_parent),
        )
    else:
        filed_counts = (_filed_measure_count(unit), 0)

    rows: list[UnitMeasureRecord] = []
    for role, measures, filed_count in (
        ("numerator", numerator, filed_counts[0]),
        ("denominator", denominator, filed_counts[1]),
    ):
        expanded = [_expanded_qname(measure) for measure in measures]
        resolved = [item for item in expanded if item is not None]
        if len(resolved) != filed_count:
            extraction.incoherent(
                UNRESOLVED_UNIT_MEASURE,
                f"unit {role} has {filed_count} filed measures but {len(resolved)} resolved",
                locator=unit_locator,
                context={"measure_role": role},
            )
        for ordinal, measure in enumerate(sorted(resolved, key=lambda item: item.sort_key()), 1):
            rows.append(
                UnitMeasureRecord(
                    unit_locator=unit_locator,
                    measure_role=cast(MeasureRole, role),
                    ordinal=ordinal,
                    measure=measure,
                )
            )
    return rows


def _unit_projection(model_xbrl: Any, extraction: _Extraction) -> _UnitProjection:
    units: list[UnitRecord] = []
    measures: list[UnitMeasureRecord] = []
    locators: dict[str, SourceLocator] = {}
    for unit_id, unit in (getattr(model_xbrl, "units", None) or {}).items():
        locator = extraction.locator(unit, what=f"unit {unit_id}")
        if locator is None:
            continue
        source_unit_id = _optional_str(getattr(unit, "id", None)) or _optional_str(unit_id)
        if source_unit_id is None:
            extraction.incoherent(
                INCOHERENT_UNIT_IDENTITY, "unit has no id attribute", locator=locator
            )
            continue
        divide = bool(getattr(unit, "isDivide", False))
        units.append(
            UnitRecord(source_unit_id=source_unit_id, source_locator=locator, divide=divide)
        )
        locators[source_unit_id] = locator
        measures.extend(
            _measure_rows(unit, unit_locator=locator, divide=divide, extraction=extraction)
        )
    units.sort(key=lambda item: item.source_locator.sort_key())
    measures.sort(key=lambda item: (item.unit_locator.sort_key(), item.measure_role, item.ordinal))
    return _UnitProjection(units=tuple(units), measures=tuple(measures), locators=locators)


# --------------------------------------------------------------------------- #
# Facts
# --------------------------------------------------------------------------- #


def _iter_item_facts(facts: Any, extraction: _Extraction) -> Iterator[Any]:
    """Item-fact occurrences in document order; tuples are explicit incompleteness."""
    for fact in facts or ():
        if getattr(fact, "isTuple", False):
            locator = extraction.locator(fact, what="tuple fact")
            extraction.incomplete(
                UNSUPPORTED_TUPLE_FACT,
                f"tuple fact {_clark(getattr(fact, 'qname', None))} is not modelled in Phase 1",
                locator=locator,
                context={"concept": _clark(getattr(fact, "qname", None))},
            )
            yield from _iter_item_facts(getattr(fact, "modelTupleFacts", None) or (), extraction)
            continue
        yield fact


def _continuation_locators(fact: Any, extraction: _Extraction) -> tuple[SourceLocator, ...]:
    """Inline continuation chain provenance, following Arelle's resolved links."""
    locators: list[SourceLocator] = []
    seen: set[int] = set()
    current = getattr(fact, "_continuationElement", None)
    while current is not None and len(locators) < _MAX_CONTINUATION_DEPTH:
        if id(current) in seen:
            break
        seen.add(id(current))
        locator = extraction.locator(current, what="inline continuation")
        if locator is None:
            break
        locators.append(locator)
        current = getattr(current, "_continuationElement", None)
    return tuple(locators)


@dataclass(frozen=True)
class _InlineAttributes:
    format_qname: ExpandedQName | None = None
    scale: int | None = None
    sign: str | None = None
    escape: bool | None = None
    continuation_provenance: tuple[SourceLocator, ...] = ()


def _is_inline_value(fact: Any) -> bool:
    """True for an Inline XBRL value object (transformed value, not raw XML text)."""
    from arelle.ModelInstanceObject import ModelInlineValueObject

    return isinstance(fact, ModelInlineValueObject)


def _inline_attributes(
    fact: Any, *, locator: SourceLocator, extraction: _Extraction
) -> _InlineAttributes:
    if not _is_inline_value(fact):
        return _InlineAttributes()

    raw_sign = fact.get("sign")
    sign: str | None = None
    if raw_sign == "-":
        sign = raw_sign
    elif raw_sign is not None:
        extraction.incomplete(
            UNSUPPORTED_INLINE_SIGN,
            f"inline fact declares an unsupported sign attribute {raw_sign!r}",
            locator=locator,
        )

    raw_scale = fact.get("scale")
    scale: int | None = None
    if raw_scale is not None:
        try:
            scale = int(raw_scale)
        except ValueError:
            extraction.incomplete(
                INVALID_INLINE_SCALE,
                f"inline fact declares a non-integer scale {raw_scale!r}",
                locator=locator,
            )

    format_qname: ExpandedQName | None = None
    if fact.get("format") is not None:
        try:
            format_qname = _expanded_qname(fact.format)
        except (AttributeError, ValueError, KeyError):
            format_qname = None
        if format_qname is None:
            extraction.incomplete(
                UNRESOLVED_INLINE_FORMAT,
                f"inline fact format {fact.get('format')!r} does not resolve to a QName",
                locator=locator,
            )

    return _InlineAttributes(
        format_qname=format_qname,
        scale=scale,
        sign=sign,
        escape=_optional_bool_attribute(fact.get("escape")),
        continuation_provenance=_continuation_locators(fact, extraction),
    )


def _raw_lexical_value(fact: Any, *, locator: SourceLocator, extraction: _Extraction) -> str | None:
    """Retained lexical value (``fact-lexical-v1``).

    Inline facts retain their pre-transformation inner text; XML instance facts
    retain their exact character data. The immutable source bytes plus locator
    stay authoritative in both cases.
    """
    if _is_inline_value(fact):
        try:
            raw = fact.rawValue
        except Exception as exc:  # noqa: BLE001 - engine transform failures are evidence
            extraction.incomplete(
                UNAVAILABLE_FACT_LEXICAL_VALUE,
                f"inline raw value unavailable: {type(exc).__name__}: {exc}",
                locator=locator,
            )
            return None
        return raw if isinstance(raw, str) else None
    return _text_content(fact)


def _fact_value(
    fact: Any,
    *,
    numeric: bool,
    locator: SourceLocator,
    extraction: _Extraction,
) -> tuple[ValueStatus, Decimal | None, str | None, str | None]:
    """``(value_status, resolved_numeric, resolved_text, kind)`` for a non-nil fact."""
    validity = getattr(fact, "xValid", 0)
    resolved = getattr(fact, "xValue", None)
    if validity < _ARELLE_VALID:
        return ("invalid" if validity == _ARELLE_INVALID else "unresolved"), None, None, None
    if numeric:
        exact = _exact_numeric(resolved)
        if exact is None and resolved is not None:
            extraction.incomplete(
                INEXACT_NUMERIC_VALUE,
                f"resolved numeric value is not exact ({type(resolved).__name__}); "
                "binary floating point is never persisted",
                locator=locator,
            )
            return "valid", None, None, None
        if exact is None:
            return "valid", None, None, None
        return "valid", Decimal(exact), None, "numeric"
    type_qname = getattr(getattr(fact, "concept", None), "typeQname", None)
    type_local = getattr(type_qname, "localName", None) if type_qname is not None else None
    text, kind, supported = _resolved_non_numeric(resolved, type_local_name=type_local)

    if not supported:
        extraction.incomplete(
            UNSUPPORTED_RESOLVED_VALUE,
            f"resolved value type {type(resolved).__name__} is not representable",
            locator=locator,
        )
        return "valid", None, None, None
    return "valid", None, text, kind


def _fact_record(
    fact: Any,
    *,
    context_locators: Mapping[str, SourceLocator],
    unit_locators: Mapping[str, SourceLocator],
    extraction: _Extraction,
) -> FactRecord | None:
    locator = extraction.locator(fact, what="fact")
    if locator is None:
        return None
    concept = getattr(fact, "concept", None)
    identity = _expanded_qname(getattr(concept, "qname", None)) or _expanded_qname(
        getattr(fact, "qname", None)
    )
    if concept is None or identity is None:
        extraction.incoherent(
            UNRESOLVED_FACT_CONCEPT,
            f"fact concept does not resolve to a declaration: "
            f"{_clark(getattr(fact, 'qname', None))}",
            locator=locator,
        )
        return None
    context = getattr(fact, "context", None)
    context_id = _optional_str(getattr(context, "id", None))
    context_locator = None if context_id is None else context_locators.get(context_id)
    if context_locator is None:
        extraction.incoherent(
            UNRESOLVED_FACT_CONTEXT,
            f"fact references context {getattr(fact, 'contextID', None)!r}, "
            "which has no projected row",
            locator=locator,
        )
        return None

    is_fraction = bool(getattr(fact, "isFraction", False))
    numeric = bool(getattr(fact, "isNumeric", False))
    if is_fraction:
        extraction.incomplete(
            UNSUPPORTED_FRACTION_FACT,
            f"fraction fact {identity.clark} is not modelled in Phase 1",
            locator=locator,
        )

    unit_locator: SourceLocator | None = None
    unit_unresolved = False
    if numeric or is_fraction:
        unit = getattr(fact, "unit", None)
        unit_id = _optional_str(getattr(unit, "id", None))
        if unit is None or unit_id is None:
            unit_unresolved = True
            extraction.incomplete(
                UNRESOLVED_REQUIRED_UNIT,
                f"numeric fact {identity.clark} has no resolvable unit "
                f"(unitRef={getattr(fact, 'unitID', None)!r})",
                locator=locator,
            )
        else:
            unit_locator = unit_locators.get(unit_id)
            if unit_locator is None:
                extraction.incoherent(
                    UNRESOLVED_FACT_UNIT_ROW,
                    f"fact references unit {unit_id!r}, which has no projected row",
                    locator=locator,
                )
                return None
    elif getattr(fact, "unitID", None) is not None:
        extraction.incomplete(
            UNEXPECTED_UNIT_REFERENCE,
            f"non-numeric fact {identity.clark} carries unitRef {getattr(fact, 'unitID', None)!r}",
            locator=locator,
        )

    is_nil = bool(getattr(fact, "isNil", False))
    resolved_kind: str | None = None
    if is_nil:
        status: ValueStatus = "nil"
        resolved_numeric: Decimal | None = None
        resolved_text: str | None = None
    else:
        status, resolved_numeric, resolved_text, resolved_kind = _fact_value(
            fact, numeric=numeric or is_fraction, locator=locator, extraction=extraction
        )
        if unit_unresolved:
            status = "unresolved"

    inline = _inline_attributes(fact, locator=locator, extraction=extraction)
    return FactRecord(
        concept_qname=identity,
        context_locator=context_locator,
        source_locator=locator,
        value_status=status,
        is_nil=is_nil,
        unit_locator=unit_locator,
        raw_lexical_value=_raw_lexical_value(fact, locator=locator, extraction=extraction),
        resolved_text_value=resolved_text,
        resolved_numeric_value=resolved_numeric,
        resolved_value_kind=cast(ResolvedValueKind | None, resolved_kind),
        resolved_value_type=(
            _expanded_qname(getattr(concept, "typeQname", None))
            if resolved_numeric is not None or resolved_text is not None
            else None
        ),
        reported_decimals=_optional_str(fact.get("decimals")),
        reported_precision=_optional_str(fact.get("precision")),
        xml_lang=_inherited_xml_lang(fact),
        format_qname=inline.format_qname,
        scale=inline.scale,
        sign=inline.sign,
        escape=inline.escape,
        continuation_provenance=inline.continuation_provenance,
    )


def _fact_records(
    model_xbrl: Any,
    *,
    context_locators: Mapping[str, SourceLocator],
    unit_locators: Mapping[str, SourceLocator],
    extraction: _Extraction,
) -> tuple[tuple[int, FactRecord], ...]:
    """Authoritative item occurrences: ``(source_order, FactRecord)`` in yield order.

    Every yielded item produces exactly one record with that iterator ordinal, or
    extraction fails. Records are never sorted after ordinal assignment.
    """
    undefined = list(getattr(model_xbrl, "undefinedFacts", None) or ())
    if undefined:
        extraction.incoherent(
            UNDEFINED_FACT_ELEMENT,
            f"{len(undefined)} reported element(s) have no concept declaration in the DTS",
            context={"count": len(undefined)},
        )
    records: list[tuple[int, FactRecord]] = []
    for source_order, fact in enumerate(
        _iter_item_facts(getattr(model_xbrl, "facts", None) or (), extraction)
    ):
        record = _fact_record(
            fact,
            context_locators=context_locators,
            unit_locators=unit_locators,
            extraction=extraction,
        )
        if record is None:
            extraction.incoherent(
                UNRESOLVED_FACT_CONCEPT,
                f"item fact at source_order={source_order} is unrepresentable",
            )
            continue
        records.append((source_order, record))
    return tuple(records)


# --------------------------------------------------------------------------- #
# Relationships, labels, and references
# --------------------------------------------------------------------------- #

_RelationshipFamily = Literal[
    "presentation", "calculation", "definition", "resource", "excluded", "deferred", "unsupported"
]


@dataclass(frozen=True)
class _RelationshipProjection:
    relationships: tuple[RelationshipRecord, ...]
    labels: tuple[ConceptLabelRecord, ...]
    references: tuple[ConceptReferenceRecord, ...]


def _relationship_family(
    arcrole_uri: str, *, link_tag: str | None, config: SemanticConfig
) -> _RelationshipFamily:
    if arcrole_uri in config.presentation_arcroles:
        return "presentation"
    if arcrole_uri in config.calculation_arcroles:
        return "calculation"
    if arcrole_uri in config.definition_arcroles:
        return "definition"
    if arcrole_uri in config.resource_arcroles:
        return "resource"
    if arcrole_uri in config.excluded_arcroles:
        return "excluded"
    if arcrole_uri in config.deferred_arcroles:
        return "deferred"
    # A custom arcrole used on a definition link keeps its filed arcrole URI and
    # is projected as a definition relationship when the policy allows it.
    if config.custom_definition_link_arcroles_supported and link_tag == DEFINITION_LINK_TAG:
        return "definition"
    return "unsupported"


def _exact_base_set_keys(model_xbrl: Any) -> list[tuple[Any, Any, Any, Any]]:
    """Exact base-set identities only: link QName and arc QName both present."""
    keys = [
        key
        for key in (getattr(model_xbrl, "baseSets", None) or {})
        if isinstance(key, tuple)
        and len(key) == 4
        and key[0]
        and key[2] is not None
        and key[3] is not None
    ]
    return sorted(
        keys,
        key=lambda key: (
            str(key[0]),
            str(key[1]) if key[1] else "",
            _clark(key[2]) or "",
            _clark(key[3]) or "",
        ),
    )


def _arc_locator(relationship: Any, extraction: _Extraction) -> SourceLocator | None:
    arc_element = getattr(relationship, "arcElement", None)
    if arc_element is None or not isinstance(getattr(arc_element, "tag", None), str):
        extraction.incomplete(
            UNAVAILABLE_ARC_OCCURRENCE,
            f"relationship for arcrole {getattr(relationship, 'arcrole', None)!r} "
            "has no source arc element",
        )
        return None
    return extraction.locator(arc_element, what="arc")


def _arc_order(
    relationship: Any, *, locator: SourceLocator, extraction: _Extraction
) -> Decimal | None:
    order = _finite_decimal(getattr(relationship, "orderDecimal", None))
    if order is None:
        extraction.incomplete(
            INVALID_ARC_ORDER,
            f"arc order {relationship.get('order')!r} is not an exact finite decimal",
            locator=locator,
        )
    return order


def _arc_weight(
    relationship: Any, *, locator: SourceLocator, extraction: _Extraction
) -> Decimal | None:
    raw = relationship.get("weight")
    if raw is None:
        return None
    weight = _finite_decimal(getattr(relationship, "weightDecimal", None))
    if weight is None:
        extraction.incomplete(
            INVALID_ARC_WEIGHT,
            f"arc weight {raw!r} is not an exact finite decimal",
            locator=locator,
        )
    return weight


def _arc_flag(
    relationship: Any,
    attribute: str,
    *,
    locator: SourceLocator,
    extraction: _Extraction,
) -> bool | None:
    raw = relationship.get(attribute)
    if raw is None:
        return None
    value = _optional_bool_attribute(raw)
    if value is None:
        extraction.incomplete(
            INVALID_ARC_ATTRIBUTE,
            f"arc attribute {attribute} has non-boolean value {raw!r}",
            locator=locator,
        )
    return value


def _arc_context_element(
    relationship: Any, *, locator: SourceLocator, extraction: _Extraction
) -> ContextElement | None:
    raw = relationship.get(CONTEXT_ELEMENT_ATTRIBUTE)
    if raw is None:
        return None
    if raw in ("segment", "scenario"):
        return cast(ContextElement, raw)
    extraction.incomplete(
        INVALID_ARC_ATTRIBUTE,
        f"arc contextElement has unsupported value {raw!r}",
        locator=locator,
    )
    return None


def _concept_endpoint(
    model_object: Any, declared: frozenset[ExpandedQName]
) -> ExpandedQName | None:
    identity = _expanded_qname(getattr(model_object, "qname", None))
    if identity is None or identity not in declared:
        return None
    return identity


def _concept_relationship_record(
    relationship: Any,
    *,
    network_type: NetworkType,
    arcrole_uri: str,
    link_role_uri: str,
    declared: frozenset[ExpandedQName],
    extraction: _Extraction,
) -> RelationshipRecord | None:
    # Escalate at the concept-network call site: do not share incomplete
    # UNAVAILABLE_ARC_OCCURRENCE recording with resource relationships.
    arc_element = getattr(relationship, "arcElement", None)
    if arc_element is None or not isinstance(getattr(arc_element, "tag", None), str):
        extraction.incoherent(
            UNAVAILABLE_ARC_OCCURRENCE,
            f"{network_type} relationship for arcrole {arcrole_uri!r} has no source arc element",
            context={"arcrole_uri": arcrole_uri, "link_role_uri": link_role_uri},
        )
        return None
    locator = extraction.locator(arc_element, what="arc")
    if locator is None:
        return None
    source = _concept_endpoint(getattr(relationship, "fromModelObject", None), declared)
    target = _concept_endpoint(getattr(relationship, "toModelObject", None), declared)
    if source is None or target is None:
        extraction.incoherent(
            ENDPOINT_FAMILY_MISMATCH,
            f"{network_type} relationship endpoints do not both resolve to declared concepts",
            locator=locator,
            context={"arcrole_uri": arcrole_uri, "link_role_uri": link_role_uri},
        )
        return None
    return RelationshipRecord(
        network_type=network_type,
        link_role_uri=link_role_uri,
        arcrole_uri=arcrole_uri,
        source_concept=source,
        target_concept=target,
        source_locator=locator,
        order=_arc_order(relationship, locator=locator, extraction=extraction),
        weight=_arc_weight(relationship, locator=locator, extraction=extraction),
        preferred_label_role=_optional_str(relationship.get("preferredLabel")),
        target_role_uri=_optional_str(relationship.get(TARGET_ROLE_ATTRIBUTE)),
        closed=_arc_flag(relationship, CLOSED_ATTRIBUTE, locator=locator, extraction=extraction),
        usable=_arc_flag(relationship, USABLE_ATTRIBUTE, locator=locator, extraction=extraction),
        context_element=_arc_context_element(relationship, locator=locator, extraction=extraction),
    )


def _reference_parts(
    resource: Any, *, locator: SourceLocator, extraction: _Extraction
) -> tuple[ReferencePartRecord, ...]:
    parts: list[ReferencePartRecord] = []
    for child in resource:
        tag = getattr(child, "tag", None)
        if not isinstance(tag, str):
            continue
        namespace, _, local_name = tag.partition("}")
        namespace = namespace[1:] if namespace.startswith("{") else ""
        local_name = local_name or tag
        fragment = _serialize_fragment(child)
        if fragment is None:
            extraction.incomplete(
                UNPRESERVED_REFERENCE_PART,
                f"reference part {tag} could not be serialized losslessly",
                locator=locator,
            )
            continue
        parts.append(
            ReferencePartRecord(
                namespace_uri=namespace or None,
                local_name=local_name,
                text=_text_content(child),
                xml=fragment,
            )
        )
    return tuple(parts)


def _resource_records(
    relationship: Any,
    *,
    arcrole_uri: str,
    link_role_uri: str,
    declared: frozenset[ExpandedQName],
    extraction: _Extraction,
    labels: list[ConceptLabelRecord],
    references: list[ConceptReferenceRecord],
) -> None:
    arc_locator = _arc_locator(relationship, extraction)
    if arc_locator is None:
        return
    concept = _concept_endpoint(getattr(relationship, "fromModelObject", None), declared)
    resource = getattr(relationship, "toModelObject", None)
    is_label = arcrole_uri.endswith("/concept-label")
    expected_tag = LABEL_RESOURCE_TAG if is_label else REFERENCE_RESOURCE_TAG
    if concept is None:
        extraction.incomplete(
            ENDPOINT_FAMILY_MISMATCH,
            "resource relationship source does not resolve to a declared concept",
            locator=arc_locator,
            context={"arcrole_uri": arcrole_uri, "link_role_uri": link_role_uri},
        )
        return
    if resource is None or getattr(resource, "tag", None) != expected_tag:
        extraction.incomplete(
            UNSUPPORTED_RESOURCE_CLASS,
            f"resource relationship target is not a {expected_tag} resource",
            locator=arc_locator,
            context={"arcrole_uri": arcrole_uri, "link_role_uri": link_role_uri},
        )
        return
    resource_locator = extraction.locator(resource, what="resource")
    if resource_locator is None:
        return
    order = _arc_order(relationship, locator=arc_locator, extraction=extraction)
    resource_role = _optional_str(resource.get(XLINK_ROLE_ATTRIBUTE))
    if is_label:
        labels.append(
            ConceptLabelRecord(
                concept=concept,
                link_role_uri=link_role_uri,
                arcrole_uri=arcrole_uri,
                text=_text_content(resource),
                source_locator=resource_locator,
                arc_locator=arc_locator,
                resource_role_uri=resource_role,
                xml_lang=_inherited_xml_lang(resource),
                order=order,
            )
        )
        return
    references.append(
        ConceptReferenceRecord(
            concept=concept,
            link_role_uri=link_role_uri,
            arcrole_uri=arcrole_uri,
            source_locator=resource_locator,
            arc_locator=arc_locator,
            reference_parts=_reference_parts(
                resource, locator=resource_locator, extraction=extraction
            ),
            resource_role_uri=resource_role,
            order=order,
        )
    )


def _relationship_projection(
    model_xbrl: Any,
    *,
    declared: frozenset[ExpandedQName],
    extraction: _Extraction,
) -> _RelationshipProjection:
    relationships: list[RelationshipRecord] = []
    labels: list[ConceptLabelRecord] = []
    references: list[ConceptReferenceRecord] = []

    for arcrole, linkrole, link_qname, arc_qname in _exact_base_set_keys(model_xbrl):
        arcrole_uri = str(arcrole)
        family = _relationship_family(
            arcrole_uri, link_tag=_clark(link_qname), config=extraction.config
        )
        try:
            relationship_set = model_xbrl.relationshipSet(arcrole, linkrole, link_qname, arc_qname)
        except Exception as exc:  # noqa: BLE001 - engine failure is projected evidence
            message = (
                f"relationship set for arcrole {arcrole_uri} could not be resolved: "
                f"{type(exc).__name__}: {exc}"
            )
            context = {
                "arcrole_uri": arcrole_uri,
                "link_role_uri": str(linkrole) if linkrole else None,
            }
            if family in _SUPPORTED_CONCEPT_NETWORKS:
                extraction.incoherent(RELATIONSHIP_SET_LOAD_FAILED, message, context=context)
            else:
                extraction.incomplete(RELATIONSHIP_SET_LOAD_FAILED, message, context=context)
            continue
        model_relationships = list(getattr(relationship_set, "modelRelationships", None) or ())
        if family == "excluded":
            # Counted, never projected, never failing (footnotes are a later phase).
            extraction.observe(
                EXCLUDED_ARCROLE,
                f"{len(model_relationships)} relationship(s) with arcrole {arcrole_uri} "
                "are outside the semantic projection",
                context={
                    "arcrole_uri": arcrole_uri,
                    "link_role_uri": str(linkrole) if linkrole else None,
                    "relationship_count": len(model_relationships),
                },
            )
            continue
        if family in ("deferred", "unsupported"):
            extraction.incomplete(
                DEFERRED_ARCROLE if family == "deferred" else UNSUPPORTED_ARCROLE,
                f"{len(model_relationships)} relationship(s) with arcrole {arcrole_uri} "
                "are not projected in Phase 1",
                context={
                    "arcrole_uri": arcrole_uri,
                    "link_role_uri": str(linkrole) if linkrole else None,
                    "relationship_count": len(model_relationships),
                },
            )
            continue
        for relationship in model_relationships:
            link_role_uri = _optional_str(getattr(relationship, "linkrole", None)) or (
                str(linkrole) if linkrole else None
            )
            effective_arcrole = _optional_str(getattr(relationship, "arcrole", None)) or arcrole_uri
            if link_role_uri is None:
                message = f"relationship with arcrole {effective_arcrole} has no extended link role"
                context = {"arcrole_uri": effective_arcrole}
                if family in _SUPPORTED_CONCEPT_NETWORKS:
                    extraction.incoherent(MISSING_NETWORK_ROLE, message, context=context)
                else:
                    extraction.incomplete(MISSING_NETWORK_ROLE, message, context=context)
                continue
            if family == "resource":
                _resource_records(
                    relationship,
                    arcrole_uri=effective_arcrole,
                    link_role_uri=link_role_uri,
                    declared=declared,
                    extraction=extraction,
                    labels=labels,
                    references=references,
                )
                continue
            record = _concept_relationship_record(
                relationship,
                network_type=cast(NetworkType, family),
                arcrole_uri=effective_arcrole,
                link_role_uri=link_role_uri,
                declared=declared,
                extraction=extraction,
            )
            if record is not None:
                relationships.append(record)

    # Emit-order source_order is assigned in build_report_extraction; do not sort.
    return _RelationshipProjection(
        relationships=tuple(relationships), labels=tuple(labels), references=tuple(references)
    )


# --------------------------------------------------------------------------- #
# Engine diagnostics
# --------------------------------------------------------------------------- #


def _diagnostic_severity(level_name: str) -> DiagnosticSeverity:
    """Fail-closed severity mapping: only explicitly informational levels are info."""
    level = level_name.upper()
    if level.startswith(("CRITICAL", "FATAL")):
        return "critical"
    if level.startswith("ERROR"):
        return "error"
    if level.startswith(("DEBUG", "INFO")):
        return "info"
    return "warning"


def _log_records(model_xbrl: Any) -> list[Any]:
    manager = getattr(model_xbrl, "modelManager", None)
    controller = getattr(manager, "cntlr", None) or getattr(model_xbrl, "cntlr", None)
    handler = getattr(controller, "logHandler", None)
    buffer = getattr(handler, "logRecordBuffer", None)
    return list(buffer) if isinstance(buffer, list) else []


def _diagnostic_reference(
    record: Any, resolver: _DocumentUriResolver
) -> tuple[str | None, int | None]:
    for reference in getattr(record, "refs", None) or ():
        if not isinstance(reference, Mapping):
            continue
        href = reference.get("href")
        document_uri = resolver.resolve_uri(str(href)) if isinstance(href, str) else None
        raw_line = reference.get("sourceLine")
        source_line = raw_line if isinstance(raw_line, int) and raw_line >= 0 else None
        if document_uri is not None or source_line is not None:
            return document_uri, source_line
    return None, None


def _diagnostic_records(
    model_xbrl: Any, resolver: _DocumentUriResolver
) -> tuple[DiagnosticRecord, ...]:
    """Structured engine diagnostics with explicit occurrence multiplicity."""
    counts: dict[tuple[DiagnosticSeverity, str, str | None, str | None, int | None], int] = {}
    for record in _log_records(model_xbrl):
        severity = _diagnostic_severity(str(getattr(record, "levelname", "INFO")))
        code = _optional_str(getattr(record, "messageCode", None)) or UNSTRUCTURED_CODE
        try:
            message = record.getMessage()
        except Exception as exc:  # noqa: BLE001 - a log failure must not fail extraction
            message = f"<unrenderable log record: {type(exc).__name__}: {exc}>"
        document_uri, source_line = _diagnostic_reference(record, resolver)
        key = (severity, code, _optional_str(message), document_uri, source_line)
        counts[key] = counts.get(key, 0) + 1
    records = [
        DiagnosticRecord(
            severity=severity,
            code=code,
            message=message,
            document_uri=document_uri,
            source_line=source_line,
            occurrence_count=count,
        )
        for (severity, code, message, document_uri, source_line), count in counts.items()
    ]
    records.sort(
        key=lambda item: (
            item.severity,
            item.code,
            item.document_uri or "",
            item.source_line if item.source_line is not None else -1,
            item.message or "",
        )
    )
    return tuple(records)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def _issue_sort_key(issue: SemanticIssueRecord) -> tuple[str, str, str, str]:
    locator = issue.locator
    return (
        issue.code,
        "" if locator is None else "#".join(locator.sort_key()),
        issue.severity,
        issue.message,
    )


def extract_report_extraction(
    model_xbrl: Any,
    *,
    bound_inputs: Any,
    primary_uris: frozenset[str] | set[str],
    uri_bindings: Sequence[UriBinding],
    report_input: XbrlReportInput | Mapping[str, Any],
    config: SemanticConfig | None = None,
    engine_version: str | None = None,
    extractor_version: str = EXTRACTOR_VERSION,
) -> ReportExtraction:
    """Extract one loaded Arelle report into native ``ReportExtraction``.

    URI → FilingBundle logical_path provenance is resolved inside this function.
    Every authoritative item-fact occurrence either becomes one ``FactRecord``
    with that iterator ordinal, or extraction fails.

    Raises :class:`SemanticExtractionError` on incoherence, unrepresentable
    facts, completeness-blocking diagnostics, or any fatal issue (fail-closed).
    """
    active_config = config if config is not None else build_semantic_config()
    extraction = _Extraction(
        config=active_config,
        resolver=_DocumentUriResolver(bound_inputs, frozenset(primary_uris)),
    )

    concept_declarations = _concept_declarations(model_xbrl, extraction)
    declared = frozenset(declaration.concept for declaration in concept_declarations)
    contexts = _context_projection(model_xbrl, extraction)
    units = _unit_projection(model_xbrl, extraction)
    ordered_facts = _fact_records(
        model_xbrl,
        context_locators=contexts.locators,
        unit_locators=units.locators,
        extraction=extraction,
    )
    networks = _relationship_projection(model_xbrl, declared=declared, extraction=extraction)
    diagnostics = _diagnostic_records(model_xbrl, extraction.resolver)
    for diagnostic in diagnostics:
        if classify_diagnostic(diagnostic) == "completeness_blocking":
            extraction.incomplete(
                BLOCKING_ENGINE_DIAGNOSTIC,
                f"engine diagnostic {diagnostic.code} is not classified as "
                "compatible with a complete source extraction",
                context={
                    "code": diagnostic.code,
                    "severity": diagnostic.severity,
                    "occurrence_count": diagnostic.occurrence_count,
                },
            )

    issues = tuple(sorted(extraction.issues, key=_issue_sort_key))
    if extraction.errors or any(issue.severity == "fatal" for issue in issues):
        raise SemanticExtractionError(
            "source extraction failed: "
            + "; ".join(
                f"{issue.code}: {issue.message}" for issue in issues if issue.severity == "fatal"
            ),
            issues=issues,
        )

    try:
        report = build_report_extraction(
            report_input=report_input,
            uri_bindings=uri_bindings,
            arelle_version=(engine_version if engine_version is not None else arelle_version()),
            extractor_version=extractor_version,
            concept_declarations=concept_declarations,
            concept_labels=networks.labels,
            concept_references=networks.references,
            contexts=contexts.contexts,
            context_dimensions=contexts.dimensions,
            units=units.units,
            unit_measures=units.measures,
            ordered_facts=ordered_facts,
            relationships=networks.relationships,
            issues=issues,
        )
    except SourceBuildError as exc:
        invalid = SemanticIssueRecord(
            severity="fatal",
            code=RECORD_SET_INVALID,
            message=str(exc),
        )
        raise SemanticExtractionError(
            f"source extraction record set is invalid: {exc}",
            issues=(*issues, invalid),
        ) from exc

    if report.arelle_item_fact_count != len(report.facts):
        raise SemanticExtractionError(
            "arelle_item_fact_count must equal len(facts): "
            f"{report.arelle_item_fact_count} != {len(report.facts)}",
            issues=issues,
        )
    if any(issue.severity == "fatal" for issue in report.issues):
        raise SemanticExtractionError(
            "source extraction must not return fatal issues",
            issues=tuple(
                SemanticIssueRecord(
                    severity=i.severity,
                    code=i.code,
                    message=i.message,
                    context=dict(i.details),
                )
                for i in report.issues
            ),
        )
    return report


# Back-compat alias removed: live path uses extract_report_extraction only.
