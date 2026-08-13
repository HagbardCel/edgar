"""SQL adapter: sync and query the Phase 2A metric registry materialization.

Caller owns the transaction for ``sync_registry`` and mutating helpers.
SQLAlchemy stays in this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from typing import cast as typing_cast

from sqlalchemy import Connection, and_, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from edgar.db import schema as tables
from edgar.metrics.registry import (
    ConceptDeclarationCitation,
    DefinitionConstraints,
    EvidenceCitation,
    ExpandedQNameRecord,
    FactCitation,
    LabelCitation,
    LoadedRegistry,
    MappingRuleRecord,
    MappingScope,
    MetricDefinitionRecord,
    MetricFamilyRecord,
    RawArtifactCitation,
    ReferenceCitation,
    RelationshipCitation,
    RuleState,
    SupersedesRef,
    fingerprint_definition,
    fingerprint_family,
    fingerprint_rule,
    rule_state,
    validate_registry,
)

# Transaction-scoped advisory lock for semantic-registry sync serialization.
ADVISORY_LOCK_KEY = 802_451_937_201_004


class MetricRegistryConflict(RuntimeError):
    """Persisted registry state conflicts with the incoming authoritative registry."""


@dataclass(frozen=True)
class SyncResult:
    registry_hash: str
    revision_id: int | None
    verified_noop: bool
    family_count: int
    definition_count: int
    rule_count: int


@dataclass(frozen=True)
class RegistryRevisionRow:
    id: int
    registry_hash: str
    registry_schema_version: int
    families_file_hash: str
    definitions_file_hash: str
    rules_file_hash: str
    synced_at: datetime


@dataclass(frozen=True)
class MappingRuleRow:
    rule: MappingRuleRecord
    state: RuleState
    rule_id: int


@dataclass(frozen=True)
class SourceFactOccurrence:
    fact_id: int
    semantic_projection_id: int
    concept_namespace_uri: str
    concept_local_name: str
    source_document_uri: str
    source_locator_scheme: str
    source_locator_value: str
    value_status: str
    is_nil: bool
    raw_lexical_value: str | None


def _jsonb_string_eq(column: Any, value: str) -> Any:
    """Compare a JSONB string-scalar column to a plain locator value."""
    return column == func.to_jsonb(value)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _acquire_advisory_lock(conn: Connection) -> None:
    conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADVISORY_LOCK_KEY})


def _scope_payload(scope: MappingScope) -> dict[str, Any]:
    return scope.model_dump(mode="json")


def _constraints_payload(constraints: DefinitionConstraints) -> dict[str, Any]:
    return constraints.model_dump(mode="json")


def _citations_payload(citations: Sequence[EvidenceCitation]) -> list[dict[str, Any]]:
    return [citation.model_dump(mode="json") for citation in citations]


def _qname_key(qname: ExpandedQNameRecord) -> tuple[str | None, str]:
    return (qname.namespace_uri, qname.local_name)


def resolve_concept_identities(
    conn: Connection,
    qnames: Sequence[ExpandedQNameRecord],
) -> dict[tuple[str | None, str], int]:
    """Lookup-only resolve of ``concept_identity`` rows. Never inserts."""
    unique = {_qname_key(q): q for q in qnames}
    if not unique:
        return {}

    out: dict[tuple[str | None, str], int] = {}
    for key, qname in unique.items():
        if qname.namespace_uri is None:
            raise MetricRegistryConflict(
                f"concept identity requires a namespace URI: {qname.local_name}"
            )
        row = conn.execute(
            select(tables.concept_identity.c.id)
            .where(tables.concept_identity.c.namespace_uri == qname.namespace_uri)
            .where(tables.concept_identity.c.local_name == qname.local_name)
        ).scalar_one_or_none()
        if row is None:
            raise MetricRegistryConflict(
                f"unknown concept_identity for {{{qname.namespace_uri}}}{qname.local_name}"
            )
        out[key] = int(row)
    return out


def _require_exactly_one(rows: Sequence[Any], *, label: str) -> Any:
    if len(rows) == 0:
        raise MetricRegistryConflict(f"evidence citation resolved to zero objects: {label}")
    if len(rows) > 1:
        raise MetricRegistryConflict(
            f"evidence citation resolved to {len(rows)} objects (expected exactly one): {label}"
        )
    return rows[0]


def _match_projection_citation(
    conn: Connection,
    citation: (
        ConceptDeclarationCitation
        | FactCitation
        | RelationshipCitation
        | LabelCitation
        | ReferenceCitation
    ),
) -> list[int]:
    """Return matching semantic_projection ids for a projection-backed citation base."""
    rows = (
        conn.execute(
            select(tables.semantic_projection.c.id)
            .select_from(
                tables.filing.join(
                    tables.filing_bundle,
                    tables.filing_bundle.c.filing_id == tables.filing.c.id,
                )
                .join(
                    tables.xbrl_report_input,
                    tables.xbrl_report_input.c.filing_bundle_id == tables.filing_bundle.c.id,
                )
                .join(
                    tables.semantic_projection,
                    tables.semantic_projection.c.xbrl_report_input_id
                    == tables.xbrl_report_input.c.id,
                )
            )
            .where(tables.filing.c.accession_number == citation.accession_number)
            .where(tables.filing_bundle.c.opaque_id == citation.filing_bundle_opaque_id)
            .where(tables.xbrl_report_input.c.ordinal == citation.xbrl_report_input_ordinal)
            .where(tables.semantic_projection.c.projection_version == citation.projection_version)
            .where(tables.semantic_projection.c.arelle_version == citation.arelle_version)
            .where(
                tables.semantic_projection.c.semantic_config_fingerprint
                == citation.semantic_config_fingerprint
            )
        )
        .scalars()
        .all()
    )
    return [int(row) for row in rows]


def _resolve_concept_declaration_citation(
    conn: Connection, citation: ConceptDeclarationCitation
) -> int:
    projection_ids = _match_projection_citation(conn, citation)
    if len(projection_ids) != 1:
        raise MetricRegistryConflict(
            "concept_declaration citation projection identity matched "
            f"{len(projection_ids)} projections (expected exactly one)"
        )
    projection_id = projection_ids[0]
    if citation.concept.namespace_uri is None:
        raise MetricRegistryConflict(
            "concept_declaration citation requires a concept namespace URI"
        )
    rows = (
        conn.execute(
            select(tables.concept_declaration.c.id)
            .select_from(
                tables.concept_declaration.join(
                    tables.concept_identity,
                    tables.concept_identity.c.id
                    == tables.concept_declaration.c.concept_identity_id,
                ).join(
                    tables.bundle_uri_binding,
                    tables.bundle_uri_binding.c.id
                    == tables.concept_declaration.c.source_bundle_uri_binding_id,
                )
            )
            .where(tables.concept_declaration.c.semantic_projection_id == projection_id)
            .where(tables.concept_identity.c.namespace_uri == citation.concept.namespace_uri)
            .where(tables.concept_identity.c.local_name == citation.concept.local_name)
            .where(tables.bundle_uri_binding.c.document_uri == citation.source_locator.document_uri)
            .where(
                tables.concept_declaration.c.source_locator_scheme == citation.source_locator.scheme
            )
            .where(_jsonb_string_eq(
                tables.concept_declaration.c.source_locator_value,
                citation.source_locator.value,
            ))
        )
        .scalars()
        .all()
    )
    row = _require_exactly_one(
        rows,
        label=(
            f"concept_declaration {{{citation.concept.namespace_uri}}}{citation.concept.local_name}"
        ),
    )
    return int(row)


def _resolve_fact_citation(conn: Connection, citation: FactCitation) -> int:
    projection_ids = _match_projection_citation(conn, citation)
    if len(projection_ids) != 1:
        raise MetricRegistryConflict(
            f"fact citation projection identity matched {len(projection_ids)} "
            "projections (expected exactly one)"
        )
    projection_id = projection_ids[0]
    if citation.concept.namespace_uri is None:
        raise MetricRegistryConflict("fact citation requires a concept namespace URI")
    rows = (
        conn.execute(
            select(tables.xbrl_fact.c.id)
            .select_from(
                tables.xbrl_fact.join(
                    tables.concept_declaration,
                    tables.concept_declaration.c.id == tables.xbrl_fact.c.concept_declaration_id,
                )
                .join(
                    tables.concept_identity,
                    tables.concept_identity.c.id
                    == tables.concept_declaration.c.concept_identity_id,
                )
                .join(
                    tables.bundle_uri_binding,
                    tables.bundle_uri_binding.c.id
                    == tables.xbrl_fact.c.source_bundle_uri_binding_id,
                )
            )
            .where(tables.xbrl_fact.c.semantic_projection_id == projection_id)
            .where(tables.concept_identity.c.namespace_uri == citation.concept.namespace_uri)
            .where(tables.concept_identity.c.local_name == citation.concept.local_name)
            .where(tables.bundle_uri_binding.c.document_uri == citation.source_locator.document_uri)
            .where(tables.xbrl_fact.c.source_locator_scheme == citation.source_locator.scheme)
            .where(_jsonb_string_eq(
                tables.xbrl_fact.c.source_locator_value, citation.source_locator.value
            ))
        )
        .scalars()
        .all()
    )
    return int(_require_exactly_one(rows, label=f"fact {citation.concept.local_name}"))


def _resolve_relationship_citation(conn: Connection, citation: RelationshipCitation) -> int:
    projection_ids = _match_projection_citation(conn, citation)
    if len(projection_ids) != 1:
        raise MetricRegistryConflict(
            "relationship citation projection identity matched "
            f"{len(projection_ids)} projections (expected exactly one)"
        )
    projection_id = projection_ids[0]
    source = citation.source_concept
    target = citation.target_concept
    if source.namespace_uri is None or target.namespace_uri is None:
        raise MetricRegistryConflict(
            "relationship citation requires namespace URIs for source and target concepts"
        )
    source_ci = tables.concept_identity.alias("source_ci")
    target_ci = tables.concept_identity.alias("target_ci")
    source_cd = tables.concept_declaration.alias("source_cd")
    target_cd = tables.concept_declaration.alias("target_cd")
    rows = (
        conn.execute(
            select(tables.xbrl_relationship.c.id)
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
                .join(
                    tables.bundle_uri_binding,
                    tables.bundle_uri_binding.c.id
                    == tables.xbrl_relationship.c.source_bundle_uri_binding_id,
                )
            )
            .where(tables.xbrl_relationship.c.semantic_projection_id == projection_id)
            .where(tables.xbrl_relationship.c.network_type == citation.network_type)
            .where(tables.xbrl_relationship.c.link_role_uri == citation.link_role_uri)
            .where(tables.xbrl_relationship.c.arcrole_uri == citation.arcrole_uri)
            .where(source_ci.c.namespace_uri == source.namespace_uri)
            .where(source_ci.c.local_name == source.local_name)
            .where(target_ci.c.namespace_uri == target.namespace_uri)
            .where(target_ci.c.local_name == target.local_name)
            .where(tables.bundle_uri_binding.c.document_uri == citation.source_locator.document_uri)
            .where(
                tables.xbrl_relationship.c.source_locator_scheme == citation.source_locator.scheme
            )
            .where(_jsonb_string_eq(
                tables.xbrl_relationship.c.source_locator_value, citation.source_locator.value
            ))
        )
        .scalars()
        .all()
    )
    return int(_require_exactly_one(rows, label="relationship citation"))


def _resolve_label_citation(conn: Connection, citation: LabelCitation) -> int:
    projection_ids = _match_projection_citation(conn, citation)
    if len(projection_ids) != 1:
        raise MetricRegistryConflict(
            f"label citation projection identity matched {len(projection_ids)} "
            "projections (expected exactly one)"
        )
    projection_id = projection_ids[0]
    if citation.concept.namespace_uri is None:
        raise MetricRegistryConflict("label citation requires a concept namespace URI")
    resource_binding = tables.bundle_uri_binding.alias("resource_binding")
    arc_binding = tables.bundle_uri_binding.alias("arc_binding")
    rows = (
        conn.execute(
            select(tables.concept_label.c.id)
            .select_from(
                tables.concept_label.join(
                    tables.concept_declaration,
                    tables.concept_declaration.c.id
                    == tables.concept_label.c.concept_declaration_id,
                )
                .join(
                    tables.concept_identity,
                    tables.concept_identity.c.id
                    == tables.concept_declaration.c.concept_identity_id,
                )
                .join(
                    resource_binding,
                    resource_binding.c.id
                    == tables.concept_label.c.resource_source_bundle_uri_binding_id,
                )
                .join(
                    arc_binding,
                    arc_binding.c.id == tables.concept_label.c.arc_source_bundle_uri_binding_id,
                )
            )
            .where(tables.concept_label.c.semantic_projection_id == projection_id)
            .where(tables.concept_identity.c.namespace_uri == citation.concept.namespace_uri)
            .where(tables.concept_identity.c.local_name == citation.concept.local_name)
            .where(tables.concept_label.c.link_role_uri == citation.link_role_uri)
            .where(tables.concept_label.c.arcrole_uri == citation.arcrole_uri)
            .where(
                tables.concept_label.c.resource_role_uri.is_not_distinct_from(
                    citation.resource_role_uri
                )
            )
            .where(tables.concept_label.c.language.is_not_distinct_from(citation.language))
            .where(resource_binding.c.document_uri == citation.source_locator.document_uri)
            .where(
                tables.concept_label.c.resource_source_locator_scheme
                == citation.source_locator.scheme
            )
            .where(_jsonb_string_eq(
                tables.concept_label.c.resource_source_locator_value,
                citation.source_locator.value,
            ))
            .where(arc_binding.c.document_uri == citation.arc_locator.document_uri)
            .where(tables.concept_label.c.arc_source_locator_scheme == citation.arc_locator.scheme)
            .where(_jsonb_string_eq(
                tables.concept_label.c.arc_source_locator_value, citation.arc_locator.value
            ))
        )
        .scalars()
        .all()
    )
    return int(_require_exactly_one(rows, label="label citation"))


def _resolve_reference_citation(conn: Connection, citation: ReferenceCitation) -> int:
    projection_ids = _match_projection_citation(conn, citation)
    if len(projection_ids) != 1:
        raise MetricRegistryConflict(
            "reference citation projection identity matched "
            f"{len(projection_ids)} projections (expected exactly one)"
        )
    projection_id = projection_ids[0]
    if citation.concept.namespace_uri is None:
        raise MetricRegistryConflict("reference citation requires a concept namespace URI")
    resource_binding = tables.bundle_uri_binding.alias("resource_binding")
    arc_binding = tables.bundle_uri_binding.alias("arc_binding")
    rows = (
        conn.execute(
            select(tables.concept_reference.c.id)
            .select_from(
                tables.concept_reference.join(
                    tables.concept_declaration,
                    tables.concept_declaration.c.id
                    == tables.concept_reference.c.concept_declaration_id,
                )
                .join(
                    tables.concept_identity,
                    tables.concept_identity.c.id
                    == tables.concept_declaration.c.concept_identity_id,
                )
                .join(
                    resource_binding,
                    resource_binding.c.id
                    == tables.concept_reference.c.resource_source_bundle_uri_binding_id,
                )
                .join(
                    arc_binding,
                    arc_binding.c.id == tables.concept_reference.c.arc_source_bundle_uri_binding_id,
                )
            )
            .where(tables.concept_reference.c.semantic_projection_id == projection_id)
            .where(tables.concept_identity.c.namespace_uri == citation.concept.namespace_uri)
            .where(tables.concept_identity.c.local_name == citation.concept.local_name)
            .where(tables.concept_reference.c.link_role_uri == citation.link_role_uri)
            .where(tables.concept_reference.c.arcrole_uri == citation.arcrole_uri)
            .where(
                tables.concept_reference.c.resource_role_uri.is_not_distinct_from(
                    citation.resource_role_uri
                )
            )
            .where(resource_binding.c.document_uri == citation.source_locator.document_uri)
            .where(
                tables.concept_reference.c.resource_source_locator_scheme
                == citation.source_locator.scheme
            )
            .where(_jsonb_string_eq(
                tables.concept_reference.c.resource_source_locator_value,
                citation.source_locator.value,
            ))
            .where(arc_binding.c.document_uri == citation.arc_locator.document_uri)
            .where(
                tables.concept_reference.c.arc_source_locator_scheme == citation.arc_locator.scheme
            )
            .where(_jsonb_string_eq(
                tables.concept_reference.c.arc_source_locator_value, citation.arc_locator.value
            ))
        )
        .scalars()
        .all()
    )
    return int(_require_exactly_one(rows, label="reference citation"))


def _resolve_raw_artifact_citation(conn: Connection, citation: RawArtifactCitation) -> int:
    stmt = (
        select(tables.bundle_artifact.c.id)
        .select_from(
            tables.filing.join(
                tables.filing_bundle,
                tables.filing_bundle.c.filing_id == tables.filing.c.id,
            )
            .join(
                tables.bundle_artifact,
                tables.bundle_artifact.c.filing_bundle_id == tables.filing_bundle.c.id,
            )
            .join(
                tables.content_object,
                tables.content_object.c.id == tables.bundle_artifact.c.content_object_id,
            )
        )
        .where(tables.filing.c.accession_number == citation.accession_number)
        .where(tables.filing_bundle.c.opaque_id == citation.filing_bundle_opaque_id)
        .where(tables.bundle_artifact.c.logical_path == citation.logical_path)
        .where(tables.content_object.c.sha256 == citation.artifact_sha256)
    )
    if citation.document_uri is not None:
        stmt = stmt.join(
            tables.bundle_uri_binding,
            and_(
                tables.bundle_uri_binding.c.bundle_artifact_id == tables.bundle_artifact.c.id,
                tables.bundle_uri_binding.c.filing_bundle_id == tables.filing_bundle.c.id,
            ),
        ).where(tables.bundle_uri_binding.c.document_uri == citation.document_uri)
    rows = conn.execute(stmt).scalars().all()
    return int(_require_exactly_one(rows, label=f"raw_artifact {citation.logical_path}"))


def resolve_evidence_citations(
    conn: Connection,
    citations: Sequence[EvidenceCitation],
) -> list[int]:
    """Resolve each citation to exactly one source object id (citation order)."""
    resolved: list[int] = []
    for citation in citations:
        if isinstance(citation, ConceptDeclarationCitation):
            resolved.append(_resolve_concept_declaration_citation(conn, citation))
        elif isinstance(citation, FactCitation):
            resolved.append(_resolve_fact_citation(conn, citation))
        elif isinstance(citation, RelationshipCitation):
            resolved.append(_resolve_relationship_citation(conn, citation))
        elif isinstance(citation, LabelCitation):
            resolved.append(_resolve_label_citation(conn, citation))
        elif isinstance(citation, ReferenceCitation):
            resolved.append(_resolve_reference_citation(conn, citation))
        elif isinstance(citation, RawArtifactCitation):
            resolved.append(_resolve_raw_artifact_citation(conn, citation))
        else:
            raise MetricRegistryConflict(f"unsupported evidence citation kind: {citation!r}")
    return resolved


def get_latest_revision(conn: Connection) -> RegistryRevisionRow | None:
    """Return the revision with the highest id, if any."""
    row = (
        conn.execute(
            select(tables.semantic_registry_revision)
            .order_by(tables.semantic_registry_revision.c.id.desc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return RegistryRevisionRow(
        id=int(row["id"]),
        registry_hash=str(row["registry_hash"]),
        registry_schema_version=int(row["registry_schema_version"]),
        families_file_hash=str(row["families_file_hash"]),
        definitions_file_hash=str(row["definitions_file_hash"]),
        rules_file_hash=str(row["rules_file_hash"]),
        synced_at=row["synced_at"],
    )


def load_families(
    conn: Connection,
    *,
    registry_schema_version: int,
) -> tuple[MetricFamilyRecord, ...]:
    """Reconstruct family records from current DB rows (no surrogate ids)."""
    id_to_code = {
        int(row["id"]): str(row["code"])
        for row in conn.execute(
            select(tables.metric_family.c.id, tables.metric_family.c.code)
        ).mappings()
    }
    records: list[MetricFamilyRecord] = []
    for row in conn.execute(
        select(
            tables.metric_family.c.code,
            tables.metric_family.c.name,
            tables.metric_family.c.description,
            tables.metric_family.c.parent_family_id,
            tables.metric_family.c.family_hash,
        ).order_by(tables.metric_family.c.code)
    ).mappings():
        parent_id = row["parent_family_id"]
        parent_code = None if parent_id is None else id_to_code[int(parent_id)]
        family = MetricFamilyRecord(
            code=str(row["code"]),
            name=str(row["name"]),
            description=str(row["description"]),
            parent_code=parent_code,
        )
        stored_hash = str(row["family_hash"])
        recomputed = fingerprint_family(registry_schema_version, family)
        if stored_hash != recomputed:
            raise MetricRegistryConflict(
                f"metric_family {family.code!r}: stored family_hash does not match "
                "reconstructed canonical hash"
            )
        records.append(family)
    return tuple(records)


def load_definitions(conn: Connection) -> tuple[MetricDefinitionRecord, ...]:
    """Reconstruct definition records from current DB rows (no surrogate ids)."""
    family_codes = {
        int(row["id"]): str(row["code"])
        for row in conn.execute(
            select(tables.metric_family.c.id, tables.metric_family.c.code)
        ).mappings()
    }
    records: list[MetricDefinitionRecord] = []
    for row in conn.execute(
        select(tables.metric_definition).order_by(
            tables.metric_definition.c.metric_code,
            tables.metric_definition.c.definition_version,
        )
    ).mappings():
        family_id = int(row["family_id"])
        if family_id not in family_codes:
            raise MetricRegistryConflict(
                f"metric_definition {row['metric_code']} v{row['definition_version']}: "
                f"unknown family_id {family_id}"
            )
        constraints = DefinitionConstraints.model_validate(row["constraints"])
        defn = MetricDefinitionRecord(
            definition_schema_version=int(row["definition_schema_version"]),
            metric_code=str(row["metric_code"]),
            definition_version=int(row["definition_version"]),
            family_code=family_codes[family_id],
            name=str(row["name"]),
            economic_definition=str(row["economic_definition"]),
            accounting_basis=str(row["accounting_basis"]),
            period_type=typing_cast(Any, row["period_type"]),
            value_kind=str(row["value_kind"]),
            unit_kind=str(row["unit_kind"]),
            entity_scope=str(row["entity_scope"]),
            sign_convention=str(row["sign_convention"]),
            constraints=constraints,
        )
        stored_hash = str(row["definition_hash"])
        recomputed = fingerprint_definition(defn)
        if stored_hash != recomputed:
            raise MetricRegistryConflict(
                f"metric_definition {defn.metric_code} v{defn.definition_version}: "
                "stored definition_hash does not match reconstructed canonical hash"
            )
        records.append(defn)
    return tuple(records)


def load_rules(conn: Connection) -> tuple[MappingRuleRecord, ...]:
    """Reconstruct mapping-rule records from current DB rows (no surrogate ids)."""
    concept_rows = {
        int(row["id"]): ExpandedQNameRecord(
            namespace_uri=str(row["namespace_uri"]),
            local_name=str(row["local_name"]),
        )
        for row in conn.execute(
            select(
                tables.concept_identity.c.id,
                tables.concept_identity.c.namespace_uri,
                tables.concept_identity.c.local_name,
            )
        ).mappings()
    }
    definition_keys = {
        int(row["id"]): (str(row["metric_code"]), int(row["definition_version"]))
        for row in conn.execute(
            select(
                tables.metric_definition.c.id,
                tables.metric_definition.c.metric_code,
                tables.metric_definition.c.definition_version,
            )
        ).mappings()
    }
    rule_key_by_id = {
        int(row["id"]): str(row["rule_key"])
        for row in conn.execute(
            select(tables.metric_mapping_rule.c.id, tables.metric_mapping_rule.c.rule_key)
        ).mappings()
    }
    records: list[MappingRuleRecord] = []
    for row in conn.execute(
        select(tables.metric_mapping_rule).order_by(tables.metric_mapping_rule.c.rule_key)
    ).mappings():
        concept_id = int(row["source_concept_identity_id"])
        if concept_id not in concept_rows:
            raise MetricRegistryConflict(
                f"metric_mapping_rule {row['rule_key']!r}: unknown source_concept_identity_id"
            )
        target_id = int(row["target_metric_definition_id"])
        if target_id not in definition_keys:
            raise MetricRegistryConflict(
                f"metric_mapping_rule {row['rule_key']!r}: unknown target_metric_definition_id"
            )
        target_code, target_version = definition_keys[target_id]
        supersedes_id = row["supersedes_rule_id"]
        supersedes = None
        if supersedes_id is not None:
            predecessor_key = rule_key_by_id.get(int(supersedes_id))
            if predecessor_key is None:
                raise MetricRegistryConflict(
                    f"metric_mapping_rule {row['rule_key']!r}: unknown supersedes_rule_id"
                )
            supersedes = SupersedesRef(rule_key=predecessor_key)
        scope_obj = row["scope"]
        if not isinstance(scope_obj, dict):
            raise MetricRegistryConflict(
                f"metric_mapping_rule {row['rule_key']!r}: scope must be a JSON object"
            )
        if scope_obj.get("kind") != row["scope_kind"]:
            raise MetricRegistryConflict(
                f"metric_mapping_rule {row['rule_key']!r}: scope_kind does not match scope.kind"
            )
        citations_raw = row["evidence_citations"]
        if not isinstance(citations_raw, list):
            raise MetricRegistryConflict(
                f"metric_mapping_rule {row['rule_key']!r}: evidence_citations must be an array"
            )
        rule = MappingRuleRecord.model_validate(
            {
                "rule_schema_version": int(row["rule_schema_version"]),
                "rule_key": str(row["rule_key"]),
                "source_concept": concept_rows[concept_id].model_dump(mode="python"),
                "target_metric_code": target_code,
                "target_definition_version": target_version,
                "relationship_type": row["relationship_type"],
                "scope_kind": row["scope_kind"],
                "scope": scope_obj,
                "confidence_tier": row["confidence_tier"],
                "rationale": str(row["rationale"]),
                "evidence_snapshot": row["evidence_snapshot"],
                "evidence_citations": citations_raw,
                "reviewed_by": str(row["reviewed_by"]),
                "reviewed_at": row["reviewed_at"],
                "supersedes": None if supersedes is None else {"rule_key": supersedes.rule_key},
            }
        )
        stored_hash = str(row["rule_hash"])
        recomputed = fingerprint_rule(rule)
        if stored_hash != recomputed:
            raise MetricRegistryConflict(
                f"metric_mapping_rule {rule.rule_key!r}: stored rule_hash does not match "
                "reconstructed canonical hash"
            )
        records.append(rule)
    return tuple(records)


def verify_materialization(conn: Connection, registry: LoadedRegistry) -> None:
    """Reconstruct DB registry state, rehash, and compare to ``registry``."""
    families = load_families(conn, registry_schema_version=registry.registry_schema_version)
    definitions = load_definitions(conn)
    rules = load_rules(conn)

    incoming_family_codes = {family.code for family in registry.families}
    db_family_codes = {family.code for family in families}
    if incoming_family_codes != db_family_codes:
        raise MetricRegistryConflict(
            "metric_family key set mismatch: "
            f"missing={sorted(incoming_family_codes - db_family_codes)} "
            f"extra={sorted(db_family_codes - incoming_family_codes)}"
        )
    incoming_families = {family.code: family for family in registry.families}
    for family in families:
        authoritative = incoming_families[family.code]
        if family != authoritative:
            raise MetricRegistryConflict(
                f"metric_family {family.code!r}: reconstructed record differs from registry"
            )
        if fingerprint_family(registry.registry_schema_version, family) != fingerprint_family(
            registry.registry_schema_version, authoritative
        ):
            raise MetricRegistryConflict(
                f"metric_family {family.code!r}: hash mismatch against authoritative registry"
            )

    incoming_defn_keys = {(d.metric_code, d.definition_version) for d in registry.definitions}
    db_defn_keys = {(d.metric_code, d.definition_version) for d in definitions}
    if incoming_defn_keys != db_defn_keys:
        raise MetricRegistryConflict(
            "metric_definition key set mismatch: "
            f"missing={sorted(incoming_defn_keys - db_defn_keys)} "
            f"extra={sorted(db_defn_keys - incoming_defn_keys)}"
        )
    incoming_definitions = {(d.metric_code, d.definition_version): d for d in registry.definitions}
    for defn in definitions:
        key = (defn.metric_code, defn.definition_version)
        authoritative = incoming_definitions[key]
        if fingerprint_definition(defn) != fingerprint_definition(authoritative):
            raise MetricRegistryConflict(
                f"metric_definition {key}: reconstructed hash differs from authoritative registry"
            )

    incoming_rule_keys = {rule.rule_key for rule in registry.rules}
    db_rule_keys = {rule.rule_key for rule in rules}
    if incoming_rule_keys != db_rule_keys:
        raise MetricRegistryConflict(
            "metric_mapping_rule key set mismatch: "
            f"missing={sorted(incoming_rule_keys - db_rule_keys)} "
            f"extra={sorted(db_rule_keys - incoming_rule_keys)}"
        )
    incoming_rules = {rule.rule_key: rule for rule in registry.rules}
    for rule in rules:
        authoritative = incoming_rules[rule.rule_key]
        if fingerprint_rule(rule) != fingerprint_rule(authoritative):
            raise MetricRegistryConflict(
                f"metric_mapping_rule {rule.rule_key!r}: reconstructed hash differs from "
                "authoritative registry"
            )


def _load_family_rows(conn: Connection) -> dict[str, Any]:
    return {str(row["code"]): row for row in conn.execute(select(tables.metric_family)).mappings()}


def _load_definition_hash_rows(conn: Connection) -> dict[tuple[str, int], Any]:
    return {
        (str(row["metric_code"]), int(row["definition_version"])): row
        for row in conn.execute(select(tables.metric_definition)).mappings()
    }


def _load_rule_hash_rows(conn: Connection) -> dict[str, Any]:
    return {
        str(row["rule_key"]): row
        for row in conn.execute(select(tables.metric_mapping_rule)).mappings()
    }


def _upsert_families(conn: Connection, registry: LoadedRegistry) -> dict[str, int]:
    existing = _load_family_rows(conn)
    incoming_codes = {family.code for family in registry.families}
    removed = set(existing) - incoming_codes
    if removed:
        raise MetricRegistryConflict(f"metric_family codes cannot be removed: {sorted(removed)}")

    for family in registry.families:
        family_hash = fingerprint_family(registry.registry_schema_version, family)
        if family.code in existing:
            conn.execute(
                update(tables.metric_family)
                .where(tables.metric_family.c.code == family.code)
                .values(
                    name=family.name,
                    description=family.description,
                    family_hash=family_hash,
                )
            )
        else:
            conn.execute(
                insert(tables.metric_family).values(
                    code=family.code,
                    name=family.name,
                    description=family.description,
                    parent_family_id=None,
                    family_hash=family_hash,
                )
            )

    code_to_id = {
        str(row["code"]): int(row["id"])
        for row in conn.execute(
            select(tables.metric_family.c.id, tables.metric_family.c.code)
        ).mappings()
    }
    for family in registry.families:
        parent_id = None if family.parent_code is None else code_to_id[family.parent_code]
        conn.execute(
            update(tables.metric_family)
            .where(tables.metric_family.c.id == code_to_id[family.code])
            .values(parent_family_id=parent_id)
        )
    return code_to_id


def _insert_definitions(
    conn: Connection,
    registry: LoadedRegistry,
    family_ids: Mapping[str, int],
) -> dict[tuple[str, int], int]:
    existing = _load_definition_hash_rows(conn)
    incoming_keys = {(d.metric_code, d.definition_version) for d in registry.definitions}
    extra = set(existing) - incoming_keys
    if extra:
        raise MetricRegistryConflict(
            f"unexpected extra metric_definition rows in DB: {sorted(extra)}"
        )

    for defn in registry.definitions:
        key = (defn.metric_code, defn.definition_version)
        expected_hash = fingerprint_definition(defn)
        if key in existing:
            stored_hash = str(existing[key]["definition_hash"])
            if stored_hash != expected_hash:
                raise MetricRegistryConflict(
                    f"immutable metric_definition {key} content mutation "
                    f"(stored_hash={stored_hash}, incoming_hash={expected_hash})"
                )
            continue
        conn.execute(
            insert(tables.metric_definition).values(
                metric_code=defn.metric_code,
                definition_version=defn.definition_version,
                definition_schema_version=defn.definition_schema_version,
                family_id=family_ids[defn.family_code],
                name=defn.name,
                economic_definition=defn.economic_definition,
                accounting_basis=defn.accounting_basis,
                period_type=defn.period_type,
                value_kind=defn.value_kind,
                unit_kind=defn.unit_kind,
                entity_scope=defn.entity_scope,
                sign_convention=defn.sign_convention,
                constraints=_constraints_payload(defn.constraints),
                definition_hash=expected_hash,
            )
        )

    return {
        (str(row["metric_code"]), int(row["definition_version"])): int(row["id"])
        for row in conn.execute(
            select(
                tables.metric_definition.c.id,
                tables.metric_definition.c.metric_code,
                tables.metric_definition.c.definition_version,
            )
        ).mappings()
    }


def _insert_rules(
    conn: Connection,
    registry: LoadedRegistry,
    *,
    concept_ids: Mapping[tuple[str | None, str], int],
    definition_ids: Mapping[tuple[str, int], int],
) -> None:
    existing = _load_rule_hash_rows(conn)
    incoming_keys = {rule.rule_key for rule in registry.rules}
    extra = set(existing) - incoming_keys
    if extra:
        raise MetricRegistryConflict(
            f"unexpected extra metric_mapping_rule rows in DB: {sorted(extra)}"
        )

    # Insert new rules first without supersedes FK, then patch supersedes.
    pending_supersedes: list[tuple[str, str]] = []
    for rule in registry.rules:
        expected_hash = fingerprint_rule(rule)
        if rule.rule_key in existing:
            stored_hash = str(existing[rule.rule_key]["rule_hash"])
            if stored_hash != expected_hash:
                raise MetricRegistryConflict(
                    f"immutable metric_mapping_rule {rule.rule_key!r} content mutation "
                    f"(stored_hash={stored_hash}, incoming_hash={expected_hash})"
                )
            continue

        resolve_evidence_citations(conn, rule.evidence_citations)
        concept_id = concept_ids[_qname_key(rule.source_concept)]
        target_id = definition_ids[(rule.target_metric_code, rule.target_definition_version)]
        conn.execute(
            insert(tables.metric_mapping_rule).values(
                rule_key=rule.rule_key,
                rule_schema_version=rule.rule_schema_version,
                source_concept_identity_id=concept_id,
                target_metric_definition_id=target_id,
                relationship_type=rule.relationship_type,
                scope_kind=rule.scope_kind,
                scope=_scope_payload(rule.scope),
                confidence_tier=rule.confidence_tier,
                rationale=rule.rationale,
                evidence_snapshot=dict(rule.evidence_snapshot.root),
                evidence_citations=_citations_payload(rule.evidence_citations),
                reviewed_by=rule.reviewed_by,
                reviewed_at=rule.reviewed_at,
                supersedes_rule_id=None,
                rule_hash=expected_hash,
            )
        )
        if rule.supersedes is not None:
            pending_supersedes.append((rule.rule_key, rule.supersedes.rule_key))

    rule_ids = {
        str(row["rule_key"]): int(row["id"])
        for row in conn.execute(
            select(tables.metric_mapping_rule.c.id, tables.metric_mapping_rule.c.rule_key)
        ).mappings()
    }
    for rule_key, predecessor_key in pending_supersedes:
        if predecessor_key not in rule_ids:
            raise MetricRegistryConflict(
                f"rule {rule_key!r}: unknown supersedes target {predecessor_key!r}"
            )
        conn.execute(
            update(tables.metric_mapping_rule)
            .where(tables.metric_mapping_rule.c.rule_key == rule_key)
            .values(supersedes_rule_id=rule_ids[predecessor_key])
        )


def sync_registry(conn: Connection, registry: LoadedRegistry) -> SyncResult:
    """Materialize ``registry`` into PostgreSQL under an advisory transaction lock."""
    validate_registry(registry)
    _acquire_advisory_lock(conn)

    latest = get_latest_revision(conn)
    if latest is not None and latest.registry_hash == registry.registry_hash:
        verify_materialization(conn, registry)
        return SyncResult(
            registry_hash=registry.registry_hash,
            revision_id=latest.id,
            verified_noop=True,
            family_count=len(registry.families),
            definition_count=len(registry.definitions),
            rule_count=len(registry.rules),
        )

    concept_ids = resolve_concept_identities(conn, [rule.source_concept for rule in registry.rules])
    # Resolve citations for all rules (including already-persisted ones) so sync
    # fails closed when cited evidence disappears.
    for rule in registry.rules:
        resolve_evidence_citations(conn, rule.evidence_citations)

    family_ids = _upsert_families(conn, registry)
    definition_ids = _insert_definitions(conn, registry, family_ids)
    _insert_rules(
        conn,
        registry,
        concept_ids=concept_ids,
        definition_ids=definition_ids,
    )

    # Final materialization gate before appending the revision.
    verify_materialization(conn, registry)

    revision_id = int(
        conn.execute(
            insert(tables.semantic_registry_revision)
            .values(
                registry_hash=registry.registry_hash,
                registry_schema_version=registry.registry_schema_version,
                families_file_hash=registry.families_file_hash,
                definitions_file_hash=registry.definitions_file_hash,
                rules_file_hash=registry.rules_file_hash,
                synced_at=_utcnow(),
            )
            .returning(tables.semantic_registry_revision.c.id)
        ).scalar_one()
    )
    return SyncResult(
        registry_hash=registry.registry_hash,
        revision_id=revision_id,
        verified_noop=False,
        family_count=len(registry.families),
        definition_count=len(registry.definitions),
        rule_count=len(registry.rules),
    )


def list_metrics(conn: Connection) -> tuple[MetricDefinitionRecord, ...]:
    return load_definitions(conn)


def get_metric(
    conn: Connection,
    metric_code: str,
    *,
    definition_version: int | None = None,
) -> tuple[MetricDefinitionRecord, ...]:
    definitions = [defn for defn in load_definitions(conn) if defn.metric_code == metric_code]
    if definition_version is not None:
        definitions = [d for d in definitions if d.definition_version == definition_version]
    return tuple(definitions)


def list_mappings(
    conn: Connection,
    *,
    metric_code: str | None = None,
    concept_namespace_uri: str | None = None,
    concept_local_name: str | None = None,
    cik: str | None = None,
    relationship_type: str | None = None,
) -> tuple[MappingRuleRow, ...]:
    rules = load_rules(conn)
    by_key = {rule.rule_key: rule for rule in rules}
    out: list[MappingRuleRow] = []
    rule_ids = {
        str(row["rule_key"]): int(row["id"])
        for row in conn.execute(
            select(tables.metric_mapping_rule.c.id, tables.metric_mapping_rule.c.rule_key)
        ).mappings()
    }
    for rule in rules:
        if metric_code is not None and rule.target_metric_code != metric_code:
            continue
        if concept_local_name is not None and rule.source_concept.local_name != concept_local_name:
            continue
        if (
            concept_namespace_uri is not None
            and rule.source_concept.namespace_uri != concept_namespace_uri
        ):
            continue
        if relationship_type is not None and rule.relationship_type != relationship_type:
            continue
        if cik is not None:
            scope = rule.scope
            scope_cik = getattr(scope, "cik", None)
            if scope_cik != cik:
                continue
        out.append(
            MappingRuleRow(
                rule=rule,
                state=rule_state(rule.rule_key, by_key),
                rule_id=rule_ids[rule.rule_key],
            )
        )
    return tuple(out)


def get_mapping(conn: Connection, rule_key: str) -> MappingRuleRow | None:
    rules = load_rules(conn)
    by_key = {rule.rule_key: rule for rule in rules}
    rule = by_key.get(rule_key)
    if rule is None:
        return None
    rule_id = conn.execute(
        select(tables.metric_mapping_rule.c.id).where(
            tables.metric_mapping_rule.c.rule_key == rule_key
        )
    ).scalar_one()
    return MappingRuleRow(
        rule=rule,
        state=rule_state(rule_key, by_key),
        rule_id=int(rule_id),
    )


def get_supersession_chain(conn: Connection, rule_key: str) -> tuple[MappingRuleRecord, ...]:
    """Return predecessor chain (oldest first) ending at ``rule_key``."""
    rules = {rule.rule_key: rule for rule in load_rules(conn)}
    if rule_key not in rules:
        raise MetricRegistryConflict(f"unknown mapping rule_key: {rule_key!r}")
    chain: list[MappingRuleRecord] = []
    seen: set[str] = set()
    current = rule_key
    while True:
        if current in seen:
            raise MetricRegistryConflict(f"supersession cycle involving {current!r}")
        seen.add(current)
        rule = rules[current]
        chain.append(rule)
        if rule.supersedes is None:
            break
        predecessor = rule.supersedes.rule_key
        if predecessor not in rules:
            raise MetricRegistryConflict(
                f"rule {current!r} supersedes unknown rule {predecessor!r}"
            )
        current = predecessor
    chain.reverse()
    return tuple(chain)


def query_source_fact_occurrences(
    conn: Connection,
    *,
    namespace_uri: str,
    local_name: str,
    limit: int | None = None,
) -> tuple[SourceFactOccurrence, ...]:
    """Return every fact occurrence for the given concept identity (no aggregation)."""
    stmt = (
        select(
            tables.xbrl_fact.c.id.label("fact_id"),
            tables.xbrl_fact.c.semantic_projection_id,
            tables.concept_identity.c.namespace_uri,
            tables.concept_identity.c.local_name,
            tables.bundle_uri_binding.c.document_uri,
            tables.xbrl_fact.c.source_locator_scheme,
            tables.xbrl_fact.c.source_locator_value,
            tables.xbrl_fact.c.value_status,
            tables.xbrl_fact.c.is_nil,
            tables.xbrl_fact.c.raw_lexical_value,
        )
        .select_from(
            tables.xbrl_fact.join(
                tables.concept_declaration,
                tables.concept_declaration.c.id == tables.xbrl_fact.c.concept_declaration_id,
            )
            .join(
                tables.concept_identity,
                tables.concept_identity.c.id == tables.concept_declaration.c.concept_identity_id,
            )
            .join(
                tables.bundle_uri_binding,
                tables.bundle_uri_binding.c.id == tables.xbrl_fact.c.source_bundle_uri_binding_id,
            )
        )
        .where(tables.concept_identity.c.namespace_uri == namespace_uri)
        .where(tables.concept_identity.c.local_name == local_name)
        .order_by(tables.xbrl_fact.c.id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    occurrences: list[SourceFactOccurrence] = []
    for row in conn.execute(stmt).mappings():
        locator_value = row["source_locator_value"]
        if not isinstance(locator_value, str):
            raise MetricRegistryConflict(
                f"xbrl_fact id={row['fact_id']}: source_locator_value must be a JSON string"
            )
        occurrences.append(
            SourceFactOccurrence(
                fact_id=int(row["fact_id"]),
                semantic_projection_id=int(row["semantic_projection_id"]),
                concept_namespace_uri=str(row["namespace_uri"]),
                concept_local_name=str(row["local_name"]),
                source_document_uri=str(row["document_uri"]),
                source_locator_scheme=str(row["source_locator_scheme"]),
                source_locator_value=locator_value,
                value_status=str(row["value_status"]),
                is_nil=bool(row["is_nil"]),
                raw_lexical_value=(
                    None if row["raw_lexical_value"] is None else str(row["raw_lexical_value"])
                ),
            )
        )
    return tuple(occurrences)
