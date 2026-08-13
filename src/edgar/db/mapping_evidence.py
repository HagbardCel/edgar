"""Pinned projection evidence resolution for mappings explain (Phase 2A)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, select

from edgar.db import schema as tables
from edgar.db.catalog import load_bundle
from edgar.domain.bundle import bundle_fingerprint
from edgar.metrics.registry import ProjectionConceptEvidence


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


@dataclass(frozen=True)
class ExplainEnrichment:
    pinned: PinnedConceptEvidence
    labels: tuple[dict[str, Any], ...]
    references: tuple[dict[str, Any], ...]
    presentation_neighbors: tuple[dict[str, Any], ...]
    calculation_neighbors: tuple[dict[str, Any], ...]
    definition_neighbors: tuple[dict[str, Any], ...]
    fact_occurrences: tuple[dict[str, Any], ...]


def _require_one(rows: Sequence[Any], *, label: str) -> Any:
    if len(rows) != 1:
        raise MappingEvidenceError(f"{label}: expected exactly one match, got {len(rows)}")
    return rows[0]


def _find_bundle_id_by_fingerprint(
    conn: Connection,
    *,
    accession: str,
    fingerprint: str,
) -> int:
    rows = (
        conn.execute(
            select(tables.filing_bundle.c.id)
            .select_from(
                tables.filing_bundle.join(
                    tables.filing, tables.filing.c.id == tables.filing_bundle.c.filing_id
                )
            )
            .where(tables.filing.c.accession_number == accession)
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
    return int(_require_one(matches, label=f"bundle_fingerprint {fingerprint}"))


def _match_semantic_projection(
    conn: Connection,
    *,
    bundle_id: int,
    projection_version: str,
    arelle_version: str,
    semantic_config_fingerprint: str,
) -> int:
    rows = (
        conn.execute(
            select(tables.semantic_projection.c.id)
            .select_from(
                tables.xbrl_report_input.join(
                    tables.semantic_projection,
                    tables.semantic_projection.c.xbrl_report_input_id
                    == tables.xbrl_report_input.c.id,
                )
            )
            .where(tables.xbrl_report_input.c.filing_bundle_id == bundle_id)
            .where(tables.semantic_projection.c.projection_version == projection_version)
            .where(tables.semantic_projection.c.arelle_version == arelle_version)
            .where(
                tables.semantic_projection.c.semantic_config_fingerprint
                == semantic_config_fingerprint
            )
        )
        .scalars()
        .all()
    )
    return int(
        _require_one(
            [int(r) for r in rows],
            label="semantic projection identity",
        )
    )


def resolve_pinned_concept(
    conn: Connection,
    evidence: ProjectionConceptEvidence,
) -> PinnedConceptEvidence:
    if evidence.concept.namespace_uri is None:
        raise MappingEvidenceError("evidence concept requires namespace_uri")
    bundle_id = _find_bundle_id_by_fingerprint(
        conn,
        accession=evidence.accession_number,
        fingerprint=evidence.bundle_fingerprint,
    )
    projection_id = _match_semantic_projection(
        conn,
        bundle_id=bundle_id,
        projection_version=evidence.projection_version,
        arelle_version=evidence.arelle_version,
        semantic_config_fingerprint=evidence.semantic_config_fingerprint,
    )
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
        .where(tables.concept_identity.c.namespace_uri == evidence.concept.namespace_uri)
        .where(tables.concept_identity.c.local_name == evidence.concept.local_name)
    ).all()
    cd_id, ci_id, ns, local = _require_one(rows, label="concept declaration")
    return PinnedConceptEvidence(
        bundle_id=bundle_id,
        semantic_projection_id=projection_id,
        concept_declaration_id=int(cd_id),
        concept_identity_id=int(ci_id),
        namespace_uri=str(ns),
        local_name=str(local),
    )


def _relationship_neighbors(
    conn: Connection,
    *,
    projection_id: int,
    concept_declaration_id: int,
    network_type: str,
) -> tuple[dict[str, Any], ...]:
    source_cd = tables.concept_declaration.alias("source_cd")
    target_cd = tables.concept_declaration.alias("target_cd")
    source_ci = tables.concept_identity.alias("source_ci")
    target_ci = tables.concept_identity.alias("target_ci")
    rows = conn.execute(
        select(
            tables.xbrl_relationship.c.link_role_uri,
            tables.xbrl_relationship.c.arcrole_uri,
            source_ci.c.namespace_uri,
            source_ci.c.local_name,
            target_ci.c.namespace_uri,
            target_ci.c.local_name,
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
    return tuple(
        {
            "link_role_uri": row.link_role_uri,
            "arcrole_uri": row.arcrole_uri,
            "source": {"namespace_uri": row[2], "local_name": row[3]},
            "target": {"namespace_uri": row[4], "local_name": row[5]},
        }
        for row in rows
    )


def enrich_pinned_evidence(
    conn: Connection,
    pinned: PinnedConceptEvidence,
) -> ExplainEnrichment:
    labels = conn.execute(
        select(
            tables.concept_label.c.link_role_uri,
            tables.concept_label.c.language,
            tables.concept_label.c.text,
        ).where(tables.concept_label.c.concept_declaration_id == pinned.concept_declaration_id)
    ).all()
    references = conn.execute(
        select(
            tables.concept_reference.c.link_role_uri,
            tables.concept_reference.c.reference_parts,
        ).where(tables.concept_reference.c.concept_declaration_id == pinned.concept_declaration_id)
    ).all()
    facts = conn.execute(
        select(
            tables.xbrl_fact.c.id,
            tables.xbrl_fact.c.value_status,
            tables.xbrl_fact.c.raw_lexical_value,
            tables.xbrl_fact.c.source_locator_scheme,
            tables.xbrl_fact.c.source_locator_value,
        )
        .where(tables.xbrl_fact.c.semantic_projection_id == pinned.semantic_projection_id)
        .where(tables.xbrl_fact.c.concept_declaration_id == pinned.concept_declaration_id)
    ).all()
    return ExplainEnrichment(
        pinned=pinned,
        labels=tuple(
            {"link_role_uri": r.link_role_uri, "language": r.language, "text": r.text}
            for r in labels
        ),
        references=tuple(
            {"link_role_uri": r.link_role_uri, "reference_parts": r.reference_parts}
            for r in references
        ),
        presentation_neighbors=_relationship_neighbors(
            conn,
            projection_id=pinned.semantic_projection_id,
            concept_declaration_id=pinned.concept_declaration_id,
            network_type="presentation",
        ),
        calculation_neighbors=_relationship_neighbors(
            conn,
            projection_id=pinned.semantic_projection_id,
            concept_declaration_id=pinned.concept_declaration_id,
            network_type="calculation",
        ),
        definition_neighbors=_relationship_neighbors(
            conn,
            projection_id=pinned.semantic_projection_id,
            concept_declaration_id=pinned.concept_declaration_id,
            network_type="definition",
        ),
        fact_occurrences=tuple(
            {
                "fact_id": int(r.id),
                "value_status": r.value_status,
                "raw_lexical_value": r.raw_lexical_value,
                "source_locator_scheme": r.source_locator_scheme,
                "source_locator_value": r.source_locator_value,
            }
            for r in facts
        ),
    )
