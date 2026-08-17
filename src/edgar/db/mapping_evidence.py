"""Pinned source.* evidence resolution for mappings explain (Phase 2B).

Evidence pin identity is accession + expanded QName only. Resolution returns
one enrichment section per matching ``source.xbrl_report`` (never merges
reports or picks a single row arbitrarily). ``arelle_version`` is display
metadata on report payloads, not resolution identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from edgar.db import source_schema as src
from edgar.metrics.registry import SourceConceptEvidence


class MappingEvidenceError(RuntimeError):
    """Evidence could not be resolved against source.* tables."""


@dataclass(frozen=True)
class SourcePinnedConcept:
    filing_id: int
    accession_number: str
    report_period_end: date | None
    report_id: int
    report_key: str
    arelle_version: str
    extractor_version: str
    concept_declaration_id: int
    concept_id: UUID
    namespace_uri: str
    local_name: str


@dataclass(frozen=True)
class ReportExplainEnrichment:
    pinned: SourcePinnedConcept
    concept_declaration: dict[str, Any]
    labels: tuple[dict[str, Any], ...]
    references: tuple[dict[str, Any], ...]
    presentation_neighbors: tuple[dict[str, Any], ...]
    calculation_neighbors: tuple[dict[str, Any], ...]
    definition_neighbors: tuple[dict[str, Any], ...]
    fact_occurrences: tuple[dict[str, Any], ...]
    extraction_issues: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ExplainEnrichment:
    filing_id: int
    accession_number: str
    report_period_end: date | None
    reports: tuple[ReportExplainEnrichment, ...]


def _decimal_to_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _date_to_iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _datetime_to_iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _numeric_to_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return _decimal_to_str(value)
    return str(value)


def _qname_payload(namespace_uri: str | None, local_name: str | None) -> dict[str, str | None]:
    return {"namespace_uri": namespace_uri, "local_name": local_name}


def _load_concept_qnames(
    conn: Connection, concept_ids: Sequence[UUID]
) -> dict[UUID, dict[str, str]]:
    unique = sorted({UUID(str(i)) for i in concept_ids}, key=str)
    if not unique:
        return {}
    rows = conn.execute(
        select(
            src.source_concept.c.id,
            src.source_concept.c.namespace_uri,
            src.source_concept.c.local_name,
        ).where(src.source_concept.c.id.in_(unique))
    ).all()
    return {
        UUID(str(row.id)): {
            "namespace_uri": str(row.namespace_uri),
            "local_name": str(row.local_name),
        }
        for row in rows
    }


def resolve_source_concept_pins(
    conn: Connection,
    evidence: SourceConceptEvidence,
) -> tuple[SourcePinnedConcept, ...]:
    """Resolve pin to every matching report-local concept declaration."""
    filing_row = conn.execute(
        select(
            src.source_filing.c.id,
            src.source_filing.c.accession,
            src.source_filing.c.report_period_end,
        ).where(src.source_filing.c.accession == evidence.accession_number)
    ).one_or_none()
    if filing_row is None:
        raise MappingEvidenceError(f"no source.filing for accession {evidence.accession_number}")

    rows = conn.execute(
        select(
            src.source_xbrl_report.c.id,
            src.source_xbrl_report.c.report_key,
            src.source_xbrl_report.c.arelle_version,
            src.source_xbrl_report.c.extractor_version,
            src.source_concept_declaration.c.id,
            src.source_concept.c.id,
            src.source_concept.c.namespace_uri,
            src.source_concept.c.local_name,
        )
        .select_from(
            src.source_xbrl_report.join(
                src.source_concept_declaration,
                src.source_concept_declaration.c.report_id == src.source_xbrl_report.c.id,
            ).join(
                src.source_concept,
                src.source_concept.c.id == src.source_concept_declaration.c.concept_id,
            )
        )
        .where(src.source_xbrl_report.c.filing_id == int(filing_row.id))
        .where(src.source_concept.c.namespace_uri == evidence.concept.namespace_uri)
        .where(src.source_concept.c.local_name == evidence.concept.local_name)
        .order_by(src.source_xbrl_report.c.id, src.source_concept_declaration.c.id)
    ).all()

    if not rows:
        raise MappingEvidenceError(
            f"pinned concept not found in source.* for accession "
            f"{evidence.accession_number}: "
            f"{{{evidence.concept.namespace_uri}}}{evidence.concept.local_name}"
        )

    # Unique (report_id, concept_id) is enforced; still guard against surprises.
    by_report: dict[int, Any] = {}
    for row in rows:
        report_id = int(row[0])
        if report_id in by_report:
            raise MappingEvidenceError(
                f"duplicate concept declaration for report_id={report_id} "
                f"accession={evidence.accession_number}"
            )
        by_report[report_id] = row

    pins: list[SourcePinnedConcept] = []
    for report_id in sorted(by_report):
        row = by_report[report_id]
        pins.append(
            SourcePinnedConcept(
                filing_id=int(filing_row.id),
                accession_number=str(filing_row.accession),
                report_period_end=filing_row.report_period_end,
                report_id=int(row[0]),
                report_key=str(row[1]),
                arelle_version=str(row[2]),
                extractor_version=str(row[3]),
                concept_declaration_id=int(row[4]),
                concept_id=UUID(str(row[5])),
                namespace_uri=str(row[6]),
                local_name=str(row[7]),
            )
        )
    return tuple(pins)


def _relationship_neighbors(
    conn: Connection,
    *,
    report_id: int,
    concept_id: UUID,
    network_type: str,
    qnames: Mapping[UUID, dict[str, str]],
) -> tuple[dict[str, Any], ...]:
    rows = conn.execute(
        select(
            src.source_relationship.c.id,
            src.source_relationship.c.network_type,
            src.source_relationship.c.link_role_uri,
            src.source_relationship.c.arcrole_uri,
            src.source_relationship.c.source_concept_id,
            src.source_relationship.c.target_concept_id,
            src.source_relationship.c.order_value,
            src.source_relationship.c.weight,
            src.source_relationship.c.preferred_label,
            src.source_relationship.c.target_role,
            src.source_relationship.c.attributes,
        )
        .where(src.source_relationship.c.report_id == report_id)
        .where(src.source_relationship.c.network_type == network_type)
        .where(
            (src.source_relationship.c.source_concept_id == concept_id)
            | (src.source_relationship.c.target_concept_id == concept_id)
        )
    ).all()

    cleaned: list[dict[str, Any]] = []
    for row in rows:
        source_q = qnames.get(UUID(str(row.source_concept_id)), {})
        target_q = qnames.get(UUID(str(row.target_concept_id)), {})
        cleaned.append(
            {
                "network_type": row.network_type,
                "link_role_uri": row.link_role_uri,
                "arcrole_uri": row.arcrole_uri,
                "source_concept": _qname_payload(
                    source_q.get("namespace_uri"), source_q.get("local_name")
                ),
                "target_concept": _qname_payload(
                    target_q.get("namespace_uri"), target_q.get("local_name")
                ),
                "order_value": _numeric_to_str(row.order_value),
                "weight": _numeric_to_str(row.weight),
                "preferred_label": row.preferred_label,
                "target_role": row.target_role,
                "attributes": row.attributes,
                "_sort_id": int(row.id),
            }
        )
    cleaned.sort(
        key=lambda item: (
            item["link_role_uri"] or "",
            item["arcrole_uri"] or "",
            item["source_concept"]["namespace_uri"] or "",
            item["source_concept"]["local_name"] or "",
            item["target_concept"]["namespace_uri"] or "",
            item["target_concept"]["local_name"] or "",
            item["order_value"] or "",
            item["_sort_id"],
        )
    )
    for item in cleaned:
        del item["_sort_id"]
    return tuple(cleaned)


def enrich_report_pin(
    conn: Connection,
    pinned: SourcePinnedConcept,
) -> ReportExplainEnrichment:
    declaration_row = conn.execute(
        select(
            src.source_concept.c.namespace_uri,
            src.source_concept.c.local_name,
            src.source_concept_declaration.c.data_type,
            src.source_concept_declaration.c.substitution_group,
            src.source_concept_declaration.c.period_type,
            src.source_concept_declaration.c.balance,
            src.source_concept_declaration.c.abstract,
            src.source_concept_declaration.c.nillable,
        )
        .select_from(
            src.source_concept_declaration.join(
                src.source_concept,
                src.source_concept.c.id == src.source_concept_declaration.c.concept_id,
            )
        )
        .where(src.source_concept_declaration.c.id == pinned.concept_declaration_id)
    ).one()

    label_rows = conn.execute(
        select(
            src.source_concept_label.c.id,
            src.source_concept_label.c.link_role_uri,
            src.source_concept_label.c.arcrole_uri,
            src.source_concept_label.c.resource_role_uri,
            src.source_concept_label.c.language,
            src.source_concept_label.c.text,
            src.source_concept_label.c.order_value,
            src.source_concept_label.c.source_order,
        )
        .where(src.source_concept_label.c.report_id == pinned.report_id)
        .where(src.source_concept_label.c.concept_id == pinned.concept_id)
    ).all()

    reference_rows = conn.execute(
        select(
            src.source_concept_reference.c.id,
            src.source_concept_reference.c.link_role_uri,
            src.source_concept_reference.c.arcrole_uri,
            src.source_concept_reference.c.resource_role_uri,
            src.source_concept_reference.c.source_order,
            src.source_concept_reference.c.reference_parts,
        )
        .where(src.source_concept_reference.c.report_id == pinned.report_id)
        .where(src.source_concept_reference.c.concept_id == pinned.concept_id)
    ).all()

    fact_rows = conn.execute(
        select(
            src.source_fact.c.id,
            src.source_fact.c.source_order,
            src.source_fact.c.context_id,
            src.source_fact.c.unit_id,
            src.source_fact.c.value_status,
            src.source_fact.c.raw_lexical_value,
            src.source_fact.c.resolved_value_kind,
            src.source_fact.c.resolved_text,
            src.source_fact.c.resolved_numeric,
            src.source_fact.c.is_nil,
            src.source_fact.c.decimals,
            src.source_fact.c.precision,
            src.source_fact.c.scale,
            src.source_fact.c.sign,
            src.source_fact.c.format_namespace_uri,
            src.source_fact.c.format_local_name,
            src.source_fact.c.source_document_id,
            src.source_fact.c.source_locator,
        )
        .where(src.source_fact.c.report_id == pinned.report_id)
        .where(src.source_fact.c.concept_id == pinned.concept_id)
    ).all()

    issue_rows = conn.execute(
        select(
            src.source_extraction_issue.c.id,
            src.source_extraction_issue.c.component,
            src.source_extraction_issue.c.code,
            src.source_extraction_issue.c.severity,
            src.source_extraction_issue.c.message,
            src.source_extraction_issue.c.details,
        )
        .where(src.source_extraction_issue.c.report_id == pinned.report_id)
        .order_by(
            src.source_extraction_issue.c.severity,
            src.source_extraction_issue.c.code,
            src.source_extraction_issue.c.id,
        )
    ).all()

    context_ids = sorted({int(r.context_id) for r in fact_rows})
    unit_ids = sorted({int(r.unit_id) for r in fact_rows if r.unit_id is not None})
    document_ids = sorted(
        {int(r.source_document_id) for r in fact_rows if r.source_document_id is not None}
    )

    related_concept_ids: set[UUID] = {pinned.concept_id}
    rel_probe = conn.execute(
        select(
            src.source_relationship.c.source_concept_id,
            src.source_relationship.c.target_concept_id,
        )
        .where(src.source_relationship.c.report_id == pinned.report_id)
        .where(
            (src.source_relationship.c.source_concept_id == pinned.concept_id)
            | (src.source_relationship.c.target_concept_id == pinned.concept_id)
        )
    ).all()
    for row in rel_probe:
        related_concept_ids.add(UUID(str(row.source_concept_id)))
        related_concept_ids.add(UUID(str(row.target_concept_id)))

    contexts_by_id: dict[int, Any] = {}
    if context_ids:
        context_rows = conn.execute(
            select(
                src.source_context.c.id,
                src.source_context.c.source_context_id,
                src.source_context.c.entity_scheme,
                src.source_context.c.entity_identifier,
                src.source_context.c.period_kind,
                src.source_context.c.instant_lexical,
                src.source_context.c.start_lexical,
                src.source_context.c.end_lexical,
                src.source_context.c.instant_at,
                src.source_context.c.start_at,
                src.source_context.c.end_at,
            ).where(src.source_context.c.id.in_(context_ids))
        ).all()
        for row in context_rows:
            contexts_by_id[int(row.id)] = row

    dim_axis = src.source_concept.alias("dim_axis")
    dim_member = src.source_concept.alias("dim_member")
    dimensions_by_context: dict[int, list[Any]] = {cid: [] for cid in context_ids}
    if context_ids:
        dim_rows = conn.execute(
            select(
                src.source_context_dimension.c.id,
                src.source_context_dimension.c.context_id,
                src.source_context_dimension.c.context_element,
                src.source_context_dimension.c.member_kind,
                dim_axis.c.namespace_uri,
                dim_axis.c.local_name,
                dim_member.c.namespace_uri,
                dim_member.c.local_name,
                src.source_context_dimension.c.typed_member,
            )
            .select_from(
                src.source_context_dimension.join(
                    dim_axis,
                    dim_axis.c.id == src.source_context_dimension.c.dimension_concept_id,
                ).outerjoin(
                    dim_member,
                    dim_member.c.id == src.source_context_dimension.c.explicit_member_concept_id,
                )
            )
            .where(src.source_context_dimension.c.context_id.in_(context_ids))
        ).all()
        for row in dim_rows:
            dimensions_by_context[int(row.context_id)].append(row)

    units_by_id: dict[int, Any] = {}
    measures_by_unit: dict[int, list[Any]] = {uid: [] for uid in unit_ids}
    if unit_ids:
        unit_rows = conn.execute(
            select(src.source_unit.c.id, src.source_unit.c.source_unit_id).where(
                src.source_unit.c.id.in_(unit_ids)
            )
        ).all()
        for row in unit_rows:
            units_by_id[int(row.id)] = row
        measure_rows = conn.execute(
            select(
                src.source_unit_measure.c.unit_id,
                src.source_unit_measure.c.side,
                src.source_unit_measure.c.ordinal,
                src.source_unit_measure.c.measure_namespace_uri,
                src.source_unit_measure.c.measure_local_name,
            )
            .where(src.source_unit_measure.c.unit_id.in_(unit_ids))
            .order_by(
                src.source_unit_measure.c.unit_id,
                src.source_unit_measure.c.side,
                src.source_unit_measure.c.ordinal,
            )
        ).all()
        for row in measure_rows:
            measures_by_unit[int(row.unit_id)].append(row)

    documents_by_id: dict[int, dict[str, Any]] = {}
    if document_ids:
        doc_rows = conn.execute(
            select(
                src.source_document.c.id,
                src.source_document.c.relative_path,
                src.source_document.c.sha256,
                src.source_document.c.source_url,
            ).where(src.source_document.c.id.in_(document_ids))
        ).all()
        for row in doc_rows:
            documents_by_id[int(row.id)] = {
                "relative_path": row.relative_path,
                "sha256": row.sha256,
                "source_url": row.source_url,
            }

    qnames = _load_concept_qnames(conn, list(related_concept_ids))

    concept_declaration = {
        "qname": _qname_payload(declaration_row.namespace_uri, declaration_row.local_name),
        "data_type": declaration_row.data_type,
        "substitution_group": declaration_row.substitution_group,
        "period_type": declaration_row.period_type,
        "balance": declaration_row.balance,
        "abstract": declaration_row.abstract,
        "nillable": declaration_row.nillable,
    }

    labels = [
        {
            "link_role_uri": row.link_role_uri,
            "arcrole_uri": row.arcrole_uri,
            "resource_role_uri": row.resource_role_uri,
            "language": row.language,
            "text": row.text,
            "order_value": _numeric_to_str(row.order_value),
            "source_order": row.source_order,
            "_sort_id": int(row.id),
        }
        for row in label_rows
    ]
    labels.sort(
        key=lambda item: (
            item["link_role_uri"] or "",
            item["resource_role_uri"] or "",
            item["language"] or "",
            item["source_order"] if item["source_order"] is not None else -1,
            item["_sort_id"],
        )
    )
    for item in labels:
        del item["_sort_id"]

    references = [
        {
            "link_role_uri": row.link_role_uri,
            "arcrole_uri": row.arcrole_uri,
            "resource_role_uri": row.resource_role_uri,
            "source_order": row.source_order,
            "reference_parts": row.reference_parts,
            "_sort_id": int(row.id),
        }
        for row in reference_rows
    ]
    references.sort(
        key=lambda item: (
            item["link_role_uri"] or "",
            item["resource_role_uri"] or "",
            item["source_order"],
            item["_sort_id"],
        )
    )
    for item in references:
        del item["_sort_id"]

    def _dimension_payload(row: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "axis": _qname_payload(row[4], row[5]),
            "context_element": row.context_element,
            "member_kind": row.member_kind,
        }
        if row.member_kind == "explicit":
            payload["member"] = _qname_payload(row[6], row[7])
            payload["typed_member"] = None
        else:
            payload["member"] = None
            payload["typed_member"] = row.typed_member
        return payload

    def _context_payload(context_id: int) -> dict[str, Any]:
        row = contexts_by_id[context_id]
        dims = dimensions_by_context.get(context_id, [])
        dim_payloads = [_dimension_payload(d) for d in dims]
        dim_payloads.sort(
            key=lambda item: (
                item["axis"]["namespace_uri"] or "",
                item["axis"]["local_name"] or "",
                item["context_element"] or "",
                item["member_kind"] or "",
                (item["member"] or {}).get("local_name") or "",
                str(item["typed_member"] or ""),
            )
        )
        return {
            "source_context_id": row.source_context_id,
            "entity_scheme": row.entity_scheme,
            "entity_identifier": row.entity_identifier,
            "period_kind": row.period_kind,
            "instant_lexical": row.instant_lexical,
            "start_lexical": row.start_lexical,
            "end_lexical": row.end_lexical,
            "instant_at": _datetime_to_iso(row.instant_at),
            "start_at": _datetime_to_iso(row.start_at),
            "end_at": _datetime_to_iso(row.end_at),
            "dimensions": dim_payloads,
        }

    def _unit_payload(unit_id: int | None) -> dict[str, Any] | None:
        if unit_id is None:
            return None
        row = units_by_id[unit_id]
        measures = measures_by_unit.get(unit_id, [])
        numerator = [
            _qname_payload(m.measure_namespace_uri, m.measure_local_name)
            for m in measures
            if m.side == "numerator"
        ]
        denominator = [
            _qname_payload(m.measure_namespace_uri, m.measure_local_name)
            for m in measures
            if m.side == "denominator"
        ]
        return {
            "source_unit_id": row.source_unit_id,
            "numerator_measures": numerator,
            "denominator_measures": denominator,
        }

    def _fact_source(row: Any) -> dict[str, Any]:
        doc = (
            documents_by_id.get(int(row.source_document_id))
            if row.source_document_id is not None
            else None
        )
        return {
            "relative_path": None if doc is None else doc["relative_path"],
            "sha256": None if doc is None else doc["sha256"],
            "source_url": None if doc is None else doc["source_url"],
            "locator": row.source_locator,
        }

    fact_payloads = [
        {
            "fact_id": int(row.id),
            "source_order": int(row.source_order),
            "value_status": row.value_status,
            "raw_lexical_value": row.raw_lexical_value,
            "resolved_value_kind": row.resolved_value_kind,
            "resolved_value_text": row.resolved_text,
            "resolved_numeric": _numeric_to_str(row.resolved_numeric),
            "is_nil": row.is_nil,
            "reported_decimals": row.decimals,
            "reported_precision": row.precision,
            "scale": row.scale,
            "sign": row.sign,
            "format": (
                None
                if row.format_namespace_uri is None and row.format_local_name is None
                else _qname_payload(row.format_namespace_uri, row.format_local_name)
            ),
            "context": _context_payload(int(row.context_id)),
            "unit": _unit_payload(int(row.unit_id) if row.unit_id is not None else None),
            "source": _fact_source(row),
        }
        for row in fact_rows
    ]
    fact_payloads.sort(
        key=lambda item: (
            item["source_order"],
            item["context"]["source_context_id"] or "",
            (item["unit"] or {}).get("source_unit_id") or "",
            item["raw_lexical_value"] or "",
            item["fact_id"],
        )
    )

    extraction_issues = [
        {
            "component": row.component,
            "severity": row.severity,
            "code": row.code,
            "message": row.message,
            "details": dict(row.details),
        }
        for row in issue_rows
    ]

    return ReportExplainEnrichment(
        pinned=pinned,
        concept_declaration=concept_declaration,
        labels=tuple(labels),
        references=tuple(references),
        presentation_neighbors=_relationship_neighbors(
            conn,
            report_id=pinned.report_id,
            concept_id=pinned.concept_id,
            network_type="presentation",
            qnames=qnames,
        ),
        calculation_neighbors=_relationship_neighbors(
            conn,
            report_id=pinned.report_id,
            concept_id=pinned.concept_id,
            network_type="calculation",
            qnames=qnames,
        ),
        definition_neighbors=_relationship_neighbors(
            conn,
            report_id=pinned.report_id,
            concept_id=pinned.concept_id,
            network_type="definition",
            qnames=qnames,
        ),
        fact_occurrences=tuple(fact_payloads),
        extraction_issues=tuple(extraction_issues),
    )


def enrich_pinned_evidence(
    conn: Connection,
    pins: Sequence[SourcePinnedConcept],
) -> ExplainEnrichment:
    if not pins:
        raise MappingEvidenceError("no pinned reports to enrich")
    reports = tuple(enrich_report_pin(conn, pin) for pin in pins)
    first = pins[0]
    return ExplainEnrichment(
        filing_id=first.filing_id,
        accession_number=first.accession_number,
        report_period_end=first.report_period_end,
        reports=reports,
    )


def enrichment_to_payload(enrichment: ExplainEnrichment) -> dict[str, Any]:
    report_payloads: list[dict[str, Any]] = []
    for report in enrichment.reports:
        pinned = report.pinned
        report_payloads.append(
            {
                "report_id": pinned.report_id,
                "report_key": pinned.report_key,
                "arelle_version": pinned.arelle_version,
                "extractor_version": pinned.extractor_version,
                "concept_declaration_id": pinned.concept_declaration_id,
                "concept_id": str(pinned.concept_id),
                "concept_declaration": report.concept_declaration,
                "labels": list(report.labels),
                "references": list(report.references),
                "presentation_neighbors": list(report.presentation_neighbors),
                "calculation_neighbors": list(report.calculation_neighbors),
                "definition_neighbors": list(report.definition_neighbors),
                "fact_occurrences": list(report.fact_occurrences),
                "extraction_issues": list(report.extraction_issues),
            }
        )
    return {
        "filing_id": enrichment.filing_id,
        "filing": {
            "accession_number": enrichment.accession_number,
            "report_period_end": _date_to_iso(enrichment.report_period_end),
        },
        "report_count": len(report_payloads),
        "reports": report_payloads,
    }
