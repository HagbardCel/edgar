"""SQL adapter: persist and reconstruct semantic projections (caller owns the transaction)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from edgar.db import schema as tables
from edgar.xbrl.config import SEMANTIC_CONFIG_SCHEMA
from edgar.xbrl.records import (
    RESOLVED_VALUE_KINDS,
    ArcroleDeclarationRecord,
    ConceptDeclarationRecord,
    ConceptLabelRecord,
    ConceptReferenceRecord,
    ContextDimensionRecord,
    ContextRecord,
    ExpandedQName,
    FactRecord,
    ReferencePartRecord,
    RelationshipRecord,
    ResolvedValueKind,
    RoleDeclarationRecord,
    SemanticIssueRecord,
    SemanticProjectionData,
    SourceLocator,
    UnitMeasureRecord,
    UnitRecord,
)

_NON_NUMERIC_RESOLVED_KINDS: frozenset[str] = frozenset(
    kind for kind in RESOLVED_VALUE_KINDS if kind != "numeric"
)


class SemanticProjectionConflict(RuntimeError):
    """Persisted semantic state conflicts with the incoming projection."""


@dataclass(frozen=True)
class SemanticProjectionResult:
    projection_id: int
    attempt_id: int
    status: str
    reused: bool
    counts: dict[str, int]
    arelle_version: str


@dataclass(frozen=True)
class SemanticFailureResult:
    attempt_id: int
    status: str = "failed"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _verify_fingerprint(config: Mapping[str, Any], fingerprint: str) -> None:
    envelope = {"config": dict(config), "schema": SEMANTIC_CONFIG_SCHEMA}
    digest = hashlib.sha256(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    if digest != fingerprint:
        raise SemanticProjectionConflict(
            "semantic_config fingerprint does not match canonicalize(semantic_config)"
        )


def _locator_value_json(locator: SourceLocator) -> str:
    """Persist locator value as a JSON string scalar."""
    return locator.value


def _binding_map(conn: Connection, bundle_id: int) -> dict[str, int]:
    rows = conn.execute(
        select(
            tables.bundle_uri_binding.c.id,
            tables.bundle_uri_binding.c.document_uri,
            tables.bundle_uri_binding.c.filing_bundle_id,
        ).where(tables.bundle_uri_binding.c.filing_bundle_id == bundle_id)
    ).mappings()
    return {str(row["document_uri"]): int(row["id"]) for row in rows}


def _require_binding(bindings: Mapping[str, int], locator: SourceLocator) -> int:
    binding_id = bindings.get(locator.document_uri)
    if binding_id is None:
        raise SemanticProjectionConflict(
            f"source document URI is not a primary binding of this bundle: {locator.document_uri}"
        )
    return binding_id


def _issue_kind(issue: SemanticIssueRecord) -> str:
    code = issue.code
    if code.startswith("UNSUPPORTED_") or "UNSUPPORTED" in code:
        return "unsupported"
    if "DIAGNOSTIC" in code or code.startswith("ix") or code.startswith("xbrl"):
        return "diagnostic"
    return "extraction"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stable_issue_context(issue: SemanticIssueRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in sorted(issue.context.items())
        if key not in {"message", "path", "workspace", "tmp"}
    }


def _issue_equality_representation(issue: SemanticIssueRecord) -> dict[str, Any]:
    return {
        "severity": issue.severity,
        "code": issue.code,
        "locator": None if issue.locator is None else issue.locator.to_dict(),
        "context": _stable_issue_context(issue),
    }


def _issue_sort_key(issue: SemanticIssueRecord) -> tuple[Any, ...]:
    locator_key = None if issue.locator is None else issue.locator.sort_key()
    representation = _issue_equality_representation(issue)
    return (
        issue.severity,
        issue.code,
        locator_key,
        _canonical_json(representation["context"]),
        _canonical_json(representation),
    )


def _sorted_dicts(records: Sequence[Any], primary_key) -> list[dict[str, Any]]:
    decorated = [
        (primary_key(record), _canonical_json(record.to_dict()), record.to_dict())
        for record in records
    ]
    decorated.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in decorated]


def semantic_projection_equality_state(
    data: SemanticProjectionData,
    *,
    status: str,
    semantic_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalized comparable projection state (multiplicity-preserving, total order)."""

    return {
        "status": status,
        "semantic_config": dict(semantic_config),
        "config_fingerprint": data.config_fingerprint,
        "projection_version": data.projection_version,
        "engine_version": data.engine_version,
        "concept_declarations": _sorted_dicts(
            data.concept_declarations, lambda r: r.concept.sort_key()
        ),
        "concept_labels": _sorted_dicts(
            data.concept_labels,
            lambda r: (
                r.concept.sort_key(),
                r.link_role_uri,
                r.arcrole_uri,
                r.resource_role_uri or "",
                r.xml_lang or "",
                r.source_locator.sort_key(),
                r.arc_locator.sort_key(),
            ),
        ),
        "concept_references": _sorted_dicts(
            data.concept_references,
            lambda r: (
                r.concept.sort_key(),
                r.link_role_uri,
                r.arcrole_uri,
                r.resource_role_uri or "",
                r.source_locator.sort_key(),
                r.arc_locator.sort_key(),
            ),
        ),
        "role_declarations": _sorted_dicts(
            data.role_declarations, lambda r: (r.role_uri, r.source_locator.sort_key())
        ),
        "arcrole_declarations": _sorted_dicts(
            data.arcrole_declarations, lambda r: (r.arcrole_uri, r.source_locator.sort_key())
        ),
        "contexts": _sorted_dicts(data.contexts, lambda r: r.source_locator.sort_key()),
        "context_dimensions": _sorted_dicts(
            data.context_dimensions,
            lambda r: (
                r.context_locator.sort_key(),
                r.source_locator.sort_key(),
                r.dimension.sort_key(),
            ),
        ),
        "units": _sorted_dicts(data.units, lambda r: r.source_locator.sort_key()),
        "unit_measures": _sorted_dicts(
            data.unit_measures,
            lambda r: (r.unit_locator.sort_key(), r.measure_role, r.ordinal),
        ),
        "facts": _sorted_dicts(data.facts, lambda r: r.source_locator.sort_key()),
        "relationships": _sorted_dicts(
            data.relationships,
            lambda r: (
                r.network_type,
                r.link_role_uri,
                r.arcrole_uri,
                r.source_concept.sort_key(),
                r.target_concept.sort_key(),
                r.source_locator.sort_key(),
            ),
        ),
        "issues": [
            _issue_equality_representation(issue)
            for issue in sorted(data.issues, key=_issue_sort_key)
        ],
    }


def _parse_filed_date(value: str | None, *, field: str) -> date | None:
    if value is None:
        return None
    if "T" in value:
        raise SemanticProjectionConflict(
            f"context {field} is dateTime and cannot be stored under arelle-semantic-v1: {value!r}"
        )
    return date.fromisoformat(value)


def _validate_resolved_value_fields(
    kind: str | None,
    text: str | None,
    numeric: Decimal | None,
) -> tuple[str | None, str | None, Decimal | None]:
    """Require mutually coherent ``(kind, text, numeric)``; no inference."""
    if kind is None:
        if text is not None or numeric is not None:
            raise SemanticProjectionConflict(
                "resolved_value_kind is NULL but resolved value columns are set"
            )
        return None, None, None
    if kind == "numeric":
        if text is not None or numeric is None:
            raise SemanticProjectionConflict(
                "numeric resolved_value_kind requires resolved_numeric and null resolved_value_text"
            )
        return kind, None, numeric
    if kind in _NON_NUMERIC_RESOLVED_KINDS:
        if text is None or numeric is not None:
            raise SemanticProjectionConflict(
                f"{kind} resolved_value_kind requires resolved_value_text and null resolved_numeric"
            )
        return kind, text, None
    raise SemanticProjectionConflict(f"unknown resolved_value_kind: {kind!r}")


def _resolved_value_fields(fact: FactRecord) -> tuple[str | None, str | None, Decimal | None]:
    """Persist FactRecord resolved fields as a coherent ``(kind, text, numeric)``."""
    return _validate_resolved_value_fields(
        fact.resolved_value_kind,
        fact.resolved_text_value,
        fact.resolved_numeric_value,
    )


def record_semantic_projection_failure(
    conn: Connection,
    *,
    report_input_id: int,
    projection_version: str,
    semantic_config: Mapping[str, Any],
    config_fingerprint: str,
    arelle_version: str | None,
    started_at: datetime,
    completed_at: datetime,
    issues: Sequence[SemanticIssueRecord] | Sequence[Mapping[str, Any]],
) -> SemanticFailureResult:
    """Persist a failed attempt and attempt-scoped issues. No projection rows."""
    _verify_fingerprint(semantic_config, config_fingerprint)
    attempt_id = int(
        conn.execute(
            insert(tables.semantic_projection_attempt)
            .values(
                xbrl_report_input_id=report_input_id,
                projection_version=projection_version,
                semantic_config_fingerprint=config_fingerprint,
                semantic_config=dict(semantic_config),
                arelle_version=arelle_version,
                started_at=started_at,
                completed_at=completed_at,
                status="failed",
                semantic_projection_id=None,
            )
            .returning(tables.semantic_projection_attempt.c.id)
        ).scalar_one()
    )
    parsed_issues: list[SemanticIssueRecord] = []
    for raw in issues:
        if isinstance(raw, SemanticIssueRecord):
            parsed_issues.append(raw)
        else:
            parsed_issues.append(SemanticIssueRecord.from_dict(dict(raw)))
    if parsed_issues:
        conn.execute(
            insert(tables.semantic_issue),
            [
                {
                    "semantic_projection_id": None,
                    "semantic_projection_attempt_id": attempt_id,
                    "kind": _issue_kind(issue),
                    "severity": issue.severity,
                    "code": issue.code,
                    "message": issue.message,
                    "context": {
                        **dict(issue.context),
                        **(
                            {"locator": issue.locator.to_dict()}
                            if issue.locator is not None
                            else {}
                        ),
                    },
                }
                for issue in parsed_issues
            ],
        )
    return SemanticFailureResult(attempt_id=attempt_id)


def _select_projection_id(
    conn: Connection,
    *,
    report_input_id: int,
    projection_version: str,
    arelle_version: str,
    fingerprint: str,
) -> int | None:
    row = conn.execute(
        select(tables.semantic_projection.c.id)
        .where(tables.semantic_projection.c.xbrl_report_input_id == report_input_id)
        .where(tables.semantic_projection.c.projection_version == projection_version)
        .where(tables.semantic_projection.c.arelle_version == arelle_version)
        .where(tables.semantic_projection.c.semantic_config_fingerprint == fingerprint)
    ).scalar_one_or_none()
    return int(row) if row is not None else None


def _upsert_concept_identities(
    conn: Connection, qnames: Sequence[ExpandedQName]
) -> dict[ExpandedQName, int]:
    unique: dict[ExpandedQName, ExpandedQName] = {}
    for qname in qnames:
        if qname.namespace_uri is None:
            raise SemanticProjectionConflict(
                f"concept identity requires a namespace URI: {qname.local_name}"
            )
        unique[qname] = qname
    if not unique:
        return {}
    rows = [{"namespace_uri": q.namespace_uri, "local_name": q.local_name} for q in unique.values()]
    conn.execute(
        insert(tables.concept_identity)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["namespace_uri", "local_name"])
    )
    selected = conn.execute(
        select(
            tables.concept_identity.c.id,
            tables.concept_identity.c.namespace_uri,
            tables.concept_identity.c.local_name,
        ).where(
            tables.concept_identity.c.namespace_uri.in_([r["namespace_uri"] for r in rows]),
        )
    ).mappings()
    out: dict[ExpandedQName, int] = {}
    wanted = {(q.namespace_uri, q.local_name): q for q in unique}
    for row in selected:
        key = (row["namespace_uri"], row["local_name"])
        qname = wanted.get(key)
        if qname is not None:
            out[qname] = int(row["id"])
    if len(out) != len(unique):
        raise SemanticProjectionConflict("failed to resolve concept_identity rows")
    return out


def catalog_semantic_projection(
    conn: Connection,
    *,
    report_input_id: int,
    bundle_id: int,
    projection_data: SemanticProjectionData,
    status: str,
    semantic_config: Mapping[str, Any],
    started_at: datetime,
    completed_at: datetime,
) -> SemanticProjectionResult:
    """Insert or verified-reuse one semantic projection; record a completed attempt."""
    if status not in {"complete", "incomplete"}:
        raise ValueError(f"invalid projection status: {status!r}")
    fingerprint = projection_data.config_fingerprint
    _verify_fingerprint(semantic_config, fingerprint)

    # Confirm report input belongs to bundle_id.
    owner = conn.execute(
        select(tables.xbrl_report_input.c.filing_bundle_id).where(
            tables.xbrl_report_input.c.id == report_input_id
        )
    ).scalar_one_or_none()
    if owner is None or int(owner) != bundle_id:
        raise SemanticProjectionConflict("report_input_id does not belong to bundle_id")

    existing_id = _select_projection_id(
        conn,
        report_input_id=report_input_id,
        projection_version=projection_data.projection_version,
        arelle_version=projection_data.engine_version,
        fingerprint=fingerprint,
    )
    if existing_id is not None:
        loaded, loaded_status = load_semantic_projection(conn, existing_id)
        incoming_state = semantic_projection_equality_state(
            projection_data, status=status, semantic_config=semantic_config
        )
        loaded_config = conn.execute(
            select(tables.semantic_projection.c.semantic_config).where(
                tables.semantic_projection.c.id == existing_id
            )
        ).scalar_one()
        loaded_state = semantic_projection_equality_state(
            loaded, status=loaded_status, semantic_config=dict(loaded_config)
        )
        if incoming_state != loaded_state:
            raise SemanticProjectionConflict(
                f"semantic_projection id={existing_id} exists but reconstructed state differs"
            )
        attempt_id = _insert_completed_attempt(
            conn,
            report_input_id=report_input_id,
            projection_id=existing_id,
            projection_data=projection_data,
            semantic_config=semantic_config,
            started_at=started_at,
            completed_at=completed_at,
        )
        return SemanticProjectionResult(
            projection_id=existing_id,
            attempt_id=attempt_id,
            status=loaded_status,
            reused=True,
            counts=projection_data.record_counts(),
            arelle_version=projection_data.engine_version,
        )

    projection_id = _insert_projection_tree(
        conn,
        report_input_id=report_input_id,
        bundle_id=bundle_id,
        projection_data=projection_data,
        status=status,
        semantic_config=semantic_config,
    )
    attempt_id = _insert_completed_attempt(
        conn,
        report_input_id=report_input_id,
        projection_id=projection_id,
        projection_data=projection_data,
        semantic_config=semantic_config,
        started_at=started_at,
        completed_at=completed_at,
    )
    # Round-trip verify.
    loaded, loaded_status = load_semantic_projection(conn, projection_id)
    if semantic_projection_equality_state(
        loaded, status=loaded_status, semantic_config=semantic_config
    ) != semantic_projection_equality_state(
        projection_data, status=status, semantic_config=semantic_config
    ):
        raise SemanticProjectionConflict("semantic projection round-trip equality failed")
    return SemanticProjectionResult(
        projection_id=projection_id,
        attempt_id=attempt_id,
        status=status,
        reused=False,
        counts=projection_data.record_counts(),
        arelle_version=projection_data.engine_version,
    )


def _insert_completed_attempt(
    conn: Connection,
    *,
    report_input_id: int,
    projection_id: int,
    projection_data: SemanticProjectionData,
    semantic_config: Mapping[str, Any],
    started_at: datetime,
    completed_at: datetime,
) -> int:
    return int(
        conn.execute(
            insert(tables.semantic_projection_attempt)
            .values(
                xbrl_report_input_id=report_input_id,
                projection_version=projection_data.projection_version,
                semantic_config_fingerprint=projection_data.config_fingerprint,
                semantic_config=dict(semantic_config),
                arelle_version=projection_data.engine_version,
                started_at=started_at,
                completed_at=completed_at,
                status="completed",
                semantic_projection_id=projection_id,
            )
            .returning(tables.semantic_projection_attempt.c.id)
        ).scalar_one()
    )


def _insert_projection_tree(
    conn: Connection,
    *,
    report_input_id: int,
    bundle_id: int,
    projection_data: SemanticProjectionData,
    status: str,
    semantic_config: Mapping[str, Any],
) -> int:
    bindings = _binding_map(conn, bundle_id)
    projection_id = int(
        conn.execute(
            insert(tables.semantic_projection)
            .values(
                xbrl_report_input_id=report_input_id,
                projection_version=projection_data.projection_version,
                arelle_version=projection_data.engine_version,
                semantic_config_fingerprint=projection_data.config_fingerprint,
                semantic_config=dict(semantic_config),
                status=status,
                created_at=_utcnow(),
            )
            .returning(tables.semantic_projection.c.id)
        ).scalar_one()
    )

    qnames = [decl.concept for decl in projection_data.concept_declarations]
    identity_ids = _upsert_concept_identities(conn, qnames)
    decl_ids: dict[ExpandedQName, int] = {}
    for decl in projection_data.concept_declarations:
        binding_id = _require_binding(bindings, decl.source_locator)
        decl_id = int(
            conn.execute(
                insert(tables.concept_declaration)
                .values(
                    semantic_projection_id=projection_id,
                    concept_identity_id=identity_ids[decl.concept],
                    type_namespace_uri=None
                    if decl.data_type is None
                    else decl.data_type.namespace_uri,
                    type_local_name=None if decl.data_type is None else decl.data_type.local_name,
                    substitution_group_namespace_uri=(
                        None
                        if decl.substitution_group is None
                        else decl.substitution_group.namespace_uri
                    ),
                    substitution_group_local_name=(
                        None
                        if decl.substitution_group is None
                        else decl.substitution_group.local_name
                    ),
                    period_type=decl.period_type,
                    balance=decl.balance,
                    is_abstract=decl.abstract,
                    is_nillable=decl.nillable,
                    source_bundle_uri_binding_id=binding_id,
                    source_locator_scheme=decl.source_locator.scheme,
                    source_locator_value=_locator_value_json(decl.source_locator),
                )
                .returning(tables.concept_declaration.c.id)
            ).scalar_one()
        )
        decl_ids[decl.concept] = decl_id

    for role in projection_data.role_declarations:
        binding_id = _require_binding(bindings, role.source_locator)
        conn.execute(
            insert(tables.role_declaration).values(
                semantic_projection_id=projection_id,
                role_uri=role.role_uri,
                definition=role.definition,
                used_on=[q.to_dict() for q in role.used_on],
                source_bundle_uri_binding_id=binding_id,
                source_locator_scheme=role.source_locator.scheme,
                source_locator_value=_locator_value_json(role.source_locator),
            )
        )
    for arcrole in projection_data.arcrole_declarations:
        binding_id = _require_binding(bindings, arcrole.source_locator)
        conn.execute(
            insert(tables.arcrole_declaration).values(
                semantic_projection_id=projection_id,
                arcrole_uri=arcrole.arcrole_uri,
                definition=arcrole.definition,
                used_on=[q.to_dict() for q in arcrole.used_on],
                cycles_allowed=arcrole.cycles_allowed,
                source_bundle_uri_binding_id=binding_id,
                source_locator_scheme=arcrole.source_locator.scheme,
                source_locator_value=_locator_value_json(arcrole.source_locator),
            )
        )

    for label in projection_data.concept_labels:
        decl_id = decl_ids.get(label.concept)
        if decl_id is None:
            raise SemanticProjectionConflict(f"label references unknown concept {label.concept}")
        conn.execute(
            insert(tables.concept_label).values(
                semantic_projection_id=projection_id,
                concept_declaration_id=decl_id,
                link_role_uri=label.link_role_uri,
                arcrole_uri=label.arcrole_uri,
                resource_role_uri=label.resource_role_uri,
                language=label.xml_lang,
                text=label.text,
                order_value=label.order,
                resource_source_bundle_uri_binding_id=_require_binding(
                    bindings, label.source_locator
                ),
                resource_source_locator_scheme=label.source_locator.scheme,
                resource_source_locator_value=_locator_value_json(label.source_locator),
                arc_source_bundle_uri_binding_id=_require_binding(bindings, label.arc_locator),
                arc_source_locator_scheme=label.arc_locator.scheme,
                arc_source_locator_value=_locator_value_json(label.arc_locator),
            )
        )
    for reference in projection_data.concept_references:
        decl_id = decl_ids.get(reference.concept)
        if decl_id is None:
            raise SemanticProjectionConflict(
                f"reference references unknown concept {reference.concept}"
            )
        conn.execute(
            insert(tables.concept_reference).values(
                semantic_projection_id=projection_id,
                concept_declaration_id=decl_id,
                link_role_uri=reference.link_role_uri,
                arcrole_uri=reference.arcrole_uri,
                resource_role_uri=reference.resource_role_uri,
                reference_parts=[part.to_dict() for part in reference.reference_parts],
                order_value=reference.order,
                resource_source_bundle_uri_binding_id=_require_binding(
                    bindings, reference.source_locator
                ),
                resource_source_locator_scheme=reference.source_locator.scheme,
                resource_source_locator_value=_locator_value_json(reference.source_locator),
                arc_source_bundle_uri_binding_id=_require_binding(bindings, reference.arc_locator),
                arc_source_locator_scheme=reference.arc_locator.scheme,
                arc_source_locator_value=_locator_value_json(reference.arc_locator),
            )
        )

    context_ids: dict[tuple[str, str, str], int] = {}
    for context in projection_data.contexts:
        binding_id = _require_binding(bindings, context.source_locator)
        context_id = int(
            conn.execute(
                insert(tables.xbrl_context)
                .values(
                    semantic_projection_id=projection_id,
                    source_context_id=context.source_context_id,
                    entity_scheme=context.entity_scheme,
                    entity_identifier=context.entity_identifier,
                    period_kind=context.period_kind,
                    instant_date=_parse_filed_date(context.period_instant, field="instant"),
                    start_date=_parse_filed_date(context.period_start, field="start"),
                    end_date=_parse_filed_date(context.period_end, field="end"),
                    source_bundle_uri_binding_id=binding_id,
                    source_locator_scheme=context.source_locator.scheme,
                    source_locator_value=_locator_value_json(context.source_locator),
                )
                .returning(tables.xbrl_context.c.id)
            ).scalar_one()
        )
        context_ids[context.source_locator.sort_key()] = context_id

    for dim in projection_data.context_dimensions:
        context_id = context_ids.get(dim.context_locator.sort_key())
        if context_id is None:
            raise SemanticProjectionConflict("context dimension references unknown context")
        dim_decl = decl_ids.get(dim.dimension)
        if dim_decl is None:
            raise SemanticProjectionConflict("context dimension references unknown dimension")
        member_decl = None if dim.member is None else decl_ids.get(dim.member)
        if dim.member is not None and member_decl is None:
            raise SemanticProjectionConflict("explicit dimension member declaration missing")
        conn.execute(
            insert(tables.xbrl_context_dimension).values(
                context_id=context_id,
                dimension_concept_declaration_id=dim_decl,
                context_element=dim.context_element,
                member_kind=dim.member_kind,
                member_concept_declaration_id=member_decl,
                typed_member_xml=dim.typed_member_xml,
                typed_member_hash=dim.typed_member_sha256,
                source_bundle_uri_binding_id=_require_binding(bindings, dim.source_locator),
                source_locator_scheme=dim.source_locator.scheme,
                source_locator_value=_locator_value_json(dim.source_locator),
            )
        )

    unit_ids: dict[tuple[str, str, str], int] = {}
    for unit in projection_data.units:
        unit_id = int(
            conn.execute(
                insert(tables.xbrl_unit)
                .values(
                    semantic_projection_id=projection_id,
                    source_unit_id=unit.source_unit_id,
                    source_bundle_uri_binding_id=_require_binding(bindings, unit.source_locator),
                    source_locator_scheme=unit.source_locator.scheme,
                    source_locator_value=_locator_value_json(unit.source_locator),
                )
                .returning(tables.xbrl_unit.c.id)
            ).scalar_one()
        )
        unit_ids[unit.source_locator.sort_key()] = unit_id
    for measure in projection_data.unit_measures:
        unit_id = unit_ids.get(measure.unit_locator.sort_key())
        if unit_id is None:
            raise SemanticProjectionConflict("unit measure references unknown unit")
        conn.execute(
            insert(tables.xbrl_unit_measure).values(
                unit_id=unit_id,
                side=measure.measure_role,
                ordinal=measure.ordinal,
                namespace_uri=measure.measure.namespace_uri,
                local_name=measure.measure.local_name,
            )
        )

    for fact in projection_data.facts:
        decl_id = decl_ids.get(fact.concept_qname)
        context_id = context_ids.get(fact.context_locator.sort_key())
        if decl_id is None or context_id is None:
            raise SemanticProjectionConflict("fact references unresolved concept or context")
        unit_id = None
        if fact.unit_locator is not None:
            unit_id = unit_ids.get(fact.unit_locator.sort_key())
            if unit_id is None:
                raise SemanticProjectionConflict("fact references unresolved unit locator")
        kind, text, numeric = _resolved_value_fields(fact)
        conn.execute(
            insert(tables.xbrl_fact).values(
                semantic_projection_id=projection_id,
                concept_declaration_id=decl_id,
                context_id=context_id,
                unit_id=unit_id,
                source_bundle_uri_binding_id=_require_binding(bindings, fact.source_locator),
                source_locator_scheme=fact.source_locator.scheme,
                source_locator_value=_locator_value_json(fact.source_locator),
                value_status=fact.value_status,
                raw_lexical_value=fact.raw_lexical_value,
                resolved_value_kind=kind,
                resolved_value_text=text,
                resolved_numeric=numeric,
                is_nil=fact.is_nil,
                reported_decimals=fact.reported_decimals,
                reported_precision=fact.reported_precision,
                xml_lang=fact.xml_lang,
                format_namespace_uri=(
                    None if fact.format_qname is None else fact.format_qname.namespace_uri
                ),
                format_local_name=None
                if fact.format_qname is None
                else fact.format_qname.local_name,
                scale=fact.scale,
                sign=fact.sign,
                escape=fact.escape,
                continuation_provenance=[loc.to_dict() for loc in fact.continuation_provenance]
                or None,
            )
        )

    for rel in projection_data.relationships:
        source_id = decl_ids.get(rel.source_concept)
        target_id = decl_ids.get(rel.target_concept)
        if source_id is None or target_id is None:
            raise SemanticProjectionConflict("relationship endpoint declaration missing")
        conn.execute(
            insert(tables.xbrl_relationship).values(
                semantic_projection_id=projection_id,
                network_type=rel.network_type,
                link_role_uri=rel.link_role_uri,
                arcrole_uri=rel.arcrole_uri,
                source_concept_declaration_id=source_id,
                target_concept_declaration_id=target_id,
                order_value=rel.order,
                weight=rel.weight,
                preferred_label_role=rel.preferred_label_role,
                target_role_uri=rel.target_role_uri,
                closed=rel.closed,
                usable=rel.usable,
                context_element=rel.context_element,
                source_bundle_uri_binding_id=_require_binding(bindings, rel.source_locator),
                source_locator_scheme=rel.source_locator.scheme,
                source_locator_value=_locator_value_json(rel.source_locator),
            )
        )

    if projection_data.issues:
        conn.execute(
            insert(tables.semantic_issue),
            [
                {
                    "semantic_projection_id": projection_id,
                    "semantic_projection_attempt_id": None,
                    "kind": _issue_kind(issue),
                    "severity": issue.severity,
                    "code": issue.code,
                    "message": issue.message,
                    "context": {
                        **dict(issue.context),
                        **(
                            {"locator": issue.locator.to_dict()}
                            if issue.locator is not None
                            else {}
                        ),
                    },
                }
                for issue in projection_data.issues
            ],
        )
    return projection_id


def _load_locator_from_row(
    *,
    document_uri: str,
    scheme: str,
    value: Any,
) -> SourceLocator:
    text = value if isinstance(value, str) else str(value)
    return SourceLocator(document_uri=document_uri, scheme=cast(Any, scheme), value=text)


def load_semantic_projection(
    conn: Connection, projection_id: int
) -> tuple[SemanticProjectionData, str]:
    """Reconstruct projection data with ownership checks."""
    proj = (
        conn.execute(
            select(tables.semantic_projection).where(
                tables.semantic_projection.c.id == projection_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if proj is None:
        raise LookupError(f"semantic_projection id={projection_id} not found")
    _verify_fingerprint(dict(proj["semantic_config"]), str(proj["semantic_config_fingerprint"]))

    report_input_id = int(proj["xbrl_report_input_id"])
    bundle_id = int(
        conn.execute(
            select(tables.xbrl_report_input.c.filing_bundle_id).where(
                tables.xbrl_report_input.c.id == report_input_id
            )
        ).scalar_one()
    )

    # Binding ownership map for this bundle.
    binding_rows = {
        int(row["id"]): str(row["document_uri"])
        for row in conn.execute(
            select(
                tables.bundle_uri_binding.c.id,
                tables.bundle_uri_binding.c.document_uri,
                tables.bundle_uri_binding.c.filing_bundle_id,
            ).where(tables.bundle_uri_binding.c.filing_bundle_id == bundle_id)
        ).mappings()
    }

    def uri_for_binding(binding_id: int) -> str:
        uri = binding_rows.get(binding_id)
        if uri is None:
            raise SemanticProjectionConflict(
                f"source_bundle_uri_binding_id={binding_id} is not owned by projection bundle"
            )
        return uri

    identity_rows = {
        int(row["id"]): ExpandedQName(
            namespace_uri=row["namespace_uri"], local_name=row["local_name"]
        )
        for row in conn.execute(
            select(tables.concept_identity).order_by(tables.concept_identity.c.id)
        ).mappings()
    }

    decl_rows = list(
        conn.execute(
            select(tables.concept_declaration)
            .where(tables.concept_declaration.c.semantic_projection_id == projection_id)
            .order_by(tables.concept_declaration.c.id)
        ).mappings()
    )
    decl_by_id: dict[int, ConceptDeclarationRecord] = {}
    decl_qname_by_id: dict[int, ExpandedQName] = {}
    for row in decl_rows:
        if int(row["semantic_projection_id"]) != projection_id:
            raise SemanticProjectionConflict("concept_declaration ownership mismatch")
        qname = identity_rows[int(row["concept_identity_id"])]
        data_type = None
        if row["type_local_name"] is not None:
            data_type = ExpandedQName(
                namespace_uri=row["type_namespace_uri"], local_name=row["type_local_name"]
            )
        subst = None
        if row["substitution_group_local_name"] is not None:
            subst = ExpandedQName(
                namespace_uri=row["substitution_group_namespace_uri"],
                local_name=row["substitution_group_local_name"],
            )
        record = ConceptDeclarationRecord(
            concept=qname,
            source_locator=_load_locator_from_row(
                document_uri=uri_for_binding(int(row["source_bundle_uri_binding_id"])),
                scheme=row["source_locator_scheme"],
                value=row["source_locator_value"],
            ),
            data_type=data_type,
            substitution_group=subst,
            period_type=row["period_type"],
            balance=row["balance"],
            abstract=row["is_abstract"],
            nillable=row["is_nillable"],
        )
        decl_by_id[int(row["id"])] = record
        decl_qname_by_id[int(row["id"])] = qname

    def require_decl(decl_id: int) -> ExpandedQName:
        qname = decl_qname_by_id.get(decl_id)
        if qname is None:
            raise SemanticProjectionConflict(
                f"cross-projection or missing concept_declaration_id={decl_id}"
            )
        return qname

    contexts: list[ContextRecord] = []
    context_id_to_locator: dict[int, SourceLocator] = {}
    for row in conn.execute(
        select(tables.xbrl_context)
        .where(tables.xbrl_context.c.semantic_projection_id == projection_id)
        .order_by(tables.xbrl_context.c.id)
    ).mappings():
        locator = _load_locator_from_row(
            document_uri=uri_for_binding(int(row["source_bundle_uri_binding_id"])),
            scheme=row["source_locator_scheme"],
            value=row["source_locator_value"],
        )
        context_id_to_locator[int(row["id"])] = locator
        contexts.append(
            ContextRecord(
                source_context_id=row["source_context_id"],
                entity_scheme=row["entity_scheme"],
                entity_identifier=row["entity_identifier"],
                period_kind=row["period_kind"],
                source_locator=locator,
                period_instant=None
                if row["instant_date"] is None
                else row["instant_date"].isoformat(),
                period_start=None if row["start_date"] is None else row["start_date"].isoformat(),
                period_end=None if row["end_date"] is None else row["end_date"].isoformat(),
            )
        )

    context_dimensions: list[ContextDimensionRecord] = []
    for row in conn.execute(
        select(tables.xbrl_context_dimension)
        .join(
            tables.xbrl_context,
            tables.xbrl_context.c.id == tables.xbrl_context_dimension.c.context_id,
        )
        .where(tables.xbrl_context.c.semantic_projection_id == projection_id)
        .order_by(tables.xbrl_context_dimension.c.id)
    ).mappings():
        context_locator = context_id_to_locator[int(row["context_id"])]
        member = None
        if row["member_concept_declaration_id"] is not None:
            member = require_decl(int(row["member_concept_declaration_id"]))
        context_dimensions.append(
            ContextDimensionRecord(
                context_locator=context_locator,
                dimension=require_decl(int(row["dimension_concept_declaration_id"])),
                context_element=row["context_element"],
                member_kind=row["member_kind"],
                source_locator=_load_locator_from_row(
                    document_uri=uri_for_binding(int(row["source_bundle_uri_binding_id"])),
                    scheme=row["source_locator_scheme"],
                    value=row["source_locator_value"],
                ),
                member=member,
                typed_member_xml=row["typed_member_xml"],
                typed_member_sha256=row["typed_member_hash"],
            )
        )

    units: list[UnitRecord] = []
    unit_id_to_locator: dict[int, SourceLocator] = {}
    unit_id_to_source_id: dict[int, str] = {}
    for row in conn.execute(
        select(tables.xbrl_unit)
        .where(tables.xbrl_unit.c.semantic_projection_id == projection_id)
        .order_by(tables.xbrl_unit.c.id)
    ).mappings():
        locator = _load_locator_from_row(
            document_uri=uri_for_binding(int(row["source_bundle_uri_binding_id"])),
            scheme=row["source_locator_scheme"],
            value=row["source_locator_value"],
        )
        unit_id_to_locator[int(row["id"])] = locator
        unit_id_to_source_id[int(row["id"])] = row["source_unit_id"]
        units.append(
            UnitRecord(source_unit_id=row["source_unit_id"], source_locator=locator, divide=False)
        )

    unit_measures: list[UnitMeasureRecord] = []
    for row in conn.execute(
        select(tables.xbrl_unit_measure)
        .join(tables.xbrl_unit, tables.xbrl_unit.c.id == tables.xbrl_unit_measure.c.unit_id)
        .where(tables.xbrl_unit.c.semantic_projection_id == projection_id)
        .order_by(
            tables.xbrl_unit_measure.c.unit_id,
            tables.xbrl_unit_measure.c.side,
            tables.xbrl_unit_measure.c.ordinal,
        )
    ).mappings():
        unit_measures.append(
            UnitMeasureRecord(
                unit_locator=unit_id_to_locator[int(row["unit_id"])],
                measure_role=row["side"],
                ordinal=int(row["ordinal"]),
                measure=ExpandedQName(
                    namespace_uri=row["namespace_uri"], local_name=row["local_name"]
                ),
            )
        )
    # Reconstruct divide flag from measures.
    measures_by_unit = {}
    for measure in unit_measures:
        measures_by_unit.setdefault(measure.unit_locator.sort_key(), []).append(measure)
    rebuilt_units: list[UnitRecord] = []
    for unit in units:
        kids = measures_by_unit.get(unit.source_locator.sort_key(), [])
        divide = any(m.measure_role == "denominator" for m in kids)
        rebuilt_units.append(
            UnitRecord(
                source_unit_id=unit.source_unit_id,
                source_locator=unit.source_locator,
                divide=divide,
            )
        )
    units = rebuilt_units

    facts: list[FactRecord] = []
    for row in conn.execute(
        select(tables.xbrl_fact)
        .where(tables.xbrl_fact.c.semantic_projection_id == projection_id)
        .order_by(tables.xbrl_fact.c.id)
    ).mappings():
        require_decl(int(row["concept_declaration_id"]))
        context_locator = context_id_to_locator.get(int(row["context_id"]))
        if context_locator is None:
            raise SemanticProjectionConflict("fact context_id not in projection")
        unit_locator = None
        if row["unit_id"] is not None:
            unit_locator = unit_id_to_locator.get(int(row["unit_id"]))
            if unit_locator is None:
                raise SemanticProjectionConflict("fact unit_id not in projection")
        kind = row["resolved_value_kind"]
        text_value = row["resolved_value_text"]
        numeric = row["resolved_numeric"]
        if numeric is not None and not isinstance(numeric, Decimal):
            numeric = Decimal(str(numeric))
        resolved_kind, resolved_text, resolved_numeric = _validate_resolved_value_fields(
            kind, text_value, numeric
        )
        decl_record = decl_by_id[int(row["concept_declaration_id"])]
        resolved_type = None
        if resolved_text is not None or resolved_numeric is not None:
            resolved_type = decl_record.data_type
        cont = row["continuation_provenance"] or []
        facts.append(
            FactRecord(
                concept_qname=decl_qname_by_id[int(row["concept_declaration_id"])],
                context_locator=context_locator,
                source_locator=_load_locator_from_row(
                    document_uri=uri_for_binding(int(row["source_bundle_uri_binding_id"])),
                    scheme=row["source_locator_scheme"],
                    value=row["source_locator_value"],
                ),
                value_status=row["value_status"],
                is_nil=bool(row["is_nil"]),
                unit_locator=unit_locator,
                raw_lexical_value=row["raw_lexical_value"],
                resolved_text_value=resolved_text,
                resolved_numeric_value=resolved_numeric,
                resolved_value_kind=cast(ResolvedValueKind | None, resolved_kind),
                resolved_value_type=resolved_type,
                reported_decimals=row["reported_decimals"],
                reported_precision=row["reported_precision"],
                xml_lang=row["xml_lang"],
                format_qname=(
                    None
                    if row["format_local_name"] is None
                    else ExpandedQName(
                        namespace_uri=row["format_namespace_uri"],
                        local_name=row["format_local_name"],
                    )
                ),
                scale=row["scale"],
                sign=row["sign"],
                escape=row["escape"],
                continuation_provenance=tuple(SourceLocator.from_dict(item) for item in cont),
            )
        )

    relationships: list[RelationshipRecord] = []
    for row in conn.execute(
        select(tables.xbrl_relationship)
        .where(tables.xbrl_relationship.c.semantic_projection_id == projection_id)
        .order_by(tables.xbrl_relationship.c.id)
    ).mappings():
        relationships.append(
            RelationshipRecord(
                network_type=row["network_type"],
                link_role_uri=row["link_role_uri"],
                arcrole_uri=row["arcrole_uri"],
                source_concept=require_decl(int(row["source_concept_declaration_id"])),
                target_concept=require_decl(int(row["target_concept_declaration_id"])),
                source_locator=_load_locator_from_row(
                    document_uri=uri_for_binding(int(row["source_bundle_uri_binding_id"])),
                    scheme=row["source_locator_scheme"],
                    value=row["source_locator_value"],
                ),
                order=row["order_value"],
                weight=row["weight"],
                preferred_label_role=row["preferred_label_role"],
                target_role_uri=row["target_role_uri"],
                closed=row["closed"],
                usable=row["usable"],
                context_element=row["context_element"],
            )
        )

    labels: list[ConceptLabelRecord] = []
    for row in conn.execute(
        select(tables.concept_label)
        .where(tables.concept_label.c.semantic_projection_id == projection_id)
        .order_by(tables.concept_label.c.id)
    ).mappings():
        labels.append(
            ConceptLabelRecord(
                concept=require_decl(int(row["concept_declaration_id"])),
                link_role_uri=row["link_role_uri"],
                arcrole_uri=row["arcrole_uri"],
                text=row["text"],
                source_locator=_load_locator_from_row(
                    document_uri=uri_for_binding(int(row["resource_source_bundle_uri_binding_id"])),
                    scheme=row["resource_source_locator_scheme"],
                    value=row["resource_source_locator_value"],
                ),
                arc_locator=_load_locator_from_row(
                    document_uri=uri_for_binding(int(row["arc_source_bundle_uri_binding_id"])),
                    scheme=row["arc_source_locator_scheme"],
                    value=row["arc_source_locator_value"],
                ),
                resource_role_uri=row["resource_role_uri"],
                xml_lang=row["language"],
                order=row["order_value"],
            )
        )

    references: list[ConceptReferenceRecord] = []
    for row in conn.execute(
        select(tables.concept_reference)
        .where(tables.concept_reference.c.semantic_projection_id == projection_id)
        .order_by(tables.concept_reference.c.id)
    ).mappings():
        parts = tuple(
            ReferencePartRecord.from_dict(part) for part in (row["reference_parts"] or [])
        )
        references.append(
            ConceptReferenceRecord(
                concept=require_decl(int(row["concept_declaration_id"])),
                link_role_uri=row["link_role_uri"],
                arcrole_uri=row["arcrole_uri"],
                reference_parts=parts,
                source_locator=_load_locator_from_row(
                    document_uri=uri_for_binding(int(row["resource_source_bundle_uri_binding_id"])),
                    scheme=row["resource_source_locator_scheme"],
                    value=row["resource_source_locator_value"],
                ),
                arc_locator=_load_locator_from_row(
                    document_uri=uri_for_binding(int(row["arc_source_bundle_uri_binding_id"])),
                    scheme=row["arc_source_locator_scheme"],
                    value=row["arc_source_locator_value"],
                ),
                resource_role_uri=row["resource_role_uri"],
                order=row["order_value"],
            )
        )

    roles: list[RoleDeclarationRecord] = []
    for row in conn.execute(
        select(tables.role_declaration)
        .where(tables.role_declaration.c.semantic_projection_id == projection_id)
        .order_by(tables.role_declaration.c.id)
    ).mappings():
        roles.append(
            RoleDeclarationRecord(
                role_uri=row["role_uri"],
                definition=row["definition"],
                used_on=tuple(ExpandedQName.from_dict(q) for q in (row["used_on"] or [])),
                source_locator=_load_locator_from_row(
                    document_uri=uri_for_binding(int(row["source_bundle_uri_binding_id"])),
                    scheme=row["source_locator_scheme"],
                    value=row["source_locator_value"],
                ),
            )
        )
    arcroles: list[ArcroleDeclarationRecord] = []
    for row in conn.execute(
        select(tables.arcrole_declaration)
        .where(tables.arcrole_declaration.c.semantic_projection_id == projection_id)
        .order_by(tables.arcrole_declaration.c.id)
    ).mappings():
        arcroles.append(
            ArcroleDeclarationRecord(
                arcrole_uri=row["arcrole_uri"],
                definition=row["definition"],
                used_on=tuple(ExpandedQName.from_dict(q) for q in (row["used_on"] or [])),
                cycles_allowed=row["cycles_allowed"],
                source_locator=_load_locator_from_row(
                    document_uri=uri_for_binding(int(row["source_bundle_uri_binding_id"])),
                    scheme=row["source_locator_scheme"],
                    value=row["source_locator_value"],
                ),
            )
        )

    issues: list[SemanticIssueRecord] = []
    for row in conn.execute(
        select(tables.semantic_issue)
        .where(tables.semantic_issue.c.semantic_projection_id == projection_id)
        .order_by(tables.semantic_issue.c.id)
    ).mappings():
        ctx = dict(row["context"] or {})
        locator = None
        if "locator" in ctx:
            locator = SourceLocator.from_dict(ctx.pop("locator"))
        issues.append(
            SemanticIssueRecord(
                severity=row["severity"],
                code=row["code"],
                message=row["message"],
                locator=locator,
                context=ctx,
            )
        )

    data = SemanticProjectionData(
        projection_version=str(proj["projection_version"]),
        config_fingerprint=str(proj["semantic_config_fingerprint"]),
        engine_name="arelle",
        engine_version=str(proj["arelle_version"]),
        concept_declarations=tuple(
            sorted(decl_by_id.values(), key=lambda item: item.concept.sort_key())
        ),
        concept_labels=tuple(labels),
        concept_references=tuple(references),
        role_declarations=tuple(roles),
        arcrole_declarations=tuple(arcroles),
        contexts=tuple(contexts),
        context_dimensions=tuple(context_dimensions),
        units=tuple(units),
        unit_measures=tuple(unit_measures),
        facts=tuple(facts),
        relationships=tuple(relationships),
        issues=tuple(issues),
    )
    return data, str(proj["status"])


def list_network_relationships(
    conn: Connection,
    projection_id: int,
    *,
    network_type: str,
    link_role_uri: str,
) -> list[dict[str, Any]]:
    """Reconstruct effective network rows from persisted relationships (no Arelle)."""
    data, _status = load_semantic_projection(conn, projection_id)
    rows: list[dict[str, Any]] = []
    for rel in data.relationships:
        if rel.network_type != network_type or rel.link_role_uri != link_role_uri:
            continue
        rows.append(rel.to_dict())
    rows.sort(
        key=lambda item: (
            item.get("order") or "",
            item["source_concept"]["namespace_uri"] or "",
            item["source_concept"]["local_name"],
            item["target_concept"]["namespace_uri"] or "",
            item["target_concept"]["local_name"],
        )
    )
    return rows


__all__ = [
    "SemanticFailureResult",
    "SemanticProjectionConflict",
    "SemanticProjectionResult",
    "catalog_semantic_projection",
    "list_network_relationships",
    "load_semantic_projection",
    "record_semantic_projection_failure",
    "semantic_projection_equality_state",
]
