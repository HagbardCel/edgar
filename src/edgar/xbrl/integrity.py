"""Same-report integrity validation on ReportExtraction (M1A-3)."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

import lxml.etree as etree

from edgar.xbrl.records import ExpandedQName
from edgar.xbrl.source_records import (
    ConceptDeclarationRecord,
    ContextRecord,
    ReportExtraction,
    UnitRecord,
)


class ReportIntegrityError(ValueError):
    """ReportExtraction violates same-report reference integrity."""


def _parse_typed_member_xml(xml: str) -> None:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )
    try:
        etree.fromstring(xml.encode("utf-8"), parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ReportIntegrityError(f"typed_member xml is not well-formed: {exc}") from exc


def _decl_key(concept: ExpandedQName) -> tuple[str, str]:
    if concept.namespace_uri is None:
        raise ReportIntegrityError(f"concept {concept.clark} missing namespace_uri")
    return (concept.namespace_uri, concept.local_name)


def validate_report_extraction(report: ReportExtraction) -> None:
    declarations_by_qname: dict[tuple[str, str], ConceptDeclarationRecord] = {}
    for decl in report.declarations:
        key = _decl_key(decl.concept)
        if key in declarations_by_qname:
            raise ReportIntegrityError(f"duplicate declaration for concept {decl.concept.clark}")
        declarations_by_qname[key] = decl

    contexts_by_source_id: dict[str, ContextRecord] = {}
    for ctx in report.contexts:
        if ctx.source_context_id in contexts_by_source_id:
            raise ReportIntegrityError(f"duplicate context id {ctx.source_context_id!r}")
        contexts_by_source_id[ctx.source_context_id] = ctx

    units_by_source_id: dict[str, UnitRecord] = {}
    for unit in report.units:
        if unit.source_unit_id in units_by_source_id:
            raise ReportIntegrityError(f"duplicate unit id {unit.source_unit_id!r}")
        units_by_source_id[unit.source_unit_id] = unit

    context_id_by_source: Mapping[str, str] = {
        c.source_context_id: c.source_context_id for c in report.contexts
    }

    for fact in report.facts:
        if fact.source_context_id not in contexts_by_source_id:
            raise ReportIntegrityError(
                f"fact references unknown context {fact.source_context_id!r}"
            )
        if fact.source_unit_id is not None and fact.source_unit_id not in units_by_source_id:
            raise ReportIntegrityError(f"fact references unknown unit {fact.source_unit_id!r}")
        key = _decl_key(fact.concept)
        if key not in declarations_by_qname:
            raise ReportIntegrityError(f"fact concept {fact.concept.clark} has no declaration")

    for label in report.labels:
        if _decl_key(label.concept) not in declarations_by_qname:
            raise ReportIntegrityError(f"label concept {label.concept.clark} has no declaration")

    for ref in report.references:
        if _decl_key(ref.concept) not in declarations_by_qname:
            raise ReportIntegrityError(f"reference concept {ref.concept.clark} has no declaration")

    for rel in report.relationships:
        if _decl_key(rel.source_concept) not in declarations_by_qname:
            raise ReportIntegrityError(
                f"relationship source {rel.source_concept.clark} has no declaration"
            )
        if _decl_key(rel.target_concept) not in declarations_by_qname:
            raise ReportIntegrityError(
                f"relationship target {rel.target_concept.clark} has no declaration"
            )

    unit_id_by_source = {u.source_unit_id: u.source_unit_id for u in report.units}
    for dim in report.dimensions:
        if dim.source_context_id not in context_id_by_source:
            raise ReportIntegrityError(
                f"dimension references unknown context {dim.source_context_id!r}"
            )
        if _decl_key(dim.dimension) not in declarations_by_qname:
            raise ReportIntegrityError(f"dimension {dim.dimension.clark} has no declaration")
        if (
            dim.member_kind == "explicit"
            and dim.member is not None
            and _decl_key(dim.member) not in declarations_by_qname
        ):
            raise ReportIntegrityError(f"explicit member {dim.member.clark} has no declaration")
        if dim.member_kind == "typed":
            if dim.typed_member is None:
                raise ReportIntegrityError("typed member missing typed_member payload")
            if not isinstance(dim.typed_member, dict):
                raise ReportIntegrityError("typed_member must be a mapping")
            xml = dim.typed_member.get("xml")
            digest = dim.typed_member.get("sha256")
            if not isinstance(xml, str) or not isinstance(digest, str):
                raise ReportIntegrityError("typed_member requires string xml and sha256")
            _parse_typed_member_xml(xml)
            expected = hashlib.sha256(xml.encode("utf-8")).hexdigest()
            if digest != expected:
                raise ReportIntegrityError("typed_member digest mismatch")

    for measure in report.measures:
        if measure.source_unit_id not in unit_id_by_source:
            raise ReportIntegrityError(
                f"unit measure references unknown unit {measure.source_unit_id!r}"
            )
