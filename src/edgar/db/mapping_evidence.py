"""Pinned projection evidence resolution for mappings explain (Phase 2A)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, select

from edgar.db import schema as tables
from edgar.db.catalog import load_bundle
from edgar.domain.bundle import bundle_fingerprint
from edgar.metrics.registry import ProjectionConceptEvidence

_REPORT_INPUT_ORDINAL_V1 = 0


class MappingEvidenceError(RuntimeError):
    """Evidence could not be resolved to exactly one pinned projection object."""


@dataclass(frozen=True)
class PinnedConceptEvidence:
    bundle_id: int
    semantic_projection_id: int
    concept_declaration_id: int
    concept_identity_id: int
    namespace_uri: str
    local_name: str
    accession_number: str
    report_period_end: date | None
    report_input_ordinal: int
    projection_version: str
    arelle_version: str
    semantic_config_fingerprint: str
    semantic_config: dict[str, Any]
    projection_status: str


@dataclass(frozen=True)
class ExplainEnrichment:
    pinned: PinnedConceptEvidence
    concept_declaration: dict[str, Any]
    labels: tuple[dict[str, Any], ...]
    references: tuple[dict[str, Any], ...]
    presentation_neighbors: tuple[dict[str, Any], ...]
    calculation_neighbors: tuple[dict[str, Any], ...]
    definition_neighbors: tuple[dict[str, Any], ...]
    fact_occurrences: tuple[dict[str, Any], ...]
    semantic_issues: tuple[dict[str, Any], ...]


def _decimal_to_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _date_to_iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _numeric_to_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return _decimal_to_str(value)
    return str(value)


def _qname_payload(namespace_uri: str | None, local_name: str | None) -> dict[str, str | None]:
    return {"namespace_uri": namespace_uri, "local_name": local_name}


def _source_payload(
    *,
    document_uri: str | None,
    artifact_path: str | None,
    content_sha256: str | None,
    locator_scheme: str | None,
    locator_value: Any,
) -> dict[str, Any]:
    return {
        "document_uri": document_uri,
        "artifact_path": artifact_path,
        "content_sha256": content_sha256,
        "locator_scheme": locator_scheme,
        "locator_value": locator_value,
    }


def _load_source_bindings(
    conn: Connection, binding_ids: Sequence[int]
) -> dict[int, dict[str, str]]:
    unique_ids = sorted({int(i) for i in binding_ids if i is not None})
    if not unique_ids:
        return {}
    rows = conn.execute(
        select(
            tables.bundle_uri_binding.c.id,
            tables.bundle_uri_binding.c.document_uri,
            tables.bundle_artifact.c.logical_path,
            tables.content_object.c.sha256,
        )
        .select_from(
            tables.bundle_uri_binding.join(
                tables.bundle_artifact,
                tables.bundle_artifact.c.id == tables.bundle_uri_binding.c.bundle_artifact_id,
            ).join(
                tables.content_object,
                tables.content_object.c.id == tables.bundle_artifact.c.content_object_id,
            )
        )
        .where(tables.bundle_uri_binding.c.id.in_(unique_ids))
    ).all()
    return {
        int(row.id): {
            "document_uri": str(row.document_uri),
            "artifact_path": str(row.logical_path),
            "content_sha256": str(row.sha256),
        }
        for row in rows
    }


def _source_from_binding(
    bindings: Mapping[int, dict[str, str]],
    binding_id: int | None,
    *,
    locator_scheme: str | None,
    locator_value: Any,
) -> dict[str, Any]:
    meta = bindings.get(int(binding_id)) if binding_id is not None else None
    if meta is None:
        return _source_payload(
            document_uri=None,
            artifact_path=None,
            content_sha256=None,
            locator_scheme=locator_scheme,
            locator_value=locator_value,
        )
    return _source_payload(
        document_uri=meta["document_uri"],
        artifact_path=meta["artifact_path"],
        content_sha256=meta["content_sha256"],
        locator_scheme=locator_scheme,
        locator_value=locator_value,
    )


def _fingerprint_matching_bundle_ids(
    conn: Connection,
    *,
    accession: str,
    fingerprint: str,
) -> list[int]:
    rows = (
        conn.execute(
            select(tables.filing_bundle.c.id)
            .select_from(
                tables.filing_bundle.join(
                    tables.filing, tables.filing.c.id == tables.filing_bundle.c.filing_id
                )
            )
            .where(tables.filing.c.accession_number == accession)
            .order_by(tables.filing_bundle.c.id)
        )
        .scalars()
        .all()
    )
    if not rows:
        raise MappingEvidenceError(f"no cataloged bundles for accession {accession}")

    matches: list[int] = []
    for bundle_id in rows:
        loaded = load_bundle(conn, int(bundle_id))
        if bundle_fingerprint(loaded) == fingerprint:
            matches.append(int(bundle_id))
    if not matches:
        raise MappingEvidenceError(
            f"bundle_fingerprint {fingerprint}: expected at least one match, got 0"
        )
    return matches


@dataclass(frozen=True)
class _ProjectionMatch:
    bundle_id: int
    projection_id: int
    status: str
    projection_version: str
    arelle_version: str
    semantic_config_fingerprint: str
    semantic_config: dict[str, Any]
    report_input_ordinal: int
    accession_number: str
    report_period_end: date | None


def _matching_ordinal0_projections(
    conn: Connection,
    *,
    bundle_ids: Sequence[int],
    projection_version: str,
    arelle_version: str,
    semantic_config_fingerprint: str,
) -> list[_ProjectionMatch]:
    rows = conn.execute(
        select(
            tables.filing_bundle.c.id,
            tables.semantic_projection.c.id,
            tables.semantic_projection.c.status,
            tables.semantic_projection.c.projection_version,
            tables.semantic_projection.c.arelle_version,
            tables.semantic_projection.c.semantic_config_fingerprint,
            tables.semantic_projection.c.semantic_config,
            tables.xbrl_report_input.c.ordinal,
            tables.filing.c.accession_number,
            tables.filing.c.report_period_end,
        )
        .select_from(
            tables.filing_bundle.join(
                tables.filing, tables.filing.c.id == tables.filing_bundle.c.filing_id
            )
            .join(
                tables.xbrl_report_input,
                tables.xbrl_report_input.c.filing_bundle_id == tables.filing_bundle.c.id,
            )
            .join(
                tables.semantic_projection,
                tables.semantic_projection.c.xbrl_report_input_id == tables.xbrl_report_input.c.id,
            )
        )
        .where(tables.filing_bundle.c.id.in_(list(bundle_ids)))
        .where(tables.xbrl_report_input.c.ordinal == _REPORT_INPUT_ORDINAL_V1)
        .where(tables.semantic_projection.c.projection_version == projection_version)
        .where(tables.semantic_projection.c.arelle_version == arelle_version)
        .where(
            tables.semantic_projection.c.semantic_config_fingerprint == semantic_config_fingerprint
        )
        .order_by(tables.filing_bundle.c.id, tables.semantic_projection.c.id)
    ).all()
    return [
        _ProjectionMatch(
            bundle_id=int(row[0]),
            projection_id=int(row[1]),
            status=str(row[2]),
            projection_version=str(row[3]),
            arelle_version=str(row[4]),
            semantic_config_fingerprint=str(row[5]),
            semantic_config=dict(row[6]),
            report_input_ordinal=int(row[7]),
            accession_number=str(row[8]),
            report_period_end=row[9],
        )
        for row in rows
    ]


def _find_concept_declaration(
    conn: Connection,
    *,
    projection_id: int,
    namespace_uri: str,
    local_name: str,
) -> tuple[int, int, str, str] | None:
    rows = conn.execute(
        select(
            tables.concept_declaration.c.id,
            tables.concept_identity.c.id,
            tables.concept_identity.c.namespace_uri,
            tables.concept_identity.c.local_name,
        )
        .select_from(
            tables.concept_declaration.join(
                tables.concept_identity,
                tables.concept_identity.c.id == tables.concept_declaration.c.concept_identity_id,
            )
        )
        .where(tables.concept_declaration.c.semantic_projection_id == projection_id)
        .where(tables.concept_identity.c.namespace_uri == namespace_uri)
        .where(tables.concept_identity.c.local_name == local_name)
    ).all()
    if not rows:
        return None
    if len(rows) != 1:
        raise MappingEvidenceError(
            f"concept declaration: expected exactly one match, got {len(rows)}"
        )
    cd_id, ci_id, ns, local = rows[0]
    return int(cd_id), int(ci_id), str(ns), str(local)


def resolve_pinned_concept(
    conn: Connection,
    evidence: ProjectionConceptEvidence,
) -> PinnedConceptEvidence:
    if evidence.concept.namespace_uri is None:
        raise MappingEvidenceError("evidence concept requires namespace_uri")

    bundle_ids = _fingerprint_matching_bundle_ids(
        conn,
        accession=evidence.accession_number,
        fingerprint=evidence.bundle_fingerprint,
    )
    projection_matches = _matching_ordinal0_projections(
        conn,
        bundle_ids=bundle_ids,
        projection_version=evidence.projection_version,
        arelle_version=evidence.arelle_version,
        semantic_config_fingerprint=evidence.semantic_config_fingerprint,
    )
    complete = [m for m in projection_matches if m.status == "complete"]
    incomplete = [m for m in projection_matches if m.status == "incomplete"]

    complete_with_concept: list[tuple[_ProjectionMatch, tuple[int, int, str, str]]] = []
    for match in complete:
        concept = _find_concept_declaration(
            conn,
            projection_id=match.projection_id,
            namespace_uri=evidence.concept.namespace_uri,
            local_name=evidence.concept.local_name,
        )
        if concept is not None:
            complete_with_concept.append((match, concept))

    if complete_with_concept:
        complete_with_concept.sort(key=lambda item: (item[0].bundle_id, item[0].projection_id))
        chosen, (cd_id, ci_id, ns, local) = complete_with_concept[0]
        return PinnedConceptEvidence(
            bundle_id=chosen.bundle_id,
            semantic_projection_id=chosen.projection_id,
            concept_declaration_id=cd_id,
            concept_identity_id=ci_id,
            namespace_uri=ns,
            local_name=local,
            accession_number=chosen.accession_number,
            report_period_end=chosen.report_period_end,
            report_input_ordinal=chosen.report_input_ordinal,
            projection_version=chosen.projection_version,
            arelle_version=chosen.arelle_version,
            semantic_config_fingerprint=chosen.semantic_config_fingerprint,
            semantic_config=chosen.semantic_config,
            projection_status=chosen.status,
        )

    if incomplete:
        raise MappingEvidenceError("pinned semantic projection is incomplete")

    raise MappingEvidenceError("pinned projection/concept not found")


def _relationship_neighbors(
    conn: Connection,
    *,
    projection_id: int,
    concept_declaration_id: int,
    network_type: str,
    bindings: Mapping[int, dict[str, str]],
) -> tuple[dict[str, Any], ...]:
    source_cd = tables.concept_declaration.alias("source_cd")
    target_cd = tables.concept_declaration.alias("target_cd")
    source_ci = tables.concept_identity.alias("source_ci")
    target_ci = tables.concept_identity.alias("target_ci")
    rows = conn.execute(
        select(
            tables.xbrl_relationship.c.id,
            tables.xbrl_relationship.c.network_type,
            tables.xbrl_relationship.c.link_role_uri,
            tables.xbrl_relationship.c.arcrole_uri,
            source_ci.c.namespace_uri,
            source_ci.c.local_name,
            target_ci.c.namespace_uri,
            target_ci.c.local_name,
            tables.xbrl_relationship.c.order_value,
            tables.xbrl_relationship.c.weight,
            tables.xbrl_relationship.c.preferred_label_role,
            tables.xbrl_relationship.c.target_role_uri,
            tables.xbrl_relationship.c.closed,
            tables.xbrl_relationship.c.usable,
            tables.xbrl_relationship.c.context_element,
            tables.xbrl_relationship.c.source_bundle_uri_binding_id,
            tables.xbrl_relationship.c.source_locator_scheme,
            tables.xbrl_relationship.c.source_locator_value,
        )
        .select_from(
            tables.xbrl_relationship.join(
                source_cd,
                source_cd.c.id == tables.xbrl_relationship.c.source_concept_declaration_id,
            )
            .join(source_ci, source_ci.c.id == source_cd.c.concept_identity_id)
            .join(
                target_cd,
                target_cd.c.id == tables.xbrl_relationship.c.target_concept_declaration_id,
            )
            .join(target_ci, target_ci.c.id == target_cd.c.concept_identity_id)
        )
        .where(tables.xbrl_relationship.c.semantic_projection_id == projection_id)
        .where(tables.xbrl_relationship.c.network_type == network_type)
        .where(
            (tables.xbrl_relationship.c.source_concept_declaration_id == concept_declaration_id)
            | (tables.xbrl_relationship.c.target_concept_declaration_id == concept_declaration_id)
        )
    ).all()
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        cleaned.append(
            {
                "network_type": row.network_type,
                "link_role_uri": row.link_role_uri,
                "arcrole_uri": row.arcrole_uri,
                "source_concept": _qname_payload(row[4], row[5]),
                "target_concept": _qname_payload(row[6], row[7]),
                "order_value": _numeric_to_str(row.order_value),
                "weight": _numeric_to_str(row.weight),
                "preferred_label_role": row.preferred_label_role,
                "target_role_uri": row.target_role_uri,
                "closed": row.closed,
                "usable": row.usable,
                "context_element": row.context_element,
                "source": _source_from_binding(
                    bindings,
                    row.source_bundle_uri_binding_id,
                    locator_scheme=row.source_locator_scheme,
                    locator_value=row.source_locator_value,
                ),
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


def enrich_pinned_evidence(
    conn: Connection,
    pinned: PinnedConceptEvidence,
) -> ExplainEnrichment:
    declaration_row = conn.execute(
        select(
            tables.concept_identity.c.namespace_uri,
            tables.concept_identity.c.local_name,
            tables.concept_declaration.c.type_namespace_uri,
            tables.concept_declaration.c.type_local_name,
            tables.concept_declaration.c.substitution_group_namespace_uri,
            tables.concept_declaration.c.substitution_group_local_name,
            tables.concept_declaration.c.period_type,
            tables.concept_declaration.c.balance,
            tables.concept_declaration.c.is_abstract,
            tables.concept_declaration.c.is_nillable,
            tables.concept_declaration.c.source_bundle_uri_binding_id,
            tables.concept_declaration.c.source_locator_scheme,
            tables.concept_declaration.c.source_locator_value,
        )
        .select_from(
            tables.concept_declaration.join(
                tables.concept_identity,
                tables.concept_identity.c.id == tables.concept_declaration.c.concept_identity_id,
            )
        )
        .where(tables.concept_declaration.c.id == pinned.concept_declaration_id)
    ).one()

    label_rows = conn.execute(
        select(
            tables.concept_label.c.id,
            tables.concept_label.c.link_role_uri,
            tables.concept_label.c.arcrole_uri,
            tables.concept_label.c.resource_role_uri,
            tables.concept_label.c.language,
            tables.concept_label.c.text,
            tables.concept_label.c.order_value,
            tables.concept_label.c.resource_source_bundle_uri_binding_id,
            tables.concept_label.c.resource_source_locator_scheme,
            tables.concept_label.c.resource_source_locator_value,
            tables.concept_label.c.arc_source_bundle_uri_binding_id,
            tables.concept_label.c.arc_source_locator_scheme,
            tables.concept_label.c.arc_source_locator_value,
        ).where(tables.concept_label.c.concept_declaration_id == pinned.concept_declaration_id)
    ).all()

    reference_rows = conn.execute(
        select(
            tables.concept_reference.c.id,
            tables.concept_reference.c.link_role_uri,
            tables.concept_reference.c.arcrole_uri,
            tables.concept_reference.c.resource_role_uri,
            tables.concept_reference.c.reference_parts,
            tables.concept_reference.c.order_value,
            tables.concept_reference.c.resource_source_bundle_uri_binding_id,
            tables.concept_reference.c.resource_source_locator_scheme,
            tables.concept_reference.c.resource_source_locator_value,
            tables.concept_reference.c.arc_source_bundle_uri_binding_id,
            tables.concept_reference.c.arc_source_locator_scheme,
            tables.concept_reference.c.arc_source_locator_value,
        ).where(tables.concept_reference.c.concept_declaration_id == pinned.concept_declaration_id)
    ).all()

    fact_rows = conn.execute(
        select(
            tables.xbrl_fact.c.id,
            tables.xbrl_fact.c.context_id,
            tables.xbrl_fact.c.unit_id,
            tables.xbrl_fact.c.value_status,
            tables.xbrl_fact.c.raw_lexical_value,
            tables.xbrl_fact.c.resolved_value_kind,
            tables.xbrl_fact.c.resolved_value_text,
            tables.xbrl_fact.c.resolved_numeric,
            tables.xbrl_fact.c.is_nil,
            tables.xbrl_fact.c.reported_decimals,
            tables.xbrl_fact.c.reported_precision,
            tables.xbrl_fact.c.scale,
            tables.xbrl_fact.c.sign,
            tables.xbrl_fact.c.format_namespace_uri,
            tables.xbrl_fact.c.format_local_name,
            tables.xbrl_fact.c.source_bundle_uri_binding_id,
            tables.xbrl_fact.c.source_locator_scheme,
            tables.xbrl_fact.c.source_locator_value,
        )
        .where(tables.xbrl_fact.c.semantic_projection_id == pinned.semantic_projection_id)
        .where(tables.xbrl_fact.c.concept_declaration_id == pinned.concept_declaration_id)
    ).all()

    issue_rows = conn.execute(
        select(
            tables.semantic_issue.c.id,
            tables.semantic_issue.c.kind,
            tables.semantic_issue.c.severity,
            tables.semantic_issue.c.code,
            tables.semantic_issue.c.message,
            tables.semantic_issue.c.context,
        )
        .where(tables.semantic_issue.c.semantic_projection_id == pinned.semantic_projection_id)
        .order_by(
            tables.semantic_issue.c.severity,
            tables.semantic_issue.c.code,
            tables.semantic_issue.c.id,
        )
    ).all()

    context_ids = sorted({int(r.context_id) for r in fact_rows})
    unit_ids = sorted({int(r.unit_id) for r in fact_rows if r.unit_id is not None})

    binding_ids: list[int] = [int(declaration_row.source_bundle_uri_binding_id)]
    for row in label_rows:
        binding_ids.append(int(row.resource_source_bundle_uri_binding_id))
        binding_ids.append(int(row.arc_source_bundle_uri_binding_id))
    for row in reference_rows:
        binding_ids.append(int(row.resource_source_bundle_uri_binding_id))
        binding_ids.append(int(row.arc_source_bundle_uri_binding_id))
    for row in fact_rows:
        binding_ids.append(int(row.source_bundle_uri_binding_id))

    contexts_by_id: dict[int, Any] = {}
    if context_ids:
        context_rows = conn.execute(
            select(
                tables.xbrl_context.c.id,
                tables.xbrl_context.c.source_context_id,
                tables.xbrl_context.c.entity_scheme,
                tables.xbrl_context.c.entity_identifier,
                tables.xbrl_context.c.period_kind,
                tables.xbrl_context.c.instant_date,
                tables.xbrl_context.c.start_date,
                tables.xbrl_context.c.end_date,
                tables.xbrl_context.c.source_bundle_uri_binding_id,
                tables.xbrl_context.c.source_locator_scheme,
                tables.xbrl_context.c.source_locator_value,
            ).where(tables.xbrl_context.c.id.in_(context_ids))
        ).all()
        for row in context_rows:
            contexts_by_id[int(row.id)] = row
            binding_ids.append(int(row.source_bundle_uri_binding_id))

    dim_axis = tables.concept_declaration.alias("dim_cd")
    dim_axis_ci = tables.concept_identity.alias("dim_ci")
    dim_member = tables.concept_declaration.alias("mem_cd")
    dim_member_ci = tables.concept_identity.alias("mem_ci")
    dimensions_by_context: dict[int, list[Any]] = {cid: [] for cid in context_ids}
    if context_ids:
        dim_rows = conn.execute(
            select(
                tables.xbrl_context_dimension.c.id,
                tables.xbrl_context_dimension.c.context_id,
                tables.xbrl_context_dimension.c.context_element,
                tables.xbrl_context_dimension.c.member_kind,
                dim_axis_ci.c.namespace_uri,
                dim_axis_ci.c.local_name,
                dim_member_ci.c.namespace_uri,
                dim_member_ci.c.local_name,
                tables.xbrl_context_dimension.c.typed_member_xml,
                tables.xbrl_context_dimension.c.typed_member_hash,
                tables.xbrl_context_dimension.c.source_bundle_uri_binding_id,
                tables.xbrl_context_dimension.c.source_locator_scheme,
                tables.xbrl_context_dimension.c.source_locator_value,
            )
            .select_from(
                tables.xbrl_context_dimension.join(
                    dim_axis,
                    dim_axis.c.id
                    == tables.xbrl_context_dimension.c.dimension_concept_declaration_id,
                )
                .join(dim_axis_ci, dim_axis_ci.c.id == dim_axis.c.concept_identity_id)
                .outerjoin(
                    dim_member,
                    dim_member.c.id
                    == tables.xbrl_context_dimension.c.member_concept_declaration_id,
                )
                .outerjoin(dim_member_ci, dim_member_ci.c.id == dim_member.c.concept_identity_id)
            )
            .where(tables.xbrl_context_dimension.c.context_id.in_(context_ids))
        ).all()
        for row in dim_rows:
            dimensions_by_context[int(row.context_id)].append(row)
            binding_ids.append(int(row.source_bundle_uri_binding_id))

    units_by_id: dict[int, Any] = {}
    measures_by_unit: dict[int, list[Any]] = {uid: [] for uid in unit_ids}
    if unit_ids:
        unit_rows = conn.execute(
            select(
                tables.xbrl_unit.c.id,
                tables.xbrl_unit.c.source_unit_id,
                tables.xbrl_unit.c.source_bundle_uri_binding_id,
                tables.xbrl_unit.c.source_locator_scheme,
                tables.xbrl_unit.c.source_locator_value,
            ).where(tables.xbrl_unit.c.id.in_(unit_ids))
        ).all()
        for row in unit_rows:
            units_by_id[int(row.id)] = row
            binding_ids.append(int(row.source_bundle_uri_binding_id))
        measure_rows = conn.execute(
            select(
                tables.xbrl_unit_measure.c.unit_id,
                tables.xbrl_unit_measure.c.side,
                tables.xbrl_unit_measure.c.ordinal,
                tables.xbrl_unit_measure.c.namespace_uri,
                tables.xbrl_unit_measure.c.local_name,
            )
            .where(tables.xbrl_unit_measure.c.unit_id.in_(unit_ids))
            .order_by(
                tables.xbrl_unit_measure.c.unit_id,
                tables.xbrl_unit_measure.c.side,
                tables.xbrl_unit_measure.c.ordinal,
            )
        ).all()
        for row in measure_rows:
            measures_by_unit[int(row.unit_id)].append(row)

    # Relationship queries need binding ids too; collect after a first pass of relationship IDs.
    rel_binding_probe = conn.execute(
        select(tables.xbrl_relationship.c.source_bundle_uri_binding_id)
        .where(tables.xbrl_relationship.c.semantic_projection_id == pinned.semantic_projection_id)
        .where(
            (
                tables.xbrl_relationship.c.source_concept_declaration_id
                == pinned.concept_declaration_id
            )
            | (
                tables.xbrl_relationship.c.target_concept_declaration_id
                == pinned.concept_declaration_id
            )
        )
    ).scalars()
    binding_ids.extend(int(i) for i in rel_binding_probe)

    bindings = _load_source_bindings(conn, binding_ids)

    concept_declaration = {
        "qname": _qname_payload(declaration_row.namespace_uri, declaration_row.local_name),
        "type": _qname_payload(declaration_row.type_namespace_uri, declaration_row.type_local_name),
        "substitution_group": _qname_payload(
            declaration_row.substitution_group_namespace_uri,
            declaration_row.substitution_group_local_name,
        ),
        "period_type": declaration_row.period_type,
        "balance": declaration_row.balance,
        "is_abstract": declaration_row.is_abstract,
        "is_nillable": declaration_row.is_nillable,
        "source": _source_from_binding(
            bindings,
            declaration_row.source_bundle_uri_binding_id,
            locator_scheme=declaration_row.source_locator_scheme,
            locator_value=declaration_row.source_locator_value,
        ),
    }

    labels = [
        {
            "link_role_uri": row.link_role_uri,
            "arcrole_uri": row.arcrole_uri,
            "resource_role_uri": row.resource_role_uri,
            "language": row.language,
            "text": row.text,
            "order_value": _numeric_to_str(row.order_value),
            "resource_source": _source_from_binding(
                bindings,
                row.resource_source_bundle_uri_binding_id,
                locator_scheme=row.resource_source_locator_scheme,
                locator_value=row.resource_source_locator_value,
            ),
            "arc_source": _source_from_binding(
                bindings,
                row.arc_source_bundle_uri_binding_id,
                locator_scheme=row.arc_source_locator_scheme,
                locator_value=row.arc_source_locator_value,
            ),
            "_sort_id": int(row.id),
        }
        for row in label_rows
    ]
    labels.sort(
        key=lambda item: (
            item["link_role_uri"] or "",
            item["resource_role_uri"] or "",
            item["language"] or "",
            item["order_value"] or "",
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
            "reference_parts": row.reference_parts,
            "order_value": _numeric_to_str(row.order_value),
            "resource_source": _source_from_binding(
                bindings,
                row.resource_source_bundle_uri_binding_id,
                locator_scheme=row.resource_source_locator_scheme,
                locator_value=row.resource_source_locator_value,
            ),
            "arc_source": _source_from_binding(
                bindings,
                row.arc_source_bundle_uri_binding_id,
                locator_scheme=row.arc_source_locator_scheme,
                locator_value=row.arc_source_locator_value,
            ),
            "_sort_id": int(row.id),
        }
        for row in reference_rows
    ]
    references.sort(
        key=lambda item: (
            item["link_role_uri"] or "",
            item["resource_role_uri"] or "",
            item["order_value"] or "",
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
            "source": _source_from_binding(
                bindings,
                row.source_bundle_uri_binding_id,
                locator_scheme=row.source_locator_scheme,
                locator_value=row.source_locator_value,
            ),
        }
        if row.member_kind == "explicit":
            payload["member"] = _qname_payload(row[6], row[7])
            payload["typed_member_xml"] = None
            payload["typed_member_hash"] = None
        else:
            payload["member"] = None
            payload["typed_member_xml"] = row.typed_member_xml
            payload["typed_member_hash"] = row.typed_member_hash
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
                item["typed_member_hash"] or "",
            )
        )
        return {
            "source_context_id": row.source_context_id,
            "entity_scheme": row.entity_scheme,
            "entity_identifier": row.entity_identifier,
            "period_kind": row.period_kind,
            "instant_date": _date_to_iso(row.instant_date),
            "start_date": _date_to_iso(row.start_date),
            "end_date": _date_to_iso(row.end_date),
            "dimensions": dim_payloads,
            "source": _source_from_binding(
                bindings,
                row.source_bundle_uri_binding_id,
                locator_scheme=row.source_locator_scheme,
                locator_value=row.source_locator_value,
            ),
        }

    def _unit_payload(unit_id: int | None) -> dict[str, Any] | None:
        if unit_id is None:
            return None
        row = units_by_id[unit_id]
        measures = measures_by_unit.get(unit_id, [])
        numerator = [
            _qname_payload(m.namespace_uri, m.local_name) for m in measures if m.side == "numerator"
        ]
        denominator = [
            _qname_payload(m.namespace_uri, m.local_name)
            for m in measures
            if m.side == "denominator"
        ]
        return {
            "source_unit_id": row.source_unit_id,
            "numerator_measures": numerator,
            "denominator_measures": denominator,
            "source": _source_from_binding(
                bindings,
                row.source_bundle_uri_binding_id,
                locator_scheme=row.source_locator_scheme,
                locator_value=row.source_locator_value,
            ),
        }

    fact_payloads = [
        {
            "fact_id": int(row.id),
            "value_status": row.value_status,
            "raw_lexical_value": row.raw_lexical_value,
            "resolved_value_kind": row.resolved_value_kind,
            "resolved_value_text": row.resolved_value_text,
            "resolved_numeric": _numeric_to_str(row.resolved_numeric),
            "is_nil": row.is_nil,
            "reported_decimals": row.reported_decimals,
            "reported_precision": row.reported_precision,
            "scale": row.scale,
            "sign": row.sign,
            "format": (
                None
                if row.format_namespace_uri is None and row.format_local_name is None
                else _qname_payload(row.format_namespace_uri, row.format_local_name)
            ),
            "context": _context_payload(int(row.context_id)),
            "unit": _unit_payload(int(row.unit_id) if row.unit_id is not None else None),
            "source": _source_from_binding(
                bindings,
                row.source_bundle_uri_binding_id,
                locator_scheme=row.source_locator_scheme,
                locator_value=row.source_locator_value,
            ),
        }
        for row in fact_rows
    ]
    fact_payloads.sort(
        key=lambda item: (
            item["context"]["source_context_id"] or "",
            (item["unit"] or {}).get("source_unit_id") or "",
            item["raw_lexical_value"] or "",
            item["fact_id"],
        )
    )

    semantic_issues = [
        {
            "kind": row.kind,
            "severity": row.severity,
            "code": row.code,
            "message": row.message,
            "context": dict(row.context),
        }
        for row in issue_rows
    ]

    return ExplainEnrichment(
        pinned=pinned,
        concept_declaration=concept_declaration,
        labels=tuple(labels),
        references=tuple(references),
        presentation_neighbors=_relationship_neighbors(
            conn,
            projection_id=pinned.semantic_projection_id,
            concept_declaration_id=pinned.concept_declaration_id,
            network_type="presentation",
            bindings=bindings,
        ),
        calculation_neighbors=_relationship_neighbors(
            conn,
            projection_id=pinned.semantic_projection_id,
            concept_declaration_id=pinned.concept_declaration_id,
            network_type="calculation",
            bindings=bindings,
        ),
        definition_neighbors=_relationship_neighbors(
            conn,
            projection_id=pinned.semantic_projection_id,
            concept_declaration_id=pinned.concept_declaration_id,
            network_type="definition",
            bindings=bindings,
        ),
        fact_occurrences=tuple(fact_payloads),
        semantic_issues=tuple(semantic_issues),
    )


def enrichment_to_payload(enrichment: ExplainEnrichment) -> dict[str, Any]:
    pinned = enrichment.pinned
    return {
        "bundle_id": pinned.bundle_id,
        "semantic_projection_id": pinned.semantic_projection_id,
        "concept_declaration_id": pinned.concept_declaration_id,
        "report_input_ordinal": pinned.report_input_ordinal,
        "filing": {
            "accession_number": pinned.accession_number,
            "report_period_end": _date_to_iso(pinned.report_period_end),
        },
        "projection": {
            "projection_version": pinned.projection_version,
            "arelle_version": pinned.arelle_version,
            "semantic_config_fingerprint": pinned.semantic_config_fingerprint,
            "semantic_config": pinned.semantic_config,
            "status": pinned.projection_status,
        },
        "semantic_issues": list(enrichment.semantic_issues),
        "concept_declaration": enrichment.concept_declaration,
        "labels": list(enrichment.labels),
        "references": list(enrichment.references),
        "presentation_neighbors": list(enrichment.presentation_neighbors),
        "calculation_neighbors": list(enrichment.calculation_neighbors),
        "definition_neighbors": list(enrichment.definition_neighbors),
        "fact_occurrences": list(enrichment.fact_occurrences),
    }
