"""Lossless V2 wire codec for ``ReportExtraction`` (worker IPC boundary).

JSON serialization is exact with respect to every source DTO field. The parent
performs no semantic adaptation beyond this codec.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from edgar.domain.decode import (
    BundleDecodeError,
    require_bool,
    require_exact_keys,
    require_int,
    require_list,
    require_object,
    require_str,
)
from edgar.xbrl.records import (
    BALANCES,
    CONTEXT_ELEMENTS,
    ISSUE_SEVERITIES,
    LOCATOR_SCHEMES,
    MEASURE_ROLES,
    MEMBER_KINDS,
    NETWORK_TYPES,
    PERIOD_KINDS,
    PERIOD_TYPES,
    RESOLVED_VALUE_KINDS,
    VALUE_STATUSES,
    ExpandedQName,
)
from edgar.xbrl.source_records import (
    SOURCE_RECORDS_SCHEMA_VERSION,
    ConceptDeclarationRecord,
    ConceptLabelRecord,
    ConceptRecord,
    ConceptReferenceRecord,
    ContextDimensionRecord,
    ContextRecord,
    ElementLocator,
    ExtractionIssueRecord,
    FactRecord,
    ReferencePartRecord,
    RelationshipRecord,
    ReportExtraction,
    UnitMeasureRecord,
    UnitRecord,
)

__all__ = [
    "SourceWireError",
    "report_extraction_from_dict",
    "report_extraction_to_dict",
]


class SourceWireError(BundleDecodeError):
    """Raised when a V2 source extraction wire payload fails decoding."""


def _require_literal(value: object, allowed: frozenset[str], *, label: str) -> str:
    text = require_str(value, label=label)
    if text not in allowed:
        raise SourceWireError(f"{label} must be one of {sorted(allowed)}, got {text!r}")
    return text


def _nullable_str(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return require_str(value, label=label)


def _nullable_bool(value: object, *, label: str) -> bool | None:
    if value is None:
        return None
    return require_bool(value, label=label)


def _nullable_int(value: object, *, label: str) -> int | None:
    if value is None:
        return None
    return require_int(value, label=label)


def _decimal_to_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _nullable_decimal(value: object, *, label: str) -> Decimal | None:
    if value is None:
        return None
    text = require_str(value, label=label)
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise SourceWireError(f"{label} is not an exact decimal: {text!r}") from exc
    if not parsed.is_finite():
        raise SourceWireError(f"{label} must be a finite decimal: {text!r}")
    return parsed


def _json_value(value: object, *, label: str) -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is list:
        return [_json_value(item, label=f"{label}[{i}]") for i, item in enumerate(value)]
    if type(value) is dict:
        out: dict[str, Any] = {}
        for key, item in cast(dict[Any, Any], value).items():
            if type(key) is not str:
                raise SourceWireError(f"{label} keys must be strings, got {type(key).__name__}")
            out[key] = _json_value(item, label=f"{label}.{key}")
        return out
    raise SourceWireError(f"{label} has unsupported JSON type {type(value).__name__}")


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


def _qname_to_dict(qname: ExpandedQName) -> dict[str, Any]:
    return qname.to_dict()


def _qname_from_dict(data: object, *, label: str) -> ExpandedQName:
    obj = require_object(data, label=label)
    return ExpandedQName.from_dict(obj)


def _nullable_qname(data: object, *, label: str) -> ExpandedQName | None:
    if data is None:
        return None
    return _qname_from_dict(data, label=label)


def _locator_to_dict(locator: ElementLocator | None) -> dict[str, str] | None:
    return None if locator is None else locator.to_dict()


def _locator_from_dict(data: object, *, label: str) -> ElementLocator | None:
    if data is None:
        return None
    obj = require_object(data, label=label)
    require_exact_keys(obj, frozenset({"scheme", "value"}), label=label)
    scheme = _require_literal(obj["scheme"], LOCATOR_SCHEMES, label=f"{label}.scheme")
    return ElementLocator(
        scheme=cast(Any, scheme), value=require_str(obj["value"], label=f"{label}.value")
    )


def _concept_to_dict(c: ConceptRecord) -> dict[str, str]:
    return {"namespace_uri": c.namespace_uri, "local_name": c.local_name}


def _concept_from_dict(data: dict[str, Any]) -> ConceptRecord:
    require_exact_keys(data, frozenset({"namespace_uri", "local_name"}), label="concept")
    return ConceptRecord(
        namespace_uri=require_str(data["namespace_uri"], label="concept.namespace_uri"),
        local_name=require_str(data["local_name"], label="concept.local_name"),
    )


def _declaration_to_dict(d: ConceptDeclarationRecord) -> dict[str, Any]:
    return {
        "concept": _qname_to_dict(d.concept),
        "data_type": None if d.data_type is None else _qname_to_dict(d.data_type),
        "substitution_group": (
            None if d.substitution_group is None else _qname_to_dict(d.substitution_group)
        ),
        "period_type": d.period_type,
        "balance": d.balance,
        "abstract": d.abstract,
        "nillable": d.nillable,
        "source_document_relative_path": d.source_document_relative_path,
        "source_locator": _locator_to_dict(d.source_locator),
    }


def _declaration_from_dict(data: dict[str, Any]) -> ConceptDeclarationRecord:
    period = data.get("period_type")
    balance = data.get("balance")
    return ConceptDeclarationRecord(
        concept=_qname_from_dict(data["concept"], label="declaration.concept"),
        data_type=_nullable_qname(data.get("data_type"), label="declaration.data_type"),
        substitution_group=_nullable_qname(
            data.get("substitution_group"), label="declaration.substitution_group"
        ),
        period_type=(
            None
            if period is None
            else cast(Any, _require_literal(period, PERIOD_TYPES, label="declaration.period_type"))
        ),
        balance=(
            None
            if balance is None
            else cast(Any, _require_literal(balance, BALANCES, label="declaration.balance"))
        ),
        abstract=_nullable_bool(data.get("abstract"), label="declaration.abstract"),
        nillable=_nullable_bool(data.get("nillable"), label="declaration.nillable"),
        source_document_relative_path=_nullable_str(
            data.get("source_document_relative_path"),
            label="declaration.source_document_relative_path",
        ),
        source_locator=_locator_from_dict(
            data.get("source_locator"), label="declaration.source_locator"
        ),
    )


def _label_to_dict(lab: ConceptLabelRecord) -> dict[str, Any]:
    return {
        "concept": _qname_to_dict(lab.concept),
        "link_role_uri": lab.link_role_uri,
        "arcrole_uri": lab.arcrole_uri,
        "resource_role_uri": lab.resource_role_uri,
        "text": lab.text,
        "language": lab.language,
        "order_value": _decimal_to_str(lab.order_value),
        "source_order": lab.source_order,
        "source_document_relative_path": lab.source_document_relative_path,
        "source_locator": _locator_to_dict(lab.source_locator),
        "arc_document_relative_path": lab.arc_document_relative_path,
        "arc_locator": _locator_to_dict(lab.arc_locator),
    }


def _label_from_dict(data: dict[str, Any]) -> ConceptLabelRecord:
    return ConceptLabelRecord(
        concept=_qname_from_dict(data["concept"], label="label.concept"),
        link_role_uri=require_str(data["link_role_uri"], label="label.link_role_uri"),
        arcrole_uri=require_str(data["arcrole_uri"], label="label.arcrole_uri"),
        text=require_str(data["text"], label="label.text"),
        source_order=require_int(data["source_order"], label="label.source_order"),
        language=_nullable_str(data.get("language"), label="label.language"),
        resource_role_uri=_nullable_str(
            data.get("resource_role_uri"), label="label.resource_role_uri"
        ),
        order_value=_nullable_decimal(data.get("order_value"), label="label.order_value"),
        source_document_relative_path=_nullable_str(
            data.get("source_document_relative_path"),
            label="label.source_document_relative_path",
        ),
        source_locator=_locator_from_dict(data.get("source_locator"), label="label.source_locator"),
        arc_document_relative_path=_nullable_str(
            data.get("arc_document_relative_path"),
            label="label.arc_document_relative_path",
        ),
        arc_locator=_locator_from_dict(data.get("arc_locator"), label="label.arc_locator"),
    )


def _reference_to_dict(ref: ConceptReferenceRecord) -> dict[str, Any]:
    return {
        "concept": _qname_to_dict(ref.concept),
        "link_role_uri": ref.link_role_uri,
        "arcrole_uri": ref.arcrole_uri,
        "resource_role_uri": ref.resource_role_uri,
        "source_order": ref.source_order,
        "order_value": _decimal_to_str(ref.order_value),
        "reference_parts": [p.to_dict() for p in ref.reference_parts],
        "source_document_relative_path": ref.source_document_relative_path,
        "source_locator": _locator_to_dict(ref.source_locator),
        "arc_document_relative_path": ref.arc_document_relative_path,
        "arc_locator": _locator_to_dict(ref.arc_locator),
    }


def _reference_from_dict(data: dict[str, Any]) -> ConceptReferenceRecord:
    parts_raw = require_list(data.get("reference_parts", []), label="reference.reference_parts")
    parts: list[ReferencePartRecord] = []
    for i, item in enumerate(parts_raw):
        obj = require_object(item, label=f"reference.reference_parts[{i}]")
        require_exact_keys(
            obj, frozenset({"qname", "value"}), label=f"reference.reference_parts[{i}]"
        )
        parts.append(
            ReferencePartRecord(
                qname=require_str(obj["qname"], label=f"reference.reference_parts[{i}].qname"),
                value=require_str(obj["value"], label=f"reference.reference_parts[{i}].value"),
            )
        )
    return ConceptReferenceRecord(
        concept=_qname_from_dict(data["concept"], label="reference.concept"),
        link_role_uri=require_str(data["link_role_uri"], label="reference.link_role_uri"),
        arcrole_uri=require_str(data["arcrole_uri"], label="reference.arcrole_uri"),
        source_order=require_int(data["source_order"], label="reference.source_order"),
        reference_parts=tuple(parts),
        resource_role_uri=_nullable_str(
            data.get("resource_role_uri"), label="reference.resource_role_uri"
        ),
        order_value=_nullable_decimal(data.get("order_value"), label="reference.order_value"),
        source_document_relative_path=_nullable_str(
            data.get("source_document_relative_path"),
            label="reference.source_document_relative_path",
        ),
        source_locator=_locator_from_dict(
            data.get("source_locator"), label="reference.source_locator"
        ),
        arc_document_relative_path=_nullable_str(
            data.get("arc_document_relative_path"),
            label="reference.arc_document_relative_path",
        ),
        arc_locator=_locator_from_dict(data.get("arc_locator"), label="reference.arc_locator"),
    )


def _context_to_dict(ctx: ContextRecord) -> dict[str, Any]:
    return {
        "source_context_id": ctx.source_context_id,
        "entity_scheme": ctx.entity_scheme,
        "entity_identifier": ctx.entity_identifier,
        "period_kind": ctx.period_kind,
        "period_instant": ctx.period_instant,
        "period_start": ctx.period_start,
        "period_end": ctx.period_end,
        "source_document_relative_path": ctx.source_document_relative_path,
        "source_locator": _locator_to_dict(ctx.source_locator),
    }


def _context_from_dict(data: dict[str, Any]) -> ContextRecord:
    return ContextRecord(
        source_context_id=require_str(data["source_context_id"], label="context.source_context_id"),
        entity_scheme=require_str(data["entity_scheme"], label="context.entity_scheme"),
        entity_identifier=require_str(data["entity_identifier"], label="context.entity_identifier"),
        period_kind=cast(
            Any, _require_literal(data["period_kind"], PERIOD_KINDS, label="context.period_kind")
        ),
        period_instant=_nullable_str(data.get("period_instant"), label="context.period_instant"),
        period_start=_nullable_str(data.get("period_start"), label="context.period_start"),
        period_end=_nullable_str(data.get("period_end"), label="context.period_end"),
        source_document_relative_path=_nullable_str(
            data.get("source_document_relative_path"),
            label="context.source_document_relative_path",
        ),
        source_locator=_locator_from_dict(
            data.get("source_locator"), label="context.source_locator"
        ),
    )


def _dimension_to_dict(dim: ContextDimensionRecord) -> dict[str, Any]:
    return {
        "source_context_id": dim.source_context_id,
        "dimension": _qname_to_dict(dim.dimension),
        "context_element": dim.context_element,
        "member_kind": dim.member_kind,
        "member": None if dim.member is None else _qname_to_dict(dim.member),
        "typed_member": None if dim.typed_member is None else dict(dim.typed_member),
        "source_document_relative_path": dim.source_document_relative_path,
        "source_locator": _locator_to_dict(dim.source_locator),
    }


def _dimension_from_dict(data: dict[str, Any]) -> ContextDimensionRecord:
    typed = data.get("typed_member")
    typed_member: dict[str, Any] | None = None
    if typed is not None:
        typed_member = cast(dict[str, Any], _json_value(typed, label="dimension.typed_member"))
    return ContextDimensionRecord(
        source_context_id=require_str(
            data["source_context_id"], label="dimension.source_context_id"
        ),
        dimension=_qname_from_dict(data["dimension"], label="dimension.dimension"),
        context_element=cast(
            Any,
            _require_literal(
                data["context_element"], CONTEXT_ELEMENTS, label="dimension.context_element"
            ),
        ),
        member_kind=cast(
            Any, _require_literal(data["member_kind"], MEMBER_KINDS, label="dimension.member_kind")
        ),
        member=_nullable_qname(data.get("member"), label="dimension.member"),
        typed_member=typed_member,
        source_document_relative_path=_nullable_str(
            data.get("source_document_relative_path"),
            label="dimension.source_document_relative_path",
        ),
        source_locator=_locator_from_dict(
            data.get("source_locator"), label="dimension.source_locator"
        ),
    )


def _unit_to_dict(unit: UnitRecord) -> dict[str, Any]:
    return {
        "source_unit_id": unit.source_unit_id,
        "divide": unit.divide,
        "source_document_relative_path": unit.source_document_relative_path,
        "source_locator": _locator_to_dict(unit.source_locator),
    }


def _unit_from_dict(data: dict[str, Any]) -> UnitRecord:
    return UnitRecord(
        source_unit_id=require_str(data["source_unit_id"], label="unit.source_unit_id"),
        divide=require_bool(data.get("divide", False), label="unit.divide"),
        source_document_relative_path=_nullable_str(
            data.get("source_document_relative_path"), label="unit.source_document_relative_path"
        ),
        source_locator=_locator_from_dict(data.get("source_locator"), label="unit.source_locator"),
    )


def _measure_to_dict(m: UnitMeasureRecord) -> dict[str, Any]:
    return {
        "source_unit_id": m.source_unit_id,
        "side": m.side,
        "ordinal": m.ordinal,
        "measure": _qname_to_dict(m.measure),
    }


def _measure_from_dict(data: dict[str, Any]) -> UnitMeasureRecord:
    return UnitMeasureRecord(
        source_unit_id=require_str(data["source_unit_id"], label="measure.source_unit_id"),
        side=cast(Any, _require_literal(data["side"], MEASURE_ROLES, label="measure.side")),
        ordinal=require_int(data["ordinal"], label="measure.ordinal"),
        measure=_qname_from_dict(data["measure"], label="measure.measure"),
    )


def _fact_to_dict(fact: FactRecord) -> dict[str, Any]:
    return {
        "source_order": fact.source_order,
        "concept": _qname_to_dict(fact.concept),
        "source_context_id": fact.source_context_id,
        "value_status": fact.value_status,
        "is_nil": fact.is_nil,
        "source_unit_id": fact.source_unit_id,
        "raw_lexical_value": fact.raw_lexical_value,
        "resolved_value_kind": fact.resolved_value_kind,
        "resolved_numeric": _decimal_to_str(fact.resolved_numeric),
        "resolved_text": fact.resolved_text,
        "decimals": fact.decimals,
        "precision": fact.precision,
        "xml_lang": fact.xml_lang,
        "scale": fact.scale,
        "sign": fact.sign,
        "format_namespace_uri": fact.format_namespace_uri,
        "format_local_name": fact.format_local_name,
        "escape": fact.escape,
        "continuation_provenance": [
            _json_value(dict(c), label="continuation") for c in fact.continuation_provenance
        ],
        "source_xml_id": fact.source_xml_id,
        "source_document_relative_path": fact.source_document_relative_path,
        "source_locator": _locator_to_dict(fact.source_locator),
    }


def _fact_from_dict(data: dict[str, Any]) -> FactRecord:
    cont_raw = require_list(
        data.get("continuation_provenance", []), label="fact.continuation_provenance"
    )
    continuation = tuple(
        cast(Mapping[str, Any], _json_value(item, label=f"fact.continuation_provenance[{i}]"))
        for i, item in enumerate(cont_raw)
    )
    kind = data.get("resolved_value_kind")
    return FactRecord(
        source_order=require_int(data["source_order"], label="fact.source_order"),
        concept=_qname_from_dict(data["concept"], label="fact.concept"),
        source_context_id=require_str(data["source_context_id"], label="fact.source_context_id"),
        value_status=cast(
            Any, _require_literal(data["value_status"], VALUE_STATUSES, label="fact.value_status")
        ),
        is_nil=require_bool(data.get("is_nil", False), label="fact.is_nil"),
        source_unit_id=_nullable_str(data.get("source_unit_id"), label="fact.source_unit_id"),
        raw_lexical_value=_nullable_str(
            data.get("raw_lexical_value"), label="fact.raw_lexical_value"
        ),
        resolved_value_kind=(
            None
            if kind is None
            else cast(
                Any,
                _require_literal(kind, RESOLVED_VALUE_KINDS, label="fact.resolved_value_kind"),
            )
        ),
        resolved_numeric=_nullable_decimal(
            data.get("resolved_numeric"), label="fact.resolved_numeric"
        ),
        resolved_text=_nullable_str(data.get("resolved_text"), label="fact.resolved_text"),
        decimals=_nullable_str(data.get("decimals"), label="fact.decimals"),
        precision=_nullable_str(data.get("precision"), label="fact.precision"),
        xml_lang=_nullable_str(data.get("xml_lang"), label="fact.xml_lang"),
        scale=_nullable_int(data.get("scale"), label="fact.scale"),
        sign=_nullable_str(data.get("sign"), label="fact.sign"),
        format_namespace_uri=_nullable_str(
            data.get("format_namespace_uri"), label="fact.format_namespace_uri"
        ),
        format_local_name=_nullable_str(
            data.get("format_local_name"), label="fact.format_local_name"
        ),
        escape=_nullable_bool(data.get("escape"), label="fact.escape"),
        continuation_provenance=continuation,
        source_xml_id=_nullable_str(data.get("source_xml_id"), label="fact.source_xml_id"),
        source_document_relative_path=_nullable_str(
            data.get("source_document_relative_path"),
            label="fact.source_document_relative_path",
        ),
        source_locator=_locator_from_dict(data.get("source_locator"), label="fact.source_locator"),
    )


def _relationship_to_dict(rel: RelationshipRecord) -> dict[str, Any]:
    return {
        "source_order": rel.source_order,
        "network_type": rel.network_type,
        "link_role_uri": rel.link_role_uri,
        "arcrole_uri": rel.arcrole_uri,
        "source_concept": _qname_to_dict(rel.source_concept),
        "target_concept": _qname_to_dict(rel.target_concept),
        "order_value": _decimal_to_str(rel.order_value),
        "weight": _decimal_to_str(rel.weight),
        "preferred_label": rel.preferred_label,
        "target_role": rel.target_role,
        "attributes": None if rel.attributes is None else dict(rel.attributes),
        "source_document_relative_path": rel.source_document_relative_path,
        "source_locator": _locator_to_dict(rel.source_locator),
    }


def _relationship_from_dict(data: dict[str, Any]) -> RelationshipRecord:
    attrs = data.get("attributes")
    attributes: dict[str, Any] | None = None
    if attrs is not None:
        attributes = cast(dict[str, Any], _json_value(attrs, label="relationship.attributes"))
    return RelationshipRecord(
        source_order=require_int(data["source_order"], label="relationship.source_order"),
        network_type=cast(
            Any,
            _require_literal(
                data["network_type"], NETWORK_TYPES, label="relationship.network_type"
            ),
        ),
        link_role_uri=require_str(data["link_role_uri"], label="relationship.link_role_uri"),
        arcrole_uri=require_str(data["arcrole_uri"], label="relationship.arcrole_uri"),
        source_concept=_qname_from_dict(
            data["source_concept"], label="relationship.source_concept"
        ),
        target_concept=_qname_from_dict(
            data["target_concept"], label="relationship.target_concept"
        ),
        order_value=_nullable_decimal(data.get("order_value"), label="relationship.order_value"),
        weight=_nullable_decimal(data.get("weight"), label="relationship.weight"),
        preferred_label=_nullable_str(
            data.get("preferred_label"), label="relationship.preferred_label"
        ),
        target_role=_nullable_str(data.get("target_role"), label="relationship.target_role"),
        attributes=attributes,
        source_document_relative_path=_nullable_str(
            data.get("source_document_relative_path"),
            label="relationship.source_document_relative_path",
        ),
        source_locator=_locator_from_dict(
            data.get("source_locator"), label="relationship.source_locator"
        ),
    )


def _issue_to_dict(issue: ExtractionIssueRecord) -> dict[str, Any]:
    return {
        "component": issue.component,
        "code": issue.code,
        "severity": issue.severity,
        "message": issue.message,
        "details": dict(issue.details),
        "source_document_relative_path": issue.source_document_relative_path,
        "source_locator": _locator_to_dict(issue.source_locator),
    }


def _issue_from_dict(data: dict[str, Any]) -> ExtractionIssueRecord:
    details = data.get("details", {})
    return ExtractionIssueRecord(
        component=require_str(data["component"], label="issue.component"),
        code=require_str(data["code"], label="issue.code"),
        severity=cast(
            Any, _require_literal(data["severity"], ISSUE_SEVERITIES, label="issue.severity")
        ),
        message=require_str(data["message"], label="issue.message"),
        details=cast(dict[str, Any], _json_value(details, label="issue.details")),
        source_document_relative_path=_nullable_str(
            data.get("source_document_relative_path"),
            label="issue.source_document_relative_path",
        ),
        source_locator=_locator_from_dict(data.get("source_locator"), label="issue.source_locator"),
    )


_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "report_input",
        "report_key",
        "extractor_version",
        "arelle_version",
        "arelle_item_fact_count",
        "concepts",
        "declarations",
        "labels",
        "references",
        "contexts",
        "dimensions",
        "units",
        "measures",
        "facts",
        "relationships",
        "issues",
    }
)


def report_extraction_to_dict(report: ReportExtraction) -> dict[str, Any]:
    """Serialize one ``ReportExtraction`` for worker IPC."""
    return {
        "schema_version": SOURCE_RECORDS_SCHEMA_VERSION,
        "report_input": dict(report.report_input),
        "report_key": report.report_key,
        "extractor_version": report.extractor_version,
        "arelle_version": report.arelle_version,
        "arelle_item_fact_count": report.arelle_item_fact_count,
        "concepts": [_concept_to_dict(c) for c in report.concepts],
        "declarations": [_declaration_to_dict(d) for d in report.declarations],
        "labels": [_label_to_dict(lab) for lab in report.labels],
        "references": [_reference_to_dict(ref) for ref in report.references],
        "contexts": [_context_to_dict(ctx) for ctx in report.contexts],
        "dimensions": [_dimension_to_dict(dim) for dim in report.dimensions],
        "units": [_unit_to_dict(u) for u in report.units],
        "measures": [_measure_to_dict(m) for m in report.measures],
        "facts": [_fact_to_dict(f) for f in report.facts],
        "relationships": [_relationship_to_dict(r) for r in report.relationships],
        "issues": [_issue_to_dict(i) for i in report.issues],
    }


def report_extraction_from_dict(data: Mapping[str, Any]) -> ReportExtraction:
    """Deserialize one ``ReportExtraction`` from worker IPC."""
    obj = require_object(dict(data), label="report_extraction")
    require_exact_keys(obj, _REPORT_KEYS, label="report_extraction")
    schema_version = require_int(obj["schema_version"], label="report_extraction.schema_version")
    if schema_version != SOURCE_RECORDS_SCHEMA_VERSION:
        raise SourceWireError(
            f"unsupported source records schema_version: {schema_version!r} "
            f"(expected {SOURCE_RECORDS_SCHEMA_VERSION})"
        )
    report_input = require_object(obj["report_input"], label="report_extraction.report_input")
    return ReportExtraction(
        report_input=dict(report_input),
        report_key=require_str(obj["report_key"], label="report_extraction.report_key"),
        extractor_version=require_str(
            obj["extractor_version"], label="report_extraction.extractor_version"
        ),
        arelle_version=require_str(obj["arelle_version"], label="report_extraction.arelle_version"),
        arelle_item_fact_count=require_int(
            obj["arelle_item_fact_count"], label="report_extraction.arelle_item_fact_count"
        ),
        concepts=_decode_records(obj["concepts"], _concept_from_dict, label="concepts"),
        declarations=_decode_records(
            obj["declarations"], _declaration_from_dict, label="declarations"
        ),
        labels=_decode_records(obj["labels"], _label_from_dict, label="labels"),
        references=_decode_records(obj["references"], _reference_from_dict, label="references"),
        contexts=_decode_records(obj["contexts"], _context_from_dict, label="contexts"),
        dimensions=_decode_records(obj["dimensions"], _dimension_from_dict, label="dimensions"),
        units=_decode_records(obj["units"], _unit_from_dict, label="units"),
        measures=_decode_records(obj["measures"], _measure_from_dict, label="measures"),
        facts=_decode_records(obj["facts"], _fact_from_dict, label="facts"),
        relationships=_decode_records(
            obj["relationships"], _relationship_from_dict, label="relationships"
        ),
        issues=_decode_records(obj["issues"], _issue_from_dict, label="issues"),
    )
