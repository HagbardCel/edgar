"""Build ``ReportExtraction`` from in-extractor Arelle record pieces.

URI → FilingBundle ``logical_path`` mapping happens here inside the extractor
boundary. Provenance is populated before the worker payload is serialized.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from edgar.domain.bundle import UriBinding, XbrlReportInput
from edgar.domain.report_key import report_input_payload
from edgar.domain.report_key import report_key as compute_report_key
from edgar.xbrl import records as phase1
from edgar.xbrl.records import ExpandedQName, SemanticIssueRecord, SourceLocator
from edgar.xbrl.source_records import (
    EXTRACTOR_VERSION,
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


class SourceBuildError(ValueError):
    """Raised when extracted Arelle records cannot form a source DTO."""


def uri_to_logical_path_map(bindings: Sequence[UriBinding]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for binding in bindings:
        mapping[binding.document_uri] = binding.artifact_path
        for alias in binding.replay_aliases:
            mapping[alias] = binding.artifact_path
    return mapping


def resolve_logical_path(
    document_uri: str,
    uri_paths: Mapping[str, str],
    *,
    required: bool,
    what: str,
) -> str | None:
    path = uri_paths.get(document_uri)
    if path is None and required:
        raise SourceBuildError(
            f"cannot resolve {what} document_uri to bundle logical_path: {document_uri!r}"
        )
    return path


def _element_locator(locator: SourceLocator) -> ElementLocator:
    return ElementLocator(scheme=locator.scheme, value=locator.value)


def _optional_path_and_locator(
    locator: SourceLocator | None,
    uri_paths: Mapping[str, str],
    *,
    required: bool,
    what: str,
) -> tuple[str | None, ElementLocator | None]:
    if locator is None:
        if required:
            raise SourceBuildError(f"{what} requires a source locator")
        return None, None
    path = resolve_logical_path(locator.document_uri, uri_paths, required=required, what=what)
    return path, _element_locator(locator)


def _clark(qname: ExpandedQName) -> str:
    return qname.clark


def _require_namespaced(concept: ExpandedQName, *, what: str) -> ExpandedQName:
    if concept.namespace_uri is None or not concept.namespace_uri:
        raise SourceBuildError(f"{what} requires a non-empty namespace_uri: {concept!r}")
    return concept


def _context_id_by_locator(contexts: Sequence[phase1.ContextRecord]) -> dict[SourceLocator, str]:
    mapping: dict[SourceLocator, str] = {}
    for ctx in contexts:
        if ctx.source_locator in mapping:
            raise SourceBuildError(
                f"duplicate context source_locator for source_context_id {ctx.source_context_id!r}"
            )
        mapping[ctx.source_locator] = ctx.source_context_id
    return mapping


def _unit_id_by_locator(units: Sequence[phase1.UnitRecord]) -> dict[SourceLocator, str]:
    mapping: dict[SourceLocator, str] = {}
    for unit in units:
        if unit.source_locator in mapping:
            raise SourceBuildError(
                f"duplicate unit source_locator for source_unit_id {unit.source_unit_id!r}"
            )
        mapping[unit.source_locator] = unit.source_unit_id
    return mapping


def _build_concepts(
    declarations: Sequence[phase1.ConceptDeclarationRecord],
) -> tuple[ConceptRecord, ...]:
    seen: set[tuple[str, str]] = set()
    concepts: list[ConceptRecord] = []
    for decl in declarations:
        concept = _require_namespaced(decl.concept, what="concept declaration")
        key = (concept.namespace_uri or "", concept.local_name)
        if key in seen:
            continue
        seen.add(key)
        concepts.append(
            ConceptRecord(namespace_uri=concept.namespace_uri or "", local_name=concept.local_name)
        )
    concepts.sort(key=lambda c: (c.namespace_uri, c.local_name))
    return tuple(concepts)


def _build_declarations(
    declarations: Sequence[phase1.ConceptDeclarationRecord],
    uri_paths: Mapping[str, str],
) -> tuple[ConceptDeclarationRecord, ...]:
    out: list[ConceptDeclarationRecord] = []
    for decl in declarations:
        path, locator = _optional_path_and_locator(
            decl.source_locator, uri_paths, required=False, what="concept declaration"
        )
        out.append(
            ConceptDeclarationRecord(
                concept=_require_namespaced(decl.concept, what="concept declaration"),
                data_type=decl.data_type,
                substitution_group=decl.substitution_group,
                period_type=decl.period_type,
                balance=decl.balance,
                abstract=decl.abstract,
                nillable=decl.nillable,
                source_document_relative_path=path,
                source_locator=locator,
            )
        )
    return tuple(out)


def _build_labels(labels: Sequence[phase1.ConceptLabelRecord]) -> tuple[ConceptLabelRecord, ...]:
    """Emit-order ``source_order`` (no post-sort)."""
    out: list[ConceptLabelRecord] = []
    for index, lab in enumerate(labels):
        role_uri = lab.resource_role_uri or lab.link_role_uri
        out.append(
            ConceptLabelRecord(
                concept=_require_namespaced(lab.concept, what="concept label"),
                role_uri=role_uri,
                text=lab.text,
                language=lab.xml_lang,
                source_order=index,
            )
        )
    return tuple(out)


def _build_references(
    references: Sequence[phase1.ConceptReferenceRecord],
) -> tuple[ConceptReferenceRecord, ...]:
    out: list[ConceptReferenceRecord] = []
    for index, ref in enumerate(references):
        role_uri = ref.resource_role_uri or ref.link_role_uri
        parts = tuple(
            ReferencePartRecord(
                qname=_clark(
                    ExpandedQName(namespace_uri=part.namespace_uri, local_name=part.local_name)
                ),
                value=part.text,
            )
            for part in ref.reference_parts
        )
        out.append(
            ConceptReferenceRecord(
                concept=_require_namespaced(ref.concept, what="concept reference"),
                role_uri=role_uri,
                source_order=index,
                reference_parts=parts,
            )
        )
    return tuple(out)


def _build_contexts(
    contexts: Sequence[phase1.ContextRecord],
    uri_paths: Mapping[str, str],
) -> tuple[ContextRecord, ...]:
    out: list[ContextRecord] = []
    for ctx in contexts:
        path, locator = _optional_path_and_locator(
            ctx.source_locator, uri_paths, required=False, what="context"
        )
        out.append(
            ContextRecord(
                source_context_id=ctx.source_context_id,
                entity_scheme=ctx.entity_scheme,
                entity_identifier=ctx.entity_identifier,
                period_kind=ctx.period_kind,
                period_instant=ctx.period_instant,
                period_start=ctx.period_start,
                period_end=ctx.period_end,
                source_document_relative_path=path,
                source_locator=locator,
            )
        )
    return tuple(out)


def _build_dimensions(
    dimensions: Sequence[phase1.ContextDimensionRecord],
    context_ids: Mapping[SourceLocator, str],
    uri_paths: Mapping[str, str],
) -> tuple[ContextDimensionRecord, ...]:
    out: list[ContextDimensionRecord] = []
    for dim in dimensions:
        source_context_id = context_ids.get(dim.context_locator)
        if source_context_id is None:
            raise SourceBuildError(
                "context dimension context_locator does not resolve to a source_context_id"
            )
        path, locator = _optional_path_and_locator(
            dim.source_locator, uri_paths, required=False, what="context dimension"
        )
        typed_member: dict[str, Any] | None = None
        if dim.member_kind == "typed":
            typed_member = {
                "xml": dim.typed_member_xml,
                "sha256": dim.typed_member_sha256,
            }
        out.append(
            ContextDimensionRecord(
                source_context_id=source_context_id,
                dimension=_require_namespaced(dim.dimension, what="dimension"),
                context_element=dim.context_element,
                member_kind=dim.member_kind,
                member=(
                    _require_namespaced(dim.member, what="dimension member")
                    if dim.member is not None
                    else None
                ),
                typed_member=typed_member,
                source_document_relative_path=path,
                source_locator=locator,
            )
        )
    return tuple(out)


def _build_units(
    units: Sequence[phase1.UnitRecord],
    uri_paths: Mapping[str, str],
) -> tuple[UnitRecord, ...]:
    out: list[UnitRecord] = []
    for unit in units:
        path, locator = _optional_path_and_locator(
            unit.source_locator, uri_paths, required=False, what="unit"
        )
        out.append(
            UnitRecord(
                source_unit_id=unit.source_unit_id,
                divide=unit.divide,
                source_document_relative_path=path,
                source_locator=locator,
            )
        )
    return tuple(out)


def _build_measures(
    measures: Sequence[phase1.UnitMeasureRecord],
    unit_ids: Mapping[SourceLocator, str],
) -> tuple[UnitMeasureRecord, ...]:
    out: list[UnitMeasureRecord] = []
    for measure in measures:
        source_unit_id = unit_ids.get(measure.unit_locator)
        if source_unit_id is None:
            raise SourceBuildError("unit measure unit_locator does not resolve to a source_unit_id")
        out.append(
            UnitMeasureRecord(
                source_unit_id=source_unit_id,
                side=measure.measure_role,
                ordinal=measure.ordinal,
                measure=measure.measure,
            )
        )
    return tuple(out)


def _build_facts(
    facts: Sequence[tuple[int, phase1.FactRecord]],
    context_ids: Mapping[SourceLocator, str],
    unit_ids: Mapping[SourceLocator, str],
    uri_paths: Mapping[str, str],
) -> tuple[FactRecord, ...]:
    """Build facts using the authoritative iterator ordinal already assigned."""
    out: list[FactRecord] = []
    for source_order, fact in facts:
        source_context_id = context_ids.get(fact.context_locator)
        if source_context_id is None:
            raise SourceBuildError("fact context_locator does not resolve to a source_context_id")
        source_unit_id: str | None = None
        if fact.unit_locator is not None:
            source_unit_id = unit_ids.get(fact.unit_locator)
            if source_unit_id is None:
                raise SourceBuildError("fact unit_locator does not resolve to a source_unit_id")
        path, locator = _optional_path_and_locator(
            fact.source_locator, uri_paths, required=True, what="fact"
        )
        source_xml_id: str | None = None
        if fact.source_locator.scheme in {"xml_id", "unqualified_id"}:
            source_xml_id = fact.source_locator.value
        continuation: list[dict[str, Any]] = []
        for cont in fact.continuation_provenance:
            cont_path = resolve_logical_path(
                cont.document_uri, uri_paths, required=True, what="fact continuation"
            )
            continuation.append(
                {
                    "source_document_relative_path": cont_path,
                    "scheme": cont.scheme,
                    "value": cont.value,
                }
            )
        format_ns = fact.format_qname.namespace_uri if fact.format_qname else None
        format_local = fact.format_qname.local_name if fact.format_qname else None
        out.append(
            FactRecord(
                source_order=source_order,
                concept=_require_namespaced(fact.concept_qname, what="fact concept"),
                source_context_id=source_context_id,
                value_status=fact.value_status,
                is_nil=fact.is_nil,
                source_unit_id=source_unit_id,
                raw_lexical_value=fact.raw_lexical_value,
                resolved_value_kind=fact.resolved_value_kind,
                resolved_numeric=fact.resolved_numeric_value,
                resolved_text=fact.resolved_text_value,
                decimals=fact.reported_decimals,
                precision=fact.reported_precision,
                xml_lang=fact.xml_lang,
                scale=fact.scale,
                sign=fact.sign,
                format_namespace_uri=format_ns,
                format_local_name=format_local,
                escape=fact.escape,
                continuation_provenance=tuple(continuation),
                source_xml_id=source_xml_id,
                source_document_relative_path=path,
                source_locator=locator,
            )
        )
    return tuple(out)


def _build_relationships(
    relationships: Sequence[phase1.RelationshipRecord],
    uri_paths: Mapping[str, str],
) -> tuple[RelationshipRecord, ...]:
    """Emit-order ``source_order`` (caller must not sort before this)."""
    out: list[RelationshipRecord] = []
    for index, rel in enumerate(relationships):
        path, locator = _optional_path_and_locator(
            rel.source_locator, uri_paths, required=False, what="relationship"
        )
        attributes: dict[str, Any] = {}
        if rel.closed is not None:
            attributes["closed"] = rel.closed
        if rel.usable is not None:
            attributes["usable"] = rel.usable
        if rel.context_element is not None:
            attributes["context_element"] = rel.context_element
        out.append(
            RelationshipRecord(
                source_order=index,
                network_type=rel.network_type,
                link_role_uri=rel.link_role_uri,
                arcrole_uri=rel.arcrole_uri,
                source_concept=_require_namespaced(rel.source_concept, what="relationship source"),
                target_concept=_require_namespaced(rel.target_concept, what="relationship target"),
                order_value=rel.order,
                weight=rel.weight,
                preferred_label=rel.preferred_label_role,
                target_role=rel.target_role_uri,
                attributes=attributes or None,
                source_document_relative_path=path,
                source_locator=locator,
            )
        )
    return tuple(out)


def _build_issues(
    issues: Sequence[SemanticIssueRecord],
    uri_paths: Mapping[str, str],
) -> tuple[ExtractionIssueRecord, ...]:
    out: list[ExtractionIssueRecord] = []
    for issue in issues:
        path: str | None = None
        locator: ElementLocator | None = None
        if issue.locator is not None:
            path, locator = _optional_path_and_locator(
                issue.locator, uri_paths, required=False, what="issue"
            )
        out.append(
            ExtractionIssueRecord(
                component="xbrl",
                code=issue.code,
                severity=issue.severity,
                message=issue.message,
                details=dict(issue.context),
                source_document_relative_path=path,
                source_locator=locator,
            )
        )
    return tuple(out)


def build_report_extraction(
    *,
    report_input: XbrlReportInput | Mapping[str, Any],
    uri_bindings: Sequence[UriBinding],
    arelle_version: str,
    extractor_version: str = EXTRACTOR_VERSION,
    concept_declarations: Sequence[phase1.ConceptDeclarationRecord],
    concept_labels: Sequence[phase1.ConceptLabelRecord],
    concept_references: Sequence[phase1.ConceptReferenceRecord],
    contexts: Sequence[phase1.ContextRecord],
    context_dimensions: Sequence[phase1.ContextDimensionRecord],
    units: Sequence[phase1.UnitRecord],
    unit_measures: Sequence[phase1.UnitMeasureRecord],
    ordered_facts: Sequence[tuple[int, phase1.FactRecord]],
    relationships: Sequence[phase1.RelationshipRecord],
    issues: Sequence[SemanticIssueRecord],
) -> ReportExtraction:
    """Assemble native ``ReportExtraction`` with logical-path provenance."""
    uri_paths = uri_to_logical_path_map(uri_bindings)
    payload = report_input_payload(report_input)
    key = compute_report_key(report_input)
    context_ids = _context_id_by_locator(contexts)
    unit_ids = _unit_id_by_locator(units)
    facts = _build_facts(ordered_facts, context_ids, unit_ids, uri_paths)
    arelle_item_fact_count = len(facts)
    if arelle_item_fact_count != len(ordered_facts):
        raise SourceBuildError(
            "arelle_item_fact_count diverged from ordered fact count: "
            f"{arelle_item_fact_count} != {len(ordered_facts)}"
        )
    return ReportExtraction(
        report_input=payload,
        report_key=key,
        extractor_version=extractor_version,
        arelle_version=arelle_version,
        arelle_item_fact_count=arelle_item_fact_count,
        concepts=_build_concepts(concept_declarations),
        declarations=_build_declarations(concept_declarations, uri_paths),
        labels=_build_labels(concept_labels),
        references=_build_references(concept_references),
        contexts=_build_contexts(contexts, uri_paths),
        dimensions=_build_dimensions(context_dimensions, context_ids, uri_paths),
        units=_build_units(units, uri_paths),
        measures=_build_measures(unit_measures, unit_ids),
        facts=facts,
        relationships=_build_relationships(relationships, uri_paths),
        issues=_build_issues(issues, uri_paths),
    )
