"""Phase 1D real-corpus acceptance helpers: snapshots and scoped coverage queries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import Connection, func, select, text
from sqlalchemy.engine import Row

from edgar.db import schema as tables
from edgar.domain.bundle import FilingBundle
from edgar.storage.bundles import BundleRepository

STANDARD_TAXONOMY_HOSTS = frozenset(
    {
        "fasb.org",
        "xbrl.sec.gov",
        "xbrl.org",
        "www.xbrl.org",
    }
)

_US_GAAP_YEAR = re.compile(r"^/us-gaap/(\d{4})(?:-\d{2}-\d{2})?$")


@dataclass(frozen=True)
class PublishedBundleResolution:
    bundle_dir: Path | None
    bundle: FilingBundle | None
    candidates: tuple[dict[str, str], ...]
    error: str | None


@dataclass(frozen=True)
class CorpusProjection:
    role: str
    company: str
    cik: str
    accession: str
    form: str
    industry_group: str
    bundle_id: int
    semantic_projection_id: int
    document_projection_id: int


@dataclass(frozen=True)
class CatalogSnapshot:
    bundle_id: int
    artifact_count: int
    uri_binding_count: int
    report_input_count: int
    report_input_member_count: int


@dataclass(frozen=True)
class SemanticSnapshot:
    projection_id: int
    concept_declaration_count: int
    concept_label_count: int
    concept_reference_count: int
    role_declaration_count: int
    arcrole_declaration_count: int
    context_count: int
    context_dimension_count: int
    unit_count: int
    unit_measure_count: int
    fact_count: int
    relationship_count: int
    semantic_issue_count: int


@dataclass(frozen=True)
class DocumentSnapshot:
    projection_id: int
    block_count: int
    section_count: int
    document_issue_count: int


@dataclass(frozen=True)
class CanonicalSnapshot:
    catalog: CatalogSnapshot
    semantic: SemanticSnapshot
    document: DocumentSnapshot


def is_standard_taxonomy_namespace(namespace_uri: str | None) -> bool:
    if not namespace_uri:
        return False
    host = urlparse(namespace_uri).hostname
    if host is None:
        return False
    return host.lower() in STANDARD_TAXONOMY_HOSTS


def parse_us_gaap_taxonomy_year(namespace_uri: str | None) -> int | None:
    if not namespace_uri:
        return None
    parsed = urlparse(namespace_uri)
    if parsed.hostname != "fasb.org":
        return None
    match = _US_GAAP_YEAR.match(parsed.path or "")
    if match is None:
        return None
    return int(match.group(1))


def resolve_published_bundle(
    repo: BundleRepository, cik: str, accession: str
) -> PublishedBundleResolution:
    published = repo.list_published(cik, accession)
    candidates = tuple(
        {
            "bundle_dir": str(bundle_dir),
            "opaque_id": bundle_dir.name,
            "payload_hash": bundle.payload_hash,
        }
        for bundle_dir, bundle in published
    )
    if not published:
        return PublishedBundleResolution(
            bundle_dir=None,
            bundle=None,
            candidates=(),
            error="bundle not found under EDGAR_DATA_ROOT",
        )
    if len(published) > 1:
        return PublishedBundleResolution(
            bundle_dir=None,
            bundle=None,
            candidates=candidates,
            error=f"ambiguous corpus identity: {len(published)} published bundles for accession",
        )
    bundle_dir, bundle = published[0]
    return PublishedBundleResolution(
        bundle_dir=bundle_dir,
        bundle=bundle,
        candidates=candidates,
        error=None,
    )


def _scalar_count(conn: Connection, stmt: Any) -> int:
    value = conn.execute(stmt).scalar_one()
    return int(value)


def canonical_snapshot(conn: Connection, projection: CorpusProjection) -> CanonicalSnapshot:
    bundle_id = projection.bundle_id
    semantic_id = projection.semantic_projection_id
    document_id = projection.document_projection_id

    report_input_ids = select(tables.xbrl_report_input.c.id).where(
        tables.xbrl_report_input.c.filing_bundle_id == bundle_id
    )

    catalog = CatalogSnapshot(
        bundle_id=bundle_id,
        artifact_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.bundle_artifact)
            .where(tables.bundle_artifact.c.filing_bundle_id == bundle_id),
        ),
        uri_binding_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.bundle_uri_binding)
            .where(tables.bundle_uri_binding.c.filing_bundle_id == bundle_id),
        ),
        report_input_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.xbrl_report_input)
            .where(tables.xbrl_report_input.c.filing_bundle_id == bundle_id),
        ),
        report_input_member_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.xbrl_report_input_member)
            .where(tables.xbrl_report_input_member.c.report_input_id.in_(report_input_ids)),
        ),
    )

    semantic = SemanticSnapshot(
        projection_id=semantic_id,
        concept_declaration_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.concept_declaration)
            .where(tables.concept_declaration.c.semantic_projection_id == semantic_id),
        ),
        concept_label_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.concept_label)
            .where(tables.concept_label.c.semantic_projection_id == semantic_id),
        ),
        concept_reference_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.concept_reference)
            .where(tables.concept_reference.c.semantic_projection_id == semantic_id),
        ),
        role_declaration_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.role_declaration)
            .where(tables.role_declaration.c.semantic_projection_id == semantic_id),
        ),
        arcrole_declaration_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.arcrole_declaration)
            .where(tables.arcrole_declaration.c.semantic_projection_id == semantic_id),
        ),
        context_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.xbrl_context)
            .where(tables.xbrl_context.c.semantic_projection_id == semantic_id),
        ),
        context_dimension_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.xbrl_context_dimension)
            .join(
                tables.xbrl_context,
                tables.xbrl_context_dimension.c.context_id == tables.xbrl_context.c.id,
            )
            .where(tables.xbrl_context.c.semantic_projection_id == semantic_id),
        ),
        unit_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.xbrl_unit)
            .where(tables.xbrl_unit.c.semantic_projection_id == semantic_id),
        ),
        unit_measure_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.xbrl_unit_measure)
            .join(tables.xbrl_unit, tables.xbrl_unit_measure.c.unit_id == tables.xbrl_unit.c.id)
            .where(tables.xbrl_unit.c.semantic_projection_id == semantic_id),
        ),
        fact_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.xbrl_fact)
            .where(tables.xbrl_fact.c.semantic_projection_id == semantic_id),
        ),
        relationship_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.xbrl_relationship)
            .where(tables.xbrl_relationship.c.semantic_projection_id == semantic_id),
        ),
        semantic_issue_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.semantic_issue)
            .where(tables.semantic_issue.c.semantic_projection_id == semantic_id)
            .where(tables.semantic_issue.c.semantic_projection_attempt_id.is_(None)),
        ),
    )

    document = DocumentSnapshot(
        projection_id=document_id,
        block_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.document_block)
            .where(tables.document_block.c.document_projection_id == document_id),
        ),
        section_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.filing_section)
            .where(tables.filing_section.c.document_projection_id == document_id),
        ),
        document_issue_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(tables.document_issue)
            .where(tables.document_issue.c.document_projection_id == document_id)
            .where(tables.document_issue.c.document_projection_attempt_id.is_(None)),
        ),
    )

    return CanonicalSnapshot(catalog=catalog, semantic=semantic, document=document)


def _extension_declarations_subquery(semantic_projection_id: int) -> Any:
    return (
        select(
            tables.concept_declaration.c.id.label("declaration_id"),
            tables.concept_identity.c.namespace_uri,
            tables.concept_identity.c.local_name,
        )
        .join(
            tables.concept_identity,
            tables.concept_declaration.c.concept_identity_id == tables.concept_identity.c.id,
        )
        .where(tables.concept_declaration.c.semantic_projection_id == semantic_projection_id)
    )


def extension_coverage(
    conn: Connection, projections: tuple[CorpusProjection, ...]
) -> dict[str, Any]:
    declared_ids: set[int] = set()
    used_ids: set[int] = set()
    extension_fact_count = 0
    declared_namespaces: set[str] = set()
    used_qnames: set[str] = set()

    for projection in projections:
        sem_id = projection.semantic_projection_id
        rows = conn.execute(_extension_declarations_subquery(sem_id)).all()
        ext_by_id: dict[int, Row[Any]] = {}
        for row in rows:
            if is_standard_taxonomy_namespace(row.namespace_uri):
                continue
            declared_ids.add(int(row.declaration_id))
            if row.namespace_uri:
                declared_namespaces.add(row.namespace_uri)
            ext_by_id[int(row.declaration_id)] = row

        if not ext_by_id:
            continue

        ext_ids = list(ext_by_id.keys())

        fact_rows = conn.execute(
            select(tables.xbrl_fact.c.concept_declaration_id)
            .where(tables.xbrl_fact.c.semantic_projection_id == projection.semantic_projection_id)
            .where(tables.xbrl_fact.c.concept_declaration_id.in_(ext_ids))
        ).all()
        for row in fact_rows:
            decl_id = int(row.concept_declaration_id)
            used_ids.add(decl_id)
            extension_fact_count += 1
            decl = ext_by_id[decl_id]
            used_qnames.add(f"{{{decl.namespace_uri}}}{decl.local_name}")

        rel_rows = conn.execute(
            select(
                tables.xbrl_relationship.c.source_concept_declaration_id,
                tables.xbrl_relationship.c.target_concept_declaration_id,
            ).where(tables.xbrl_relationship.c.semantic_projection_id == sem_id)
        ).all()
        for row in rel_rows:
            for decl_id in (row.source_concept_declaration_id, row.target_concept_declaration_id):
                if decl_id is None:
                    continue
                decl_id_int = int(decl_id)
                if decl_id_int in ext_by_id:
                    used_ids.add(decl_id_int)
                    decl = ext_by_id[decl_id_int]
                    used_qnames.add(f"{{{decl.namespace_uri}}}{decl.local_name}")

    return {
        "declared_extension_concept_count": len(declared_ids),
        "used_extension_concept_count": len(used_ids),
        "extension_fact_count": extension_fact_count,
        "sample_extension_namespaces": sorted(declared_namespaces)[:10],
        "sample_used_extension_qnames": sorted(used_qnames)[:10],
    }


def dimension_coverage(
    conn: Connection, projections: tuple[CorpusProjection, ...]
) -> dict[str, Any]:
    total = 0
    per_filing: dict[str, int] = {}
    for projection in projections:
        sem_id = projection.semantic_projection_id
        count = _scalar_count(
            conn,
            select(func.count())
            .select_from(tables.xbrl_context_dimension)
            .join(
                tables.xbrl_context,
                tables.xbrl_context_dimension.c.context_id == tables.xbrl_context.c.id,
            )
            .where(tables.xbrl_context.c.semantic_projection_id == sem_id),
        )
        per_filing[projection.accession] = count
        total += count
    return {"dimension_count": total, "per_filing": per_filing}


def presentation_role_coverage(
    conn: Connection, projections: tuple[CorpusProjection, ...]
) -> dict[str, Any]:
    all_roles: set[str] = set()
    per_filing: dict[str, list[str]] = {}
    for projection in projections:
        rows = conn.execute(
            select(tables.xbrl_relationship.c.link_role_uri)
            .where(
                tables.xbrl_relationship.c.semantic_projection_id
                == projection.semantic_projection_id
            )
            .where(tables.xbrl_relationship.c.network_type == "presentation")
            .distinct()
        ).all()
        roles = sorted({row.link_role_uri for row in rows})
        per_filing[projection.accession] = roles
        all_roles.update(roles)
    return {
        "distinct_presentation_role_count": len(all_roles),
        "distinct_presentation_roles": sorted(all_roles),
        "per_filing": per_filing,
    }


def taxonomy_transition_coverage(
    conn: Connection, projections: tuple[CorpusProjection, ...]
) -> dict[str, Any]:
    per_projection: list[dict[str, Any]] = []
    cik_years: dict[str, set[int]] = {}

    for projection in projections:
        rows = conn.execute(
            select(tables.concept_identity.c.namespace_uri)
            .join(
                tables.concept_declaration,
                tables.concept_declaration.c.concept_identity_id == tables.concept_identity.c.id,
            )
            .where(
                tables.concept_declaration.c.semantic_projection_id
                == projection.semantic_projection_id
            )
            .distinct()
        ).all()
        years = sorted(
            {
                year
                for row in rows
                if (year := parse_us_gaap_taxonomy_year(row.namespace_uri)) is not None
            }
        )
        entry: dict[str, Any] = {
            "accession": projection.accession,
            "cik": projection.cik,
            "semantic_projection_id": projection.semantic_projection_id,
            "us_gaap_years": years,
        }
        if len(years) == 1:
            entry["projection_taxonomy_year"] = years[0]
            cik_years.setdefault(projection.cik, set()).add(years[0])
        elif len(years) == 0:
            entry["ambiguity"] = "no identifiable US-GAAP taxonomy year"
        else:
            entry["ambiguity"] = f"multiple US-GAAP taxonomy years in one projection: {years}"
        per_projection.append(entry)

    transition_ciks = sorted(cik for cik, years in cik_years.items() if len(years) >= 2)
    return {
        "per_projection": per_projection,
        "transition_ciks": transition_ciks,
        "has_taxonomy_transition": bool(transition_ciks),
    }


def continuation_provenance_coverage(
    conn: Connection, projections: tuple[CorpusProjection, ...]
) -> dict[str, Any]:
    """Informational only (class C); not a gate."""
    total = 0
    per_filing: dict[str, int] = {}
    for projection in projections:
        count = _scalar_count(
            conn,
            select(func.count())
            .select_from(tables.xbrl_fact)
            .where(tables.xbrl_fact.c.semantic_projection_id == projection.semantic_projection_id)
            .where(tables.xbrl_fact.c.continuation_provenance.is_not(None))
            .where(text("continuation_provenance != '[]'::jsonb")),
        )
        per_filing[projection.accession] = count
        total += count
    return {"continuation_fact_count": total, "per_filing": per_filing, "gating": False}


def evaluate_class_a_requirements(
    projections: tuple[CorpusProjection, ...],
    *,
    extension: dict[str, Any],
    dimensions: dict[str, Any],
    presentation_roles: dict[str, Any],
    taxonomy: dict[str, Any],
) -> dict[str, Any]:
    by_role = {p.role: p for p in projections}
    two_10k = [by_role[r].company for r in ("base_10k", "second_10k") if r in by_role]
    two_10q = [by_role[r].company for r in ("first_10q", "second_10q") if r in by_role]
    amendment = [by_role["amendment_10ka"].company] if "amendment_10ka" in by_role else []
    industries = sorted({p.industry_group for p in projections})

    requirements = {
        "two_10k": two_10k,
        "two_10q": two_10q,
        "amendment": amendment,
        "multiple_industries": len(industries) >= 2,
        "industry_groups": industries,
        "used_extension_concepts": extension["used_extension_concept_count"] > 0,
        "dimensions": dimensions["dimension_count"] > 0,
        "multiple_statement_roles": presentation_roles["distinct_presentation_role_count"] > 1,
        "taxonomy_transition": taxonomy["has_taxonomy_transition"],
    }
    checks = {
        "two_10k": len(two_10k) >= 2,
        "two_10q": len(two_10q) >= 2,
        "amendment": len(amendment) >= 1,
        "multiple_industries": len(industries) >= 2,
        "used_extension_concepts": extension["used_extension_concept_count"] > 0,
        "dimensions": dimensions["dimension_count"] > 0,
        "multiple_statement_roles": presentation_roles["distinct_presentation_role_count"] > 1,
        "taxonomy_transition": taxonomy["has_taxonomy_transition"],
    }
    unmet = [key for key, met in checks.items() if not met]
    return {"requirements": requirements, "checks": checks, "unmet": unmet}
