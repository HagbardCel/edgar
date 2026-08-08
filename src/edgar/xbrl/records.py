"""Immutable XBRL semantic-projection records (ADR 0008, ADR 0004).

These records are the adapter boundary. An Arelle projection emits them and
persistence consumes them; every record is JSON-serializable so a projection can
cross the isolated worker process boundary (:mod:`edgar.xbrl.worker`) without an
Arelle object ever escaping the adapter.

Reference rules:

- concept-valued references are :class:`ExpandedQName` (namespace URI + local
  name). Source prefixes are serialization and never define semantic identity.
- context and unit references are :class:`SourceLocator` (canonical document URI
  + deterministic element locator, ``element-locator-v1``).
- no Arelle in-memory object identifier and no database identifier appears in
  any record.

Exact QName identity is *not* economic equivalence: joining on
:class:`ExpandedQName` is a syntactic join only (ADR 0008 §4).

Filed numerics use :class:`decimal.Decimal` and serialize as exact strings;
binary floating point is rejected everywhere in this module.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast, get_args

from edgar.domain.decode import (
    BundleDecodeError,
    require_bool,
    require_exact_keys,
    require_int,
    require_list,
    require_object,
    require_str,
)
from edgar.domain.uri import assert_serialized_binding_uri

# Serialization contract for the worker/persistence boundary. This is a wire
# format version only: it deliberately does not participate in semantic
# projection identity (see edgar.xbrl.config).
RECORDS_SCHEMA_VERSION = 1

LocatorScheme = Literal["xml_id", "unqualified_id", "expanded_element_path"]
PeriodKind = Literal["instant", "duration", "forever"]
PeriodType = Literal["instant", "duration"]
Balance = Literal["debit", "credit"]
ContextElement = Literal["segment", "scenario"]
MemberKind = Literal["explicit", "typed"]
MeasureRole = Literal["numerator", "denominator"]
ValueStatus = Literal["valid", "nil", "invalid", "unresolved"]
NetworkType = Literal["presentation", "calculation", "definition"]
CyclesAllowed = Literal["any", "undirected", "none"]
DiagnosticSeverity = Literal["info", "warning", "error", "critical"]
IssueSeverity = Literal["fatal", "warning", "info"]
IssueScope = Literal["operational", "semantic_projection", "document_projection"]

LOCATOR_SCHEMES: frozenset[str] = frozenset(get_args(LocatorScheme))
PERIOD_KINDS: frozenset[str] = frozenset(get_args(PeriodKind))
PERIOD_TYPES: frozenset[str] = frozenset(get_args(PeriodType))
BALANCES: frozenset[str] = frozenset(get_args(Balance))
CONTEXT_ELEMENTS: frozenset[str] = frozenset(get_args(ContextElement))
MEMBER_KINDS: frozenset[str] = frozenset(get_args(MemberKind))
MEASURE_ROLES: frozenset[str] = frozenset(get_args(MeasureRole))
VALUE_STATUSES: frozenset[str] = frozenset(get_args(ValueStatus))
NETWORK_TYPES: frozenset[str] = frozenset(get_args(NetworkType))
CYCLES_ALLOWED: frozenset[str] = frozenset(get_args(CyclesAllowed))
DIAGNOSTIC_SEVERITIES: frozenset[str] = frozenset(get_args(DiagnosticSeverity))
ISSUE_SEVERITIES: frozenset[str] = frozenset(get_args(IssueSeverity))
ISSUE_SCOPES: frozenset[str] = frozenset(get_args(IssueScope))

# Inline XBRL permits exactly one sign attribute value.
INLINE_SIGN_VALUES: frozenset[str] = frozenset({"-"})


class RecordDecodeError(BundleDecodeError):
    """Raised when a persisted or transported semantic record fails decoding."""


def _require_literal(value: object, allowed: frozenset[str], *, label: str) -> str:
    text = require_str(value, label=label)
    if text not in allowed:
        raise RecordDecodeError(f"{label} must be one of {sorted(allowed)}, got {text!r}")
    return text


def _require_nullable_literal(value: object, allowed: frozenset[str], *, label: str) -> str | None:
    if value is None:
        return None
    return _require_literal(value, allowed, label=label)


def _require_nullable_str(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return require_str(value, label=label)


def _require_nullable_bool(value: object, *, label: str) -> bool | None:
    if value is None:
        return None
    return require_bool(value, label=label)


def _require_nullable_int(value: object, *, label: str) -> int | None:
    if value is None:
        return None
    return require_int(value, label=label)


def _decimal_to_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _require_nullable_decimal(value: object, *, label: str) -> Decimal | None:
    """Decode an exact decimal from its string form; binary floats are rejected."""
    if value is None:
        return None
    text = require_str(value, label=label)
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise RecordDecodeError(f"{label} is not an exact decimal: {text!r}") from exc
    if not parsed.is_finite():
        raise RecordDecodeError(f"{label} must be a finite decimal: {text!r}")
    return parsed


def _assert_finite_decimal(value: Decimal | None, *, label: str) -> None:
    if value is not None and not value.is_finite():
        raise ValueError(f"{label} must be a finite decimal: {value!r}")


def _decode_records[R](
    value: object,
    decoder: Callable[[dict[str, Any]], R],
    *,
    label: str,
) -> tuple[R, ...]:
    items = require_list(value, label=label)
    return tuple(
        decoder(require_object(item, label=f"{label}[{index}]")) for index, item in enumerate(items)
    )


def _require_json_value(value: object, *, label: str) -> Any:
    """Allow only JSON scalars, lists, and objects; floats are rejected.

    Binary floating point never enters filing evidence, including issue context.
    """
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is list:
        return [_require_json_value(item, label=f"{label}[{i}]") for i, item in enumerate(value)]
    if type(value) is dict:
        out: dict[str, Any] = {}
        for key, item in cast(dict[Any, Any], value).items():
            if type(key) is not str:
                raise RecordDecodeError(f"{label} keys must be strings, got {type(key).__name__}")
            out[key] = _require_json_value(item, label=f"{label}.{key}")
        return out
    raise RecordDecodeError(f"{label} has unsupported JSON type {type(value).__name__}")


_QNAME_KEYS = frozenset({"namespace_uri", "local_name"})
_LOCATOR_KEYS = frozenset({"document_uri", "scheme", "value"})


@dataclass(frozen=True)
class ExpandedQName:
    """Prefix-independent QName identity (namespace URI + local name)."""

    namespace_uri: str | None
    local_name: str

    def __post_init__(self) -> None:
        if not self.local_name:
            raise ValueError("local_name must be non-empty")
        if any(ch in self.local_name for ch in ":{}/ \t\r\n"):
            raise ValueError(f"local_name is not an NCName: {self.local_name!r}")
        if self.namespace_uri is not None and not self.namespace_uri:
            raise ValueError("namespace_uri must be None or non-empty")

    @property
    def clark(self) -> str:
        """Clark notation ``{namespace}local`` (``local`` when unqualified)."""
        if self.namespace_uri is None:
            return self.local_name
        return f"{{{self.namespace_uri}}}{self.local_name}"

    @classmethod
    def from_clark(cls, text: str) -> ExpandedQName:
        if text.startswith("{"):
            namespace, closing, local = text[1:].partition("}")
            if not closing:
                raise ValueError(f"malformed Clark notation: {text!r}")
            return cls(namespace_uri=namespace, local_name=local)
        return cls(namespace_uri=None, local_name=text)

    def sort_key(self) -> tuple[str, str]:
        return (self.namespace_uri or "", self.local_name)

    def to_dict(self) -> dict[str, Any]:
        return {"namespace_uri": self.namespace_uri, "local_name": self.local_name}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExpandedQName:
        obj = require_object(data, label="qname")
        require_exact_keys(obj, _QNAME_KEYS, label="qname")
        return cls(
            namespace_uri=_require_nullable_str(obj["namespace_uri"], label="qname.namespace_uri"),
            local_name=require_str(obj["local_name"], label="qname.local_name"),
        )


def _qname_to_dict(value: ExpandedQName | None) -> dict[str, Any] | None:
    return None if value is None else value.to_dict()


def _require_qname(value: object, *, label: str) -> ExpandedQName:
    obj = require_object(value, label=label)
    require_exact_keys(obj, _QNAME_KEYS, label=label)
    return ExpandedQName(
        namespace_uri=_require_nullable_str(obj["namespace_uri"], label=f"{label}.namespace_uri"),
        local_name=require_str(obj["local_name"], label=f"{label}.local_name"),
    )


def _require_nullable_qname(value: object, *, label: str) -> ExpandedQName | None:
    if value is None:
        return None
    return _require_qname(value, label=label)


def _require_qnames(value: object, *, label: str) -> tuple[ExpandedQName, ...]:
    items = require_list(value, label=label)
    return tuple(_require_qname(item, label=f"{label}[{i}]") for i, item in enumerate(items))


@dataclass(frozen=True)
class SourceLocator:
    """Deterministic reference to one element in one immutable source document.

    ``document_uri`` is the canonical replay URI of the bundle URI binding that
    owns the bytes; it is never an Arelle in-memory object identifier and never a
    filesystem path. ``scheme``/``value`` follow ``element-locator-v1``
    (:mod:`edgar.xbrl.locators`).
    """

    document_uri: str
    scheme: LocatorScheme
    value: str

    def __post_init__(self) -> None:
        assert_serialized_binding_uri(self.document_uri)
        if self.scheme not in LOCATOR_SCHEMES:
            raise ValueError(f"unknown locator scheme: {self.scheme!r}")
        if not self.value:
            raise ValueError("locator value must be non-empty")

    def sort_key(self) -> tuple[str, str, str]:
        return (self.document_uri, self.scheme, self.value)

    def to_dict(self) -> dict[str, Any]:
        return {"document_uri": self.document_uri, "scheme": self.scheme, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceLocator:
        return _require_locator(data, label="source_locator")


def _require_locator(value: object, *, label: str) -> SourceLocator:
    obj = require_object(value, label=label)
    require_exact_keys(obj, _LOCATOR_KEYS, label=label)
    scheme = _require_literal(obj["scheme"], LOCATOR_SCHEMES, label=f"{label}.scheme")
    return SourceLocator(
        document_uri=require_str(obj["document_uri"], label=f"{label}.document_uri"),
        scheme=cast(LocatorScheme, scheme),
        value=require_str(obj["value"], label=f"{label}.value"),
    )


def _require_nullable_locator(value: object, *, label: str) -> SourceLocator | None:
    if value is None:
        return None
    return _require_locator(value, label=label)


def _require_locators(value: object, *, label: str) -> tuple[SourceLocator, ...]:
    items = require_list(value, label=label)
    return tuple(_require_locator(item, label=f"{label}[{i}]") for i, item in enumerate(items))


def _locator_to_dict(value: SourceLocator | None) -> dict[str, Any] | None:
    return None if value is None else value.to_dict()


_DIAGNOSTIC_KEYS = frozenset(
    {"severity", "code", "message", "document_uri", "source_line", "occurrence_count"}
)


@dataclass(frozen=True)
class DiagnosticRecord:
    """One engine diagnostic occurrence class with explicit multiplicity.

    ``code`` is the engine message code. A diagnostic without a structured code
    is recorded with :data:`edgar.xbrl.diagnostics.UNSTRUCTURED_CODE` so it can
    never be silently treated as recognized.
    """

    severity: DiagnosticSeverity
    code: str
    message: str | None = None
    document_uri: str | None = None
    source_line: int | None = None
    occurrence_count: int = 1

    def __post_init__(self) -> None:
        if self.severity not in DIAGNOSTIC_SEVERITIES:
            raise ValueError(f"unknown diagnostic severity: {self.severity!r}")
        if not self.code:
            raise ValueError("diagnostic code must be non-empty")
        if self.occurrence_count < 1:
            raise ValueError("occurrence_count must be at least 1")
        if self.source_line is not None and self.source_line < 0:
            raise ValueError("source_line must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "document_uri": self.document_uri,
            "source_line": self.source_line,
            "occurrence_count": self.occurrence_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiagnosticRecord:
        obj = require_object(data, label="diagnostic")
        require_exact_keys(obj, _DIAGNOSTIC_KEYS, label="diagnostic")
        severity = _require_literal(
            obj["severity"], DIAGNOSTIC_SEVERITIES, label="diagnostic.severity"
        )
        return cls(
            severity=cast(DiagnosticSeverity, severity),
            code=require_str(obj["code"], label="diagnostic.code"),
            message=_require_nullable_str(obj["message"], label="diagnostic.message"),
            document_uri=_require_nullable_str(
                obj["document_uri"], label="diagnostic.document_uri"
            ),
            source_line=_require_nullable_int(obj["source_line"], label="diagnostic.source_line"),
            occurrence_count=require_int(
                obj["occurrence_count"], label="diagnostic.occurrence_count"
            ),
        )


_CONCEPT_DECLARATION_KEYS = frozenset(
    {
        "concept",
        "data_type",
        "substitution_group",
        "period_type",
        "balance",
        "abstract",
        "nillable",
        "source_locator",
    }
)


@dataclass(frozen=True)
class ConceptDeclarationRecord:
    """Projection-scoped effective declaration of one concept identity.

    QName identity (``concept``) is stable across projections; the declaration
    and its provenance are specific to this DTS.
    """

    concept: ExpandedQName
    source_locator: SourceLocator
    data_type: ExpandedQName | None = None
    substitution_group: ExpandedQName | None = None
    period_type: PeriodType | None = None
    balance: Balance | None = None
    abstract: bool | None = None
    nillable: bool | None = None

    def __post_init__(self) -> None:
        if self.period_type is not None and self.period_type not in PERIOD_TYPES:
            raise ValueError(f"unknown period_type: {self.period_type!r}")
        if self.balance is not None and self.balance not in BALANCES:
            raise ValueError(f"unknown balance: {self.balance!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept.to_dict(),
            "data_type": _qname_to_dict(self.data_type),
            "substitution_group": _qname_to_dict(self.substitution_group),
            "period_type": self.period_type,
            "balance": self.balance,
            "abstract": self.abstract,
            "nillable": self.nillable,
            "source_locator": self.source_locator.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConceptDeclarationRecord:
        label = "concept_declaration"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _CONCEPT_DECLARATION_KEYS, label=label)
        period_type = _require_nullable_literal(
            obj["period_type"], PERIOD_TYPES, label=f"{label}.period_type"
        )
        balance = _require_nullable_literal(obj["balance"], BALANCES, label=f"{label}.balance")
        return cls(
            concept=_require_qname(obj["concept"], label=f"{label}.concept"),
            source_locator=_require_locator(obj["source_locator"], label=f"{label}.source_locator"),
            data_type=_require_nullable_qname(obj["data_type"], label=f"{label}.data_type"),
            substitution_group=_require_nullable_qname(
                obj["substitution_group"], label=f"{label}.substitution_group"
            ),
            period_type=cast(PeriodType | None, period_type),
            balance=cast(Balance | None, balance),
            abstract=_require_nullable_bool(obj["abstract"], label=f"{label}.abstract"),
            nillable=_require_nullable_bool(obj["nillable"], label=f"{label}.nillable"),
        )


_CONCEPT_LABEL_KEYS = frozenset(
    {
        "concept",
        "link_role_uri",
        "arcrole_uri",
        "resource_role_uri",
        "xml_lang",
        "text",
        "order",
        "source_locator",
        "arc_locator",
    }
)


@dataclass(frozen=True)
class ConceptLabelRecord:
    """One supported concept-label resource occurrence.

    ``link_role_uri`` (ELR), ``arcrole_uri``, and ``resource_role_uri`` are three
    distinct role concepts and are never collapsed.
    """

    concept: ExpandedQName
    link_role_uri: str
    arcrole_uri: str
    text: str
    source_locator: SourceLocator
    arc_locator: SourceLocator
    resource_role_uri: str | None = None
    xml_lang: str | None = None
    order: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.link_role_uri:
            raise ValueError("link_role_uri is required")
        if not self.arcrole_uri:
            raise ValueError("arcrole_uri is required")
        _assert_finite_decimal(self.order, label="order")

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept.to_dict(),
            "link_role_uri": self.link_role_uri,
            "arcrole_uri": self.arcrole_uri,
            "resource_role_uri": self.resource_role_uri,
            "xml_lang": self.xml_lang,
            "text": self.text,
            "order": _decimal_to_str(self.order),
            "source_locator": self.source_locator.to_dict(),
            "arc_locator": self.arc_locator.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConceptLabelRecord:
        label = "concept_label"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _CONCEPT_LABEL_KEYS, label=label)
        return cls(
            concept=_require_qname(obj["concept"], label=f"{label}.concept"),
            link_role_uri=require_str(obj["link_role_uri"], label=f"{label}.link_role_uri"),
            arcrole_uri=require_str(obj["arcrole_uri"], label=f"{label}.arcrole_uri"),
            text=require_str(obj["text"], label=f"{label}.text"),
            source_locator=_require_locator(obj["source_locator"], label=f"{label}.source_locator"),
            arc_locator=_require_locator(obj["arc_locator"], label=f"{label}.arc_locator"),
            resource_role_uri=_require_nullable_str(
                obj["resource_role_uri"], label=f"{label}.resource_role_uri"
            ),
            xml_lang=_require_nullable_str(obj["xml_lang"], label=f"{label}.xml_lang"),
            order=_require_nullable_decimal(obj["order"], label=f"{label}.order"),
        )


_REFERENCE_PART_KEYS = frozenset({"namespace_uri", "local_name", "text", "xml"})


@dataclass(frozen=True)
class ReferencePartRecord:
    """One ordered structured part of a concept-reference resource.

    ``xml`` is a namespace-complete, self-contained serialization of the part
    subtree; it must not depend on namespace declarations that only existed on
    ancestors in the source document.
    """

    namespace_uri: str | None
    local_name: str
    text: str
    xml: str

    def __post_init__(self) -> None:
        if not self.local_name:
            raise ValueError("reference part local_name must be non-empty")
        if self.namespace_uri is not None and not self.namespace_uri:
            raise ValueError("reference part namespace_uri must be None or non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace_uri": self.namespace_uri,
            "local_name": self.local_name,
            "text": self.text,
            "xml": self.xml,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReferencePartRecord:
        label = "reference_part"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _REFERENCE_PART_KEYS, label=label)
        return cls(
            namespace_uri=_require_nullable_str(
                obj["namespace_uri"], label=f"{label}.namespace_uri"
            ),
            local_name=require_str(obj["local_name"], label=f"{label}.local_name"),
            text=require_str(obj["text"], label=f"{label}.text"),
            xml=require_str(obj["xml"], label=f"{label}.xml"),
        )


_CONCEPT_REFERENCE_KEYS = frozenset(
    {
        "concept",
        "link_role_uri",
        "arcrole_uri",
        "resource_role_uri",
        "order",
        "reference_parts",
        "source_locator",
        "arc_locator",
    }
)


@dataclass(frozen=True)
class ConceptReferenceRecord:
    """One supported concept-reference resource occurrence with ordered parts."""

    concept: ExpandedQName
    link_role_uri: str
    arcrole_uri: str
    source_locator: SourceLocator
    arc_locator: SourceLocator
    reference_parts: tuple[ReferencePartRecord, ...] = ()
    resource_role_uri: str | None = None
    order: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.link_role_uri:
            raise ValueError("link_role_uri is required")
        if not self.arcrole_uri:
            raise ValueError("arcrole_uri is required")
        _assert_finite_decimal(self.order, label="order")

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept.to_dict(),
            "link_role_uri": self.link_role_uri,
            "arcrole_uri": self.arcrole_uri,
            "resource_role_uri": self.resource_role_uri,
            "order": _decimal_to_str(self.order),
            "reference_parts": [part.to_dict() for part in self.reference_parts],
            "source_locator": self.source_locator.to_dict(),
            "arc_locator": self.arc_locator.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConceptReferenceRecord:
        label = "concept_reference"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _CONCEPT_REFERENCE_KEYS, label=label)
        return cls(
            concept=_require_qname(obj["concept"], label=f"{label}.concept"),
            link_role_uri=require_str(obj["link_role_uri"], label=f"{label}.link_role_uri"),
            arcrole_uri=require_str(obj["arcrole_uri"], label=f"{label}.arcrole_uri"),
            source_locator=_require_locator(obj["source_locator"], label=f"{label}.source_locator"),
            arc_locator=_require_locator(obj["arc_locator"], label=f"{label}.arc_locator"),
            reference_parts=_decode_records(
                obj["reference_parts"],
                ReferencePartRecord.from_dict,
                label=f"{label}.reference_parts",
            ),
            resource_role_uri=_require_nullable_str(
                obj["resource_role_uri"], label=f"{label}.resource_role_uri"
            ),
            order=_require_nullable_decimal(obj["order"], label=f"{label}.order"),
        )


_ROLE_DECLARATION_KEYS = frozenset({"role_uri", "definition", "used_on", "source_locator"})


@dataclass(frozen=True)
class RoleDeclarationRecord:
    """One ``roleType`` declaration occurrence.

    The URI alone is not declaration identity: a DTS may declare the same role
    URI in more than one document, so the source locator is part of the record.
    """

    role_uri: str
    source_locator: SourceLocator
    definition: str | None = None
    used_on: tuple[ExpandedQName, ...] = ()

    def __post_init__(self) -> None:
        if not self.role_uri:
            raise ValueError("role_uri is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_uri": self.role_uri,
            "definition": self.definition,
            "used_on": [q.to_dict() for q in self.used_on],
            "source_locator": self.source_locator.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoleDeclarationRecord:
        label = "role_declaration"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _ROLE_DECLARATION_KEYS, label=label)
        return cls(
            role_uri=require_str(obj["role_uri"], label=f"{label}.role_uri"),
            source_locator=_require_locator(obj["source_locator"], label=f"{label}.source_locator"),
            definition=_require_nullable_str(obj["definition"], label=f"{label}.definition"),
            used_on=_require_qnames(obj["used_on"], label=f"{label}.used_on"),
        )


_ARCROLE_DECLARATION_KEYS = frozenset(
    {"arcrole_uri", "definition", "used_on", "cycles_allowed", "source_locator"}
)


@dataclass(frozen=True)
class ArcroleDeclarationRecord:
    """One ``arcroleType`` declaration occurrence (``cycles_allowed`` applies here only)."""

    arcrole_uri: str
    source_locator: SourceLocator
    definition: str | None = None
    used_on: tuple[ExpandedQName, ...] = ()
    cycles_allowed: CyclesAllowed | None = None

    def __post_init__(self) -> None:
        if not self.arcrole_uri:
            raise ValueError("arcrole_uri is required")
        if self.cycles_allowed is not None and self.cycles_allowed not in CYCLES_ALLOWED:
            raise ValueError(f"unknown cycles_allowed: {self.cycles_allowed!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "arcrole_uri": self.arcrole_uri,
            "definition": self.definition,
            "used_on": [q.to_dict() for q in self.used_on],
            "cycles_allowed": self.cycles_allowed,
            "source_locator": self.source_locator.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArcroleDeclarationRecord:
        label = "arcrole_declaration"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _ARCROLE_DECLARATION_KEYS, label=label)
        cycles = _require_nullable_literal(
            obj["cycles_allowed"], CYCLES_ALLOWED, label=f"{label}.cycles_allowed"
        )
        return cls(
            arcrole_uri=require_str(obj["arcrole_uri"], label=f"{label}.arcrole_uri"),
            source_locator=_require_locator(obj["source_locator"], label=f"{label}.source_locator"),
            definition=_require_nullable_str(obj["definition"], label=f"{label}.definition"),
            used_on=_require_qnames(obj["used_on"], label=f"{label}.used_on"),
            cycles_allowed=cast(CyclesAllowed | None, cycles),
        )


_CONTEXT_KEYS = frozenset(
    {
        "source_context_id",
        "entity_scheme",
        "entity_identifier",
        "period_kind",
        "period_instant",
        "period_start",
        "period_end",
        "non_dimensional_segment_xml",
        "non_dimensional_scenario_xml",
        "source_locator",
    }
)


@dataclass(frozen=True)
class ContextRecord:
    """One ``xbrli:context`` occurrence.

    Period fields keep the filed lexical representation: XBRL periods may carry
    date or dateTime forms and engine normalization is not substituted for the
    filed value. Non-dimensional segment/scenario content is preserved as
    namespace-complete XML rather than dropped; when the projection cannot
    preserve it, the adapter must raise a semantic issue instead.
    """

    source_context_id: str
    entity_scheme: str
    entity_identifier: str
    period_kind: PeriodKind
    source_locator: SourceLocator
    period_instant: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    non_dimensional_segment_xml: str | None = None
    non_dimensional_scenario_xml: str | None = None

    def __post_init__(self) -> None:
        if not self.source_context_id:
            raise ValueError("source_context_id is required")
        if self.period_kind not in PERIOD_KINDS:
            raise ValueError(f"unknown period_kind: {self.period_kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_context_id": self.source_context_id,
            "entity_scheme": self.entity_scheme,
            "entity_identifier": self.entity_identifier,
            "period_kind": self.period_kind,
            "period_instant": self.period_instant,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "non_dimensional_segment_xml": self.non_dimensional_segment_xml,
            "non_dimensional_scenario_xml": self.non_dimensional_scenario_xml,
            "source_locator": self.source_locator.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextRecord:
        label = "context"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _CONTEXT_KEYS, label=label)
        period_kind = _require_literal(
            obj["period_kind"], PERIOD_KINDS, label=f"{label}.period_kind"
        )
        return cls(
            source_context_id=require_str(
                obj["source_context_id"], label=f"{label}.source_context_id"
            ),
            entity_scheme=require_str(obj["entity_scheme"], label=f"{label}.entity_scheme"),
            entity_identifier=require_str(
                obj["entity_identifier"], label=f"{label}.entity_identifier"
            ),
            period_kind=cast(PeriodKind, period_kind),
            source_locator=_require_locator(obj["source_locator"], label=f"{label}.source_locator"),
            period_instant=_require_nullable_str(
                obj["period_instant"], label=f"{label}.period_instant"
            ),
            period_start=_require_nullable_str(obj["period_start"], label=f"{label}.period_start"),
            period_end=_require_nullable_str(obj["period_end"], label=f"{label}.period_end"),
            non_dimensional_segment_xml=_require_nullable_str(
                obj["non_dimensional_segment_xml"], label=f"{label}.non_dimensional_segment_xml"
            ),
            non_dimensional_scenario_xml=_require_nullable_str(
                obj["non_dimensional_scenario_xml"], label=f"{label}.non_dimensional_scenario_xml"
            ),
        )


_CONTEXT_DIMENSION_KEYS = frozenset(
    {
        "context_locator",
        "dimension",
        "context_element",
        "member_kind",
        "member",
        "typed_member_xml",
        "typed_member_sha256",
        "source_locator",
    }
)


@dataclass(frozen=True)
class ContextDimensionRecord:
    """One *filed* explicit or typed dimension occurrence within a context.

    Dimension defaults are never materialized here: default semantics live in the
    effective definition network. ``typed_member_sha256`` is an integrity and
    indexing aid, never an identity key.
    """

    context_locator: SourceLocator
    dimension: ExpandedQName
    context_element: ContextElement
    member_kind: MemberKind
    source_locator: SourceLocator
    member: ExpandedQName | None = None
    typed_member_xml: str | None = None
    typed_member_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.context_element not in CONTEXT_ELEMENTS:
            raise ValueError(f"unknown context_element: {self.context_element!r}")
        if self.member_kind not in MEMBER_KINDS:
            raise ValueError(f"unknown member_kind: {self.member_kind!r}")
        if self.member_kind == "explicit":
            if self.member is None:
                raise ValueError("explicit dimension requires a member QName")
            if self.typed_member_xml is not None:
                raise ValueError("explicit dimension must not carry typed member XML")
        else:
            if self.typed_member_xml is None:
                raise ValueError("typed dimension requires typed_member_xml")
            if self.member is not None:
                raise ValueError("typed dimension must not carry an explicit member QName")

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_locator": self.context_locator.to_dict(),
            "dimension": self.dimension.to_dict(),
            "context_element": self.context_element,
            "member_kind": self.member_kind,
            "member": _qname_to_dict(self.member),
            "typed_member_xml": self.typed_member_xml,
            "typed_member_sha256": self.typed_member_sha256,
            "source_locator": self.source_locator.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextDimensionRecord:
        label = "context_dimension"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _CONTEXT_DIMENSION_KEYS, label=label)
        context_element = _require_literal(
            obj["context_element"], CONTEXT_ELEMENTS, label=f"{label}.context_element"
        )
        member_kind = _require_literal(
            obj["member_kind"], MEMBER_KINDS, label=f"{label}.member_kind"
        )
        return cls(
            context_locator=_require_locator(
                obj["context_locator"], label=f"{label}.context_locator"
            ),
            dimension=_require_qname(obj["dimension"], label=f"{label}.dimension"),
            context_element=cast(ContextElement, context_element),
            member_kind=cast(MemberKind, member_kind),
            source_locator=_require_locator(obj["source_locator"], label=f"{label}.source_locator"),
            member=_require_nullable_qname(obj["member"], label=f"{label}.member"),
            typed_member_xml=_require_nullable_str(
                obj["typed_member_xml"], label=f"{label}.typed_member_xml"
            ),
            typed_member_sha256=_require_nullable_str(
                obj["typed_member_sha256"], label=f"{label}.typed_member_sha256"
            ),
        )


_UNIT_KEYS = frozenset({"source_unit_id", "divide", "source_locator"})


@dataclass(frozen=True)
class UnitRecord:
    """One ``xbrli:unit`` occurrence; measures are child :class:`UnitMeasureRecord` rows."""

    source_unit_id: str
    source_locator: SourceLocator
    divide: bool = False

    def __post_init__(self) -> None:
        if not self.source_unit_id:
            raise ValueError("source_unit_id is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_unit_id": self.source_unit_id,
            "divide": self.divide,
            "source_locator": self.source_locator.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UnitRecord:
        label = "unit"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _UNIT_KEYS, label=label)
        return cls(
            source_unit_id=require_str(obj["source_unit_id"], label=f"{label}.source_unit_id"),
            source_locator=_require_locator(obj["source_locator"], label=f"{label}.source_locator"),
            divide=require_bool(obj["divide"], label=f"{label}.divide"),
        )


_UNIT_MEASURE_KEYS = frozenset({"unit_locator", "measure_role", "ordinal", "measure"})


@dataclass(frozen=True)
class UnitMeasureRecord:
    """One measure of a unit, as an expanded QName (never a lexical prefix form)."""

    unit_locator: SourceLocator
    measure_role: MeasureRole
    ordinal: int
    measure: ExpandedQName

    def __post_init__(self) -> None:
        if self.measure_role not in MEASURE_ROLES:
            raise ValueError(f"unknown measure_role: {self.measure_role!r}")
        if self.ordinal < 1:
            raise ValueError("measure ordinal is 1-based")

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_locator": self.unit_locator.to_dict(),
            "measure_role": self.measure_role,
            "ordinal": self.ordinal,
            "measure": self.measure.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UnitMeasureRecord:
        label = "unit_measure"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _UNIT_MEASURE_KEYS, label=label)
        measure_role = _require_literal(
            obj["measure_role"], MEASURE_ROLES, label=f"{label}.measure_role"
        )
        return cls(
            unit_locator=_require_locator(obj["unit_locator"], label=f"{label}.unit_locator"),
            measure_role=cast(MeasureRole, measure_role),
            ordinal=require_int(obj["ordinal"], label=f"{label}.ordinal"),
            measure=_require_qname(obj["measure"], label=f"{label}.measure"),
        )


_FACT_KEYS = frozenset(
    {
        "concept_qname",
        "context_locator",
        "unit_locator",
        "source_locator",
        "value_status",
        "raw_lexical_value",
        "resolved_text_value",
        "resolved_numeric_value",
        "resolved_value_type",
        "is_nil",
        "reported_decimals",
        "reported_precision",
        "xml_lang",
        "format_qname",
        "scale",
        "sign",
        "escape",
        "continuation_provenance",
    }
)


@dataclass(frozen=True)
class FactRecord:
    """One item-fact *source occurrence*.

    Identity is the source occurrence (``source_locator``), never
    ``(concept, context, unit, value)``: two otherwise identical occurrences must
    both survive.

    ``raw_lexical_value`` is the adapter's retained lexical value under
    :data:`edgar.xbrl.config.FACT_LEXICAL_VERSION`; the immutable source bytes
    plus locator remain authoritative. ``reported_decimals`` and
    ``reported_precision`` stay textual because ``INF`` is a legal filed value.
    ``unit_locator`` is ``None`` for non-numeric facts and for numeric facts
    whose unit could not be resolved (``value_status`` then records the failure).
    """

    concept_qname: ExpandedQName
    context_locator: SourceLocator
    source_locator: SourceLocator
    value_status: ValueStatus
    is_nil: bool = False
    unit_locator: SourceLocator | None = None
    raw_lexical_value: str | None = None
    resolved_text_value: str | None = None
    resolved_numeric_value: Decimal | None = None
    resolved_value_type: ExpandedQName | None = None
    reported_decimals: str | None = None
    reported_precision: str | None = None
    xml_lang: str | None = None
    format_qname: ExpandedQName | None = None
    scale: int | None = None
    sign: str | None = None
    escape: bool | None = None
    continuation_provenance: tuple[SourceLocator, ...] = ()

    def __post_init__(self) -> None:
        if self.value_status not in VALUE_STATUSES:
            raise ValueError(f"unknown value_status: {self.value_status!r}")
        if self.is_nil != (self.value_status == "nil"):
            raise ValueError("is_nil and value_status == 'nil' must agree")
        if self.is_nil and (
            self.resolved_numeric_value is not None or self.resolved_text_value is not None
        ):
            raise ValueError("a nil fact must not carry a resolved value")
        _assert_finite_decimal(self.resolved_numeric_value, label="resolved_numeric_value")
        if self.sign is not None and self.sign not in INLINE_SIGN_VALUES:
            raise ValueError(f"unsupported sign attribute: {self.sign!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_qname": self.concept_qname.to_dict(),
            "context_locator": self.context_locator.to_dict(),
            "unit_locator": _locator_to_dict(self.unit_locator),
            "source_locator": self.source_locator.to_dict(),
            "value_status": self.value_status,
            "raw_lexical_value": self.raw_lexical_value,
            "resolved_text_value": self.resolved_text_value,
            "resolved_numeric_value": _decimal_to_str(self.resolved_numeric_value),
            "resolved_value_type": _qname_to_dict(self.resolved_value_type),
            "is_nil": self.is_nil,
            "reported_decimals": self.reported_decimals,
            "reported_precision": self.reported_precision,
            "xml_lang": self.xml_lang,
            "format_qname": _qname_to_dict(self.format_qname),
            "scale": self.scale,
            "sign": self.sign,
            "escape": self.escape,
            "continuation_provenance": [loc.to_dict() for loc in self.continuation_provenance],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FactRecord:
        label = "fact"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _FACT_KEYS, label=label)
        value_status = _require_literal(
            obj["value_status"], VALUE_STATUSES, label=f"{label}.value_status"
        )
        return cls(
            concept_qname=_require_qname(obj["concept_qname"], label=f"{label}.concept_qname"),
            context_locator=_require_locator(
                obj["context_locator"], label=f"{label}.context_locator"
            ),
            source_locator=_require_locator(obj["source_locator"], label=f"{label}.source_locator"),
            value_status=cast(ValueStatus, value_status),
            is_nil=require_bool(obj["is_nil"], label=f"{label}.is_nil"),
            unit_locator=_require_nullable_locator(
                obj["unit_locator"], label=f"{label}.unit_locator"
            ),
            raw_lexical_value=_require_nullable_str(
                obj["raw_lexical_value"], label=f"{label}.raw_lexical_value"
            ),
            resolved_text_value=_require_nullable_str(
                obj["resolved_text_value"], label=f"{label}.resolved_text_value"
            ),
            resolved_numeric_value=_require_nullable_decimal(
                obj["resolved_numeric_value"], label=f"{label}.resolved_numeric_value"
            ),
            resolved_value_type=_require_nullable_qname(
                obj["resolved_value_type"], label=f"{label}.resolved_value_type"
            ),
            reported_decimals=_require_nullable_str(
                obj["reported_decimals"], label=f"{label}.reported_decimals"
            ),
            reported_precision=_require_nullable_str(
                obj["reported_precision"], label=f"{label}.reported_precision"
            ),
            xml_lang=_require_nullable_str(obj["xml_lang"], label=f"{label}.xml_lang"),
            format_qname=_require_nullable_qname(
                obj["format_qname"], label=f"{label}.format_qname"
            ),
            scale=_require_nullable_int(obj["scale"], label=f"{label}.scale"),
            sign=_require_nullable_str(obj["sign"], label=f"{label}.sign"),
            escape=_require_nullable_bool(obj["escape"], label=f"{label}.escape"),
            continuation_provenance=_require_locators(
                obj["continuation_provenance"], label=f"{label}.continuation_provenance"
            ),
        )


_RELATIONSHIP_KEYS = frozenset(
    {
        "network_type",
        "link_role_uri",
        "arcrole_uri",
        "source_concept",
        "target_concept",
        "order",
        "weight",
        "preferred_label_role",
        "target_role_uri",
        "closed",
        "usable",
        "context_element",
        "source_locator",
    }
)


@dataclass(frozen=True)
class RelationshipRecord:
    """One effective presentation, calculation, or definition relationship.

    ``link_role_uri`` and ``arcrole_uri`` are required (ADR 0004): a relationship
    without network identity cannot reconstruct a statement tree. Endpoints are
    concept identities that must resolve to declarations of this projection.
    """

    network_type: NetworkType
    link_role_uri: str
    arcrole_uri: str
    source_concept: ExpandedQName
    target_concept: ExpandedQName
    source_locator: SourceLocator
    order: Decimal | None = None
    weight: Decimal | None = None
    preferred_label_role: str | None = None
    target_role_uri: str | None = None
    closed: bool | None = None
    usable: bool | None = None
    context_element: ContextElement | None = None

    def __post_init__(self) -> None:
        if self.network_type not in NETWORK_TYPES:
            raise ValueError(f"unknown network_type: {self.network_type!r}")
        if not self.link_role_uri:
            raise ValueError("link_role_uri is required")
        if not self.arcrole_uri:
            raise ValueError("arcrole_uri is required")
        if self.context_element is not None and self.context_element not in CONTEXT_ELEMENTS:
            raise ValueError(f"unknown context_element: {self.context_element!r}")
        _assert_finite_decimal(self.order, label="order")
        _assert_finite_decimal(self.weight, label="weight")

    def to_dict(self) -> dict[str, Any]:
        return {
            "network_type": self.network_type,
            "link_role_uri": self.link_role_uri,
            "arcrole_uri": self.arcrole_uri,
            "source_concept": self.source_concept.to_dict(),
            "target_concept": self.target_concept.to_dict(),
            "order": _decimal_to_str(self.order),
            "weight": _decimal_to_str(self.weight),
            "preferred_label_role": self.preferred_label_role,
            "target_role_uri": self.target_role_uri,
            "closed": self.closed,
            "usable": self.usable,
            "context_element": self.context_element,
            "source_locator": self.source_locator.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelationshipRecord:
        label = "relationship"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _RELATIONSHIP_KEYS, label=label)
        network_type = _require_literal(
            obj["network_type"], NETWORK_TYPES, label=f"{label}.network_type"
        )
        context_element = _require_nullable_literal(
            obj["context_element"], CONTEXT_ELEMENTS, label=f"{label}.context_element"
        )
        return cls(
            network_type=cast(NetworkType, network_type),
            link_role_uri=require_str(obj["link_role_uri"], label=f"{label}.link_role_uri"),
            arcrole_uri=require_str(obj["arcrole_uri"], label=f"{label}.arcrole_uri"),
            source_concept=_require_qname(obj["source_concept"], label=f"{label}.source_concept"),
            target_concept=_require_qname(obj["target_concept"], label=f"{label}.target_concept"),
            source_locator=_require_locator(obj["source_locator"], label=f"{label}.source_locator"),
            order=_require_nullable_decimal(obj["order"], label=f"{label}.order"),
            weight=_require_nullable_decimal(obj["weight"], label=f"{label}.weight"),
            preferred_label_role=_require_nullable_str(
                obj["preferred_label_role"], label=f"{label}.preferred_label_role"
            ),
            target_role_uri=_require_nullable_str(
                obj["target_role_uri"], label=f"{label}.target_role_uri"
            ),
            closed=_require_nullable_bool(obj["closed"], label=f"{label}.closed"),
            usable=_require_nullable_bool(obj["usable"], label=f"{label}.usable"),
            context_element=cast(ContextElement | None, context_element),
        )


_SEMANTIC_ISSUE_KEYS = frozenset({"severity", "code", "message", "scope", "locator", "context"})


@dataclass(frozen=True)
class SemanticIssueRecord:
    """A quality issue scoped to semantic projection (never a run log line).

    A ``fatal`` issue means the projection cannot be marked semantically
    complete; it does not by itself require discarding the filing.
    """

    severity: IssueSeverity
    code: str
    message: str
    scope: IssueScope = "semantic_projection"
    locator: SourceLocator | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in ISSUE_SEVERITIES:
            raise ValueError(f"unknown issue severity: {self.severity!r}")
        if self.scope not in ISSUE_SCOPES:
            raise ValueError(f"unknown issue scope: {self.scope!r}")
        if not self.code:
            raise ValueError("issue code must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "scope": self.scope,
            "locator": _locator_to_dict(self.locator),
            "context": dict(self.context),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SemanticIssueRecord:
        label = "semantic_issue"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _SEMANTIC_ISSUE_KEYS, label=label)
        severity = _require_literal(obj["severity"], ISSUE_SEVERITIES, label=f"{label}.severity")
        scope = _require_literal(obj["scope"], ISSUE_SCOPES, label=f"{label}.scope")
        context = require_object(obj["context"], label=f"{label}.context")
        return cls(
            severity=cast(IssueSeverity, severity),
            code=require_str(obj["code"], label=f"{label}.code"),
            message=require_str(obj["message"], label=f"{label}.message"),
            scope=cast(IssueScope, scope),
            locator=_require_nullable_locator(obj["locator"], label=f"{label}.locator"),
            context=cast(dict[str, Any], _require_json_value(context, label=f"{label}.context")),
        )


_PROJECTION_KEYS = frozenset(
    {
        "schema_version",
        "projection_version",
        "config_fingerprint",
        "engine_name",
        "engine_version",
        "concept_declarations",
        "concept_labels",
        "concept_references",
        "role_declarations",
        "arcrole_declarations",
        "contexts",
        "context_dimensions",
        "units",
        "unit_measures",
        "facts",
        "relationships",
        "diagnostics",
        "issues",
    }
)


@dataclass(frozen=True)
class SemanticProjectionData:
    """The complete record set produced for one XBRL report input.

    This is the payload that crosses the worker boundary and reaches
    persistence. It intentionally carries no bundle, report-input, attempt, or
    database identity: projection identity is assembled by the calling service
    from bundle + report input + ``projection_version`` + engine version +
    ``config_fingerprint`` (ADR 0008 §2).
    """

    projection_version: str
    config_fingerprint: str
    engine_name: str
    engine_version: str
    concept_declarations: tuple[ConceptDeclarationRecord, ...] = ()
    concept_labels: tuple[ConceptLabelRecord, ...] = ()
    concept_references: tuple[ConceptReferenceRecord, ...] = ()
    role_declarations: tuple[RoleDeclarationRecord, ...] = ()
    arcrole_declarations: tuple[ArcroleDeclarationRecord, ...] = ()
    contexts: tuple[ContextRecord, ...] = ()
    context_dimensions: tuple[ContextDimensionRecord, ...] = ()
    units: tuple[UnitRecord, ...] = ()
    unit_measures: tuple[UnitMeasureRecord, ...] = ()
    facts: tuple[FactRecord, ...] = ()
    relationships: tuple[RelationshipRecord, ...] = ()
    diagnostics: tuple[DiagnosticRecord, ...] = ()
    issues: tuple[SemanticIssueRecord, ...] = ()
    schema_version: int = RECORDS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RECORDS_SCHEMA_VERSION:
            raise ValueError(f"unsupported records schema_version: {self.schema_version}")
        if not self.projection_version:
            raise ValueError("projection_version is required")
        if not self.config_fingerprint:
            raise ValueError("config_fingerprint is required")
        if not self.engine_name or not self.engine_version:
            raise ValueError("engine_name and engine_version are required")

    def record_counts(self) -> dict[str, int]:
        """Deterministic per-collection counts for reporting and golden review."""
        return {
            "concept_declarations": len(self.concept_declarations),
            "concept_labels": len(self.concept_labels),
            "concept_references": len(self.concept_references),
            "role_declarations": len(self.role_declarations),
            "arcrole_declarations": len(self.arcrole_declarations),
            "contexts": len(self.contexts),
            "context_dimensions": len(self.context_dimensions),
            "units": len(self.units),
            "unit_measures": len(self.unit_measures),
            "facts": len(self.facts),
            "relationships": len(self.relationships),
            "diagnostics": len(self.diagnostics),
            "issues": len(self.issues),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "projection_version": self.projection_version,
            "config_fingerprint": self.config_fingerprint,
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "concept_declarations": _to_dicts(self.concept_declarations),
            "concept_labels": _to_dicts(self.concept_labels),
            "concept_references": _to_dicts(self.concept_references),
            "role_declarations": _to_dicts(self.role_declarations),
            "arcrole_declarations": _to_dicts(self.arcrole_declarations),
            "contexts": _to_dicts(self.contexts),
            "context_dimensions": _to_dicts(self.context_dimensions),
            "units": _to_dicts(self.units),
            "unit_measures": _to_dicts(self.unit_measures),
            "facts": _to_dicts(self.facts),
            "relationships": _to_dicts(self.relationships),
            "diagnostics": _to_dicts(self.diagnostics),
            "issues": _to_dicts(self.issues),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SemanticProjectionData:
        label = "semantic_projection_data"
        obj = require_object(data, label=label)
        require_exact_keys(obj, _PROJECTION_KEYS, label=label)
        schema_version = require_int(obj["schema_version"], label=f"{label}.schema_version")
        if schema_version != RECORDS_SCHEMA_VERSION:
            raise RecordDecodeError(f"unsupported records schema_version: {schema_version}")
        return cls(
            projection_version=require_str(
                obj["projection_version"], label=f"{label}.projection_version"
            ),
            config_fingerprint=require_str(
                obj["config_fingerprint"], label=f"{label}.config_fingerprint"
            ),
            engine_name=require_str(obj["engine_name"], label=f"{label}.engine_name"),
            engine_version=require_str(obj["engine_version"], label=f"{label}.engine_version"),
            concept_declarations=_decode_records(
                obj["concept_declarations"],
                ConceptDeclarationRecord.from_dict,
                label=f"{label}.concept_declarations",
            ),
            concept_labels=_decode_records(
                obj["concept_labels"], ConceptLabelRecord.from_dict, label=f"{label}.concept_labels"
            ),
            concept_references=_decode_records(
                obj["concept_references"],
                ConceptReferenceRecord.from_dict,
                label=f"{label}.concept_references",
            ),
            role_declarations=_decode_records(
                obj["role_declarations"],
                RoleDeclarationRecord.from_dict,
                label=f"{label}.role_declarations",
            ),
            arcrole_declarations=_decode_records(
                obj["arcrole_declarations"],
                ArcroleDeclarationRecord.from_dict,
                label=f"{label}.arcrole_declarations",
            ),
            contexts=_decode_records(
                obj["contexts"], ContextRecord.from_dict, label=f"{label}.contexts"
            ),
            context_dimensions=_decode_records(
                obj["context_dimensions"],
                ContextDimensionRecord.from_dict,
                label=f"{label}.context_dimensions",
            ),
            units=_decode_records(obj["units"], UnitRecord.from_dict, label=f"{label}.units"),
            unit_measures=_decode_records(
                obj["unit_measures"], UnitMeasureRecord.from_dict, label=f"{label}.unit_measures"
            ),
            facts=_decode_records(obj["facts"], FactRecord.from_dict, label=f"{label}.facts"),
            relationships=_decode_records(
                obj["relationships"], RelationshipRecord.from_dict, label=f"{label}.relationships"
            ),
            diagnostics=_decode_records(
                obj["diagnostics"], DiagnosticRecord.from_dict, label=f"{label}.diagnostics"
            ),
            issues=_decode_records(
                obj["issues"], SemanticIssueRecord.from_dict, label=f"{label}.issues"
            ),
            schema_version=schema_version,
        )

    def to_json(self) -> str:
        """Deterministic JSON for the worker boundary (sorted keys, no NaN)."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def from_json(cls, text: str) -> SemanticProjectionData:
        decoded = json.loads(text)
        if type(decoded) is not dict:
            raise RecordDecodeError("semantic projection JSON must be an object")
        return cls.from_dict(decoded)


def _to_dicts(records: Sequence[Any]) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]
