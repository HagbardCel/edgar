"""Phase 2B source catalog and extraction persistence.

Commit 4: live CatalogService / filings catalog|extract route through this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, delete, func, null, select
from sqlalchemy.dialects.postgresql import insert

from edgar.db import source_schema as src
from edgar.domain.bundle import FilingBundle, FilingIdentity
from edgar.domain.concept_id import concept_id
from edgar.xbrl.records import ExpandedQName
from edgar.xbrl.source_records import (
    ConceptDeclarationRecord,
    ConceptLabelRecord,
    ConceptReferenceRecord,
    ContextDimensionRecord,
    ContextRecord,
    DocumentBlockRecord,
    ElementLocator,
    ExtractionIssueRecord,
    FactRecord,
    FilingExtraction,
    FilingSectionRecord,
    RelationshipRecord,
    ReportExtraction,
    UnitMeasureRecord,
    UnitRecord,
)

__all__ = [
    "DocumentInventoryItem",
    "PersistExtractionError",
    "PersistExtractionResult",
    "SourceCatalogConflict",
    "SourceCatalogResult",
    "catalog_source_filing",
    "list_source_document_sections",
    "load_filing_documents",
    "persist_extraction",
    "resolve_document_id",
]


class SourceCatalogConflict(RuntimeError):
    """Persisted source catalog state conflicts with the incoming FilingBundle."""


class PersistExtractionError(RuntimeError):
    """Extraction persistence failed (missing provenance, incomplete facts, etc.)."""


@dataclass(frozen=True)
class SourceCatalogResult:
    filing_id: int
    accession: str
    issuer_cik: str
    document_count: int
    reused: bool


@dataclass(frozen=True)
class PersistExtractionResult:
    filing_id: int
    report_ids: tuple[int, ...]
    fact_count: int
    block_count: int
    section_count: int
    issue_count: int
    concept_upsert_count: int


@dataclass(frozen=True)
class DocumentInventoryItem:
    relative_path: str
    sha256: str
    byte_size: int
    document_kind: str
    source_url: str | None
    is_primary: bool


def catalog_source_filing(
    conn: Connection,
    bundle: FilingBundle,
    *,
    issuer_name: str | None = None,
) -> SourceCatalogResult:
    """Insert or verify-reuse ``source.issuer`` / ``filing`` / ``document``.

    Idempotent only when the catalogued inventory equals
    ``set(relative_path, sha256, byte_size)``. A path/hash conflict or inventory
    difference is an integrity failure, not an UPDATE.
    """
    cik = bundle.filing.cik
    _upsert_issuer(conn, cik, issuer_name)
    existing = _select_filing_id(conn, bundle.filing.accession)
    inventory = _bundle_document_inventory(bundle)

    if existing is not None:
        _assert_filing_metadata_compatible(conn, existing, bundle.filing)
        _assert_inventory_identical(conn, existing, inventory)
        return SourceCatalogResult(
            filing_id=existing,
            accession=bundle.filing.accession,
            issuer_cik=cik,
            document_count=len(inventory),
            reused=True,
        )

    filing_id = _insert_filing(conn, cik, bundle.filing)
    for item in inventory:
        _insert_document(conn, filing_id, item)

    return SourceCatalogResult(
        filing_id=filing_id,
        accession=bundle.filing.accession,
        issuer_cik=cik,
        document_count=len(inventory),
        reused=False,
    )


def _upsert_issuer(conn: Connection, cik: str, name: str | None) -> None:
    stmt = (
        insert(src.source_issuer)
        .values(cik=cik, name=name)
        .on_conflict_do_nothing(index_elements=["cik"])
    )
    conn.execute(stmt)
    if name is not None:
        # Fill name only when currently NULL; never overwrite a set name silently.
        conn.execute(
            src.source_issuer.update()
            .where(src.source_issuer.c.cik == cik)
            .where(src.source_issuer.c.name.is_(None))
            .values(name=name)
        )


def _select_filing_id(conn: Connection, accession: str) -> int | None:
    value = conn.execute(
        select(src.source_filing.c.id).where(src.source_filing.c.accession == accession)
    ).scalar_one_or_none()
    return int(value) if value is not None else None


def _insert_filing(conn: Connection, cik: str, filing: FilingIdentity) -> int:
    result = conn.execute(
        insert(src.source_filing)
        .values(
            issuer_cik=cik,
            accession=filing.accession,
            form=filing.form_type,
            filing_date=filing.filing_date,
            accepted_at=filing.accepted_at,
            report_period_end=filing.report_period_end,
            primary_document=filing.primary_document,
        )
        .returning(src.source_filing.c.id)
    )
    return int(result.scalar_one())


def _insert_document(conn: Connection, filing_id: int, item: DocumentInventoryItem) -> int:
    result = conn.execute(
        insert(src.source_document)
        .values(
            filing_id=filing_id,
            relative_path=item.relative_path,
            document_kind=item.document_kind,
            source_url=item.source_url,
            sha256=item.sha256,
            byte_size=item.byte_size,
            is_primary=item.is_primary,
        )
        .returning(src.source_document.c.id)
    )
    return int(result.scalar_one())


def _bundle_document_inventory(bundle: FilingBundle) -> tuple[DocumentInventoryItem, ...]:
    primary = bundle.filing.primary_document
    uri_by_path = {b.artifact_path: b.document_uri for b in bundle.uri_bindings}
    items: list[DocumentInventoryItem] = []
    for artifact in sorted(bundle.artifacts, key=lambda a: a.logical_path):
        basename = artifact.logical_path.rsplit("/", 1)[-1]
        is_primary = basename == primary or artifact.logical_path.endswith("/" + primary)
        items.append(
            DocumentInventoryItem(
                relative_path=artifact.logical_path,
                sha256=artifact.content.sha256,
                byte_size=artifact.content.byte_size,
                document_kind=artifact.artifact_kind,
                source_url=uri_by_path.get(artifact.logical_path),
                is_primary=is_primary,
            )
        )
    return tuple(items)


def _assert_filing_metadata_compatible(
    conn: Connection,
    filing_id: int,
    filing: FilingIdentity,
) -> None:
    row = (
        conn.execute(select(src.source_filing).where(src.source_filing.c.id == filing_id))
        .mappings()
        .one()
    )
    if row["issuer_cik"] != filing.cik:
        raise SourceCatalogConflict(
            f"filing {filing.accession} issuer_cik mismatch: "
            f"catalogued={row['issuer_cik']} incoming={filing.cik}"
        )
    if row["form"] != filing.form_type:
        raise SourceCatalogConflict(
            f"filing {filing.accession} form mismatch: "
            f"catalogued={row['form']} incoming={filing.form_type}"
        )
    catalogued_date = row["filing_date"]
    if isinstance(catalogued_date, datetime):
        catalogued_date = catalogued_date.date()
    if catalogued_date != filing.filing_date:
        raise SourceCatalogConflict(
            f"filing {filing.accession} filing_date mismatch: "
            f"catalogued={catalogued_date} incoming={filing.filing_date}"
        )
    if row["accepted_at"] != filing.accepted_at:
        raise SourceCatalogConflict(
            f"filing {filing.accession} accepted_at mismatch: "
            f"catalogued={row['accepted_at']} incoming={filing.accepted_at}"
        )
    catalogued_period = row["report_period_end"]
    if isinstance(catalogued_period, datetime):
        catalogued_period = catalogued_period.date()
    if catalogued_period != filing.report_period_end:
        raise SourceCatalogConflict(
            f"filing {filing.accession} report_period_end mismatch: "
            f"catalogued={catalogued_period} incoming={filing.report_period_end}"
        )
    if row["primary_document"] != filing.primary_document:
        raise SourceCatalogConflict(
            f"filing {filing.accession} primary_document mismatch: "
            f"catalogued={row['primary_document']} incoming={filing.primary_document}"
        )


def _assert_inventory_identical(
    conn: Connection,
    filing_id: int,
    inventory: tuple[DocumentInventoryItem, ...],
) -> None:
    rows = (
        conn.execute(
            select(
                src.source_document.c.relative_path,
                src.source_document.c.sha256,
                src.source_document.c.byte_size,
                src.source_document.c.document_kind,
                src.source_document.c.source_url,
                src.source_document.c.is_primary,
            ).where(src.source_document.c.filing_id == filing_id)
        )
        .mappings()
        .all()
    )
    existing_identity = {(r["relative_path"], r["sha256"], int(r["byte_size"])) for r in rows}
    incoming_identity = {(i.relative_path, i.sha256, i.byte_size) for i in inventory}
    if existing_identity != incoming_identity:
        raise SourceCatalogConflict(
            f"document inventory mismatch for filing_id={filing_id}: "
            f"catalogued={sorted(existing_identity)!r} incoming={sorted(incoming_identity)!r}"
        )
    by_path = {r["relative_path"]: r for r in rows}
    for item in inventory:
        row = by_path[item.relative_path]
        if row["document_kind"] != item.document_kind:
            raise SourceCatalogConflict(
                f"document_kind mismatch for {item.relative_path!r}: "
                f"catalogued={row['document_kind']!r} incoming={item.document_kind!r}"
            )
        if row["source_url"] != item.source_url:
            raise SourceCatalogConflict(
                f"source_url mismatch for {item.relative_path!r}: "
                f"catalogued={row['source_url']!r} incoming={item.source_url!r}"
            )
        if bool(row["is_primary"]) != item.is_primary:
            raise SourceCatalogConflict(
                f"is_primary mismatch for {item.relative_path!r}: "
                f"catalogued={row['is_primary']!r} incoming={item.is_primary!r}"
            )


def resolve_document_id(
    conn: Connection,
    *,
    filing_id: int,
    relative_path: str,
) -> int:
    """Map ``(filing_id, relative_path)`` → ``source.document.id``."""
    value = conn.execute(
        select(src.source_document.c.id).where(
            src.source_document.c.filing_id == filing_id,
            src.source_document.c.relative_path == relative_path,
        )
    ).scalar_one_or_none()
    if value is None:
        raise LookupError(
            f"source.document not found for filing_id={filing_id} path={relative_path!r}"
        )
    return int(value)


def load_filing_documents(
    conn: Connection,
    filing_id: int,
) -> dict[str, int]:
    """Return map relative_path → document id for a filing."""
    rows = conn.execute(
        select(src.source_document.c.relative_path, src.source_document.c.id).where(
            src.source_document.c.filing_id == filing_id
        )
    ).all()
    return {str(path): int(doc_id) for path, doc_id in rows}


def persist_extraction(
    conn: Connection,
    *,
    filing_id: int,
    extraction: FilingExtraction,
) -> PersistExtractionResult:
    """Atomically replace extraction-owned ``source.*`` rows for a filing.

    Caller may own the outer transaction. Locks ``source.filing`` with
    ``FOR UPDATE``, deletes extraction-owned current state, upserts shared
    concepts (never GC), inserts report rows and dependents, then asserts
    per-report fact completeness against ``arelle_item_fact_count``.
    """
    for report in extraction.reports:
        for issue in report.issues:
            if issue.severity == "fatal":
                raise PersistExtractionError(
                    f"refusing to persist fatal extraction issue {issue.code!r}; "
                    "fatal attempts must not replace the snapshot"
                )
    for issue in extraction.issues:
        if issue.severity == "fatal":
            raise PersistExtractionError(
                f"refusing to persist fatal filing issue {issue.code!r}; "
                "fatal attempts must not replace the snapshot"
            )

    locked = conn.execute(
        select(src.source_filing.c.id).where(src.source_filing.c.id == filing_id).with_for_update()
    ).scalar_one_or_none()
    if locked is None:
        raise PersistExtractionError(f"source.filing id={filing_id} not found")

    _delete_extraction_owned(conn, filing_id)

    documents = load_filing_documents(conn, filing_id)
    now = datetime.now(UTC)
    concepts = _collect_concepts(extraction)
    concept_upsert_count = _upsert_concepts(conn, concepts)

    report_ids: list[int] = []
    fact_count = 0
    issue_rows: list[dict[str, Any]] = []

    for report in extraction.reports:
        report_id = _insert_report(conn, filing_id=filing_id, report=report, extracted_at=now)
        report_ids.append(report_id)
        _insert_report_children(
            conn,
            report_id=report_id,
            report=report,
            documents=documents,
        )
        persisted = conn.execute(
            select(func.count())
            .select_from(src.source_fact)
            .where(src.source_fact.c.report_id == report_id)
        ).scalar_one()
        if int(persisted) != report.arelle_item_fact_count:
            raise PersistExtractionError(
                f"fact completeness mismatch for report_key={report.report_key}: "
                f"persisted={persisted} arelle_item_fact_count={report.arelle_item_fact_count}"
            )
        fact_count += int(persisted)
        for issue in report.issues:
            issue_rows.append(
                _issue_row(
                    filing_id=filing_id,
                    report_id=report_id,
                    issue=issue,
                    documents=documents,
                    created_at=now,
                )
            )

    for issue in extraction.issues:
        issue_rows.append(
            _issue_row(
                filing_id=filing_id,
                report_id=None,
                issue=issue,
                documents=documents,
                created_at=now,
            )
        )

    if issue_rows:
        conn.execute(src.source_extraction_issue.insert(), issue_rows)

    block_count = _bulk_insert_document_blocks(conn, extraction.document_blocks, documents)
    section_count = _bulk_insert_filing_sections(conn, extraction.filing_sections, documents)

    return PersistExtractionResult(
        filing_id=filing_id,
        report_ids=tuple(report_ids),
        fact_count=fact_count,
        block_count=block_count,
        section_count=section_count,
        issue_count=len(issue_rows),
        concept_upsert_count=concept_upsert_count,
    )


def _delete_extraction_owned(conn: Connection, filing_id: int) -> None:
    conn.execute(
        delete(src.source_xbrl_report).where(src.source_xbrl_report.c.filing_id == filing_id)
    )
    conn.execute(
        delete(src.source_extraction_issue).where(
            src.source_extraction_issue.c.filing_id == filing_id
        )
    )
    doc_ids = select(src.source_document.c.id).where(src.source_document.c.filing_id == filing_id)
    conn.execute(
        delete(src.source_document_block).where(
            src.source_document_block.c.document_id.in_(doc_ids)
        )
    )
    conn.execute(
        delete(src.source_filing_section).where(
            src.source_filing_section.c.document_id.in_(doc_ids)
        )
    )


def _collect_concepts(extraction: FilingExtraction) -> list[tuple[str, str, UUID]]:
    seen: dict[UUID, tuple[str, str]] = {}
    for report in extraction.reports:
        for concept in report.concepts:
            _remember_concept(seen, concept.namespace_uri, concept.local_name)
        for decl in report.declarations:
            _remember_qname(seen, decl.concept, what="declaration concept")
        for label in report.labels:
            _remember_qname(seen, label.concept, what="label concept")
        for ref in report.references:
            _remember_qname(seen, ref.concept, what="reference concept")
        for dim in report.dimensions:
            _remember_qname(seen, dim.dimension, what="dimension")
            if dim.member is not None:
                _remember_qname(seen, dim.member, what="dimension member")
        for fact in report.facts:
            _remember_qname(seen, fact.concept, what="fact concept")
        for rel in report.relationships:
            _remember_qname(seen, rel.source_concept, what="relationship source")
            _remember_qname(seen, rel.target_concept, what="relationship target")
    return [(ns, local, cid) for cid, (ns, local) in seen.items()]


def _remember_qname(
    seen: dict[UUID, tuple[str, str]],
    qname: ExpandedQName,
    *,
    what: str,
) -> None:
    if qname.namespace_uri is None or not qname.namespace_uri:
        raise PersistExtractionError(f"{what} requires a non-empty namespace_uri: {qname!r}")
    _remember_concept(seen, qname.namespace_uri, qname.local_name)


def _remember_concept(
    seen: dict[UUID, tuple[str, str]],
    namespace_uri: str,
    local_name: str,
) -> None:
    cid = concept_id(namespace_uri, local_name)
    seen[cid] = (namespace_uri, local_name)


def _upsert_concepts(conn: Connection, concepts: Sequence[tuple[str, str, UUID]]) -> int:
    if not concepts:
        return 0
    rows = [{"id": cid, "namespace_uri": ns, "local_name": local} for ns, local, cid in concepts]
    # Deterministic UUIDv5 PK aligns with UNIQUE(namespace_uri, local_name); either conflict
    # path is a reuse. Prefer the natural key so a stale divergent id cannot insert.
    stmt = (
        insert(src.source_concept)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_source_concept_qname")
    )
    conn.execute(stmt)
    return len(rows)


def _insert_report(
    conn: Connection,
    *,
    filing_id: int,
    report: ReportExtraction,
    extracted_at: datetime,
) -> int:
    return int(
        conn.execute(
            insert(src.source_xbrl_report)
            .values(
                filing_id=filing_id,
                report_key=report.report_key,
                report_input=report.report_input,
                entry_document_id=None,
                extractor_version=report.extractor_version,
                arelle_version=report.arelle_version,
                extracted_at=extracted_at,
                arelle_item_fact_count=report.arelle_item_fact_count,
            )
            .returning(src.source_xbrl_report.c.id)
        ).scalar_one()
    )


def _insert_report_children(
    conn: Connection,
    *,
    report_id: int,
    report: ReportExtraction,
    documents: Mapping[str, int],
) -> None:
    _bulk_insert_declarations(conn, report_id, report.declarations, documents)
    _bulk_insert_labels(conn, report_id, report.labels, documents)
    _bulk_insert_references(conn, report_id, report.references, documents)
    context_ids = _bulk_insert_contexts(conn, report_id, report.contexts, documents)
    _bulk_insert_dimensions(conn, context_ids, report.dimensions, documents)
    unit_ids = _bulk_insert_units(conn, report_id, report.units, documents)
    _bulk_insert_measures(conn, unit_ids, report.measures)
    _bulk_insert_facts(conn, report_id, report.facts, context_ids, unit_ids, documents)
    _bulk_insert_relationships(conn, report_id, report.relationships, documents)


def _bulk_insert_declarations(
    conn: Connection,
    report_id: int,
    declarations: Sequence[ConceptDeclarationRecord],
    documents: Mapping[str, int],
) -> None:
    if not declarations:
        return
    rows = [
        {
            "report_id": report_id,
            "concept_id": _concept_uuid(decl.concept, what="declaration"),
            "data_type": _optional_clark(decl.data_type),
            "period_type": decl.period_type,
            "balance": decl.balance,
            "abstract": decl.abstract,
            "nillable": decl.nillable,
            "substitution_group": _optional_clark(decl.substitution_group),
            "source_document_id": _resolve_optional_document(
                documents,
                decl.source_document_relative_path,
                decl.source_locator,
                what="declaration",
            ),
            "source_locator": _locator_json(decl.source_locator),
        }
        for decl in declarations
    ]
    conn.execute(src.source_concept_declaration.insert(), rows)


def _bulk_insert_labels(
    conn: Connection,
    report_id: int,
    labels: Sequence[ConceptLabelRecord],
    documents: Mapping[str, int],
) -> None:
    if not labels:
        return
    rows = [
        {
            "report_id": report_id,
            "concept_id": _concept_uuid(label.concept, what="label"),
            "link_role_uri": label.link_role_uri,
            "arcrole_uri": label.arcrole_uri,
            "resource_role_uri": label.resource_role_uri,
            "language": label.language,
            "text": label.text,
            "order_value": label.order_value,
            "source_order": label.source_order,
            "source_document_id": _resolve_optional_document(
                documents,
                label.source_document_relative_path,
                label.source_locator,
                what=f"label source_order={label.source_order}",
            ),
            "source_locator": _locator_json(label.source_locator),
            "arc_source_document_id": _resolve_optional_document(
                documents,
                label.arc_document_relative_path,
                label.arc_locator,
                what=f"label arc source_order={label.source_order}",
            ),
            "arc_locator": _locator_json(label.arc_locator),
        }
        for label in labels
    ]
    conn.execute(src.source_concept_label.insert(), rows)


def _bulk_insert_references(
    conn: Connection,
    report_id: int,
    references: Sequence[ConceptReferenceRecord],
    documents: Mapping[str, int],
) -> None:
    if not references:
        return
    rows = [
        {
            "report_id": report_id,
            "concept_id": _concept_uuid(ref.concept, what="reference"),
            "link_role_uri": ref.link_role_uri,
            "arcrole_uri": ref.arcrole_uri,
            "resource_role_uri": ref.resource_role_uri,
            "order_value": ref.order_value,
            "source_order": ref.source_order,
            "reference_parts": [part.to_dict() for part in ref.reference_parts],
            "source_document_id": _resolve_optional_document(
                documents,
                ref.source_document_relative_path,
                ref.source_locator,
                what=f"reference source_order={ref.source_order}",
            ),
            "source_locator": _locator_json(ref.source_locator),
            "arc_source_document_id": _resolve_optional_document(
                documents,
                ref.arc_document_relative_path,
                ref.arc_locator,
                what=f"reference arc source_order={ref.source_order}",
            ),
            "arc_locator": _locator_json(ref.arc_locator),
        }
        for ref in references
    ]
    conn.execute(src.source_concept_reference.insert(), rows)


def _bulk_insert_contexts(
    conn: Connection,
    report_id: int,
    contexts: Sequence[ContextRecord],
    documents: Mapping[str, int],
) -> dict[str, int]:
    if not contexts:
        return {}
    rows = [
        {
            "report_id": report_id,
            "source_context_id": ctx.source_context_id,
            "entity_scheme": ctx.entity_scheme,
            "entity_identifier": ctx.entity_identifier,
            "period_kind": ctx.period_kind,
            "instant_lexical": ctx.period_instant,
            "start_lexical": ctx.period_start,
            "end_lexical": ctx.period_end,
            "instant_at": _parse_offset_aware_datetime(ctx.period_instant),
            "start_at": _parse_offset_aware_datetime(ctx.period_start),
            "end_at": _parse_offset_aware_datetime(ctx.period_end),
            "source_document_id": _resolve_optional_document(
                documents,
                ctx.source_document_relative_path,
                ctx.source_locator,
                what=f"context {ctx.source_context_id}",
            ),
            "source_locator": _locator_json(ctx.source_locator),
        }
        for ctx in contexts
    ]
    conn.execute(src.source_context.insert(), rows)
    loaded = conn.execute(
        select(src.source_context.c.source_context_id, src.source_context.c.id).where(
            src.source_context.c.report_id == report_id
        )
    ).all()
    return {str(source_id): int(db_id) for source_id, db_id in loaded}


def _bulk_insert_dimensions(
    conn: Connection,
    context_ids: Mapping[str, int],
    dimensions: Sequence[ContextDimensionRecord],
    documents: Mapping[str, int],
) -> None:
    if not dimensions:
        return
    rows: list[dict[str, Any]] = []
    for dim in dimensions:
        context_id = context_ids.get(dim.source_context_id)
        if context_id is None:
            raise PersistExtractionError(
                f"dimension references unknown source_context_id={dim.source_context_id!r}"
            )
        typed_member: Any = null()
        if dim.typed_member is not None:
            typed_member = dict(dim.typed_member)
        rows.append(
            {
                "context_id": context_id,
                "dimension_concept_id": _concept_uuid(dim.dimension, what="dimension"),
                "context_element": dim.context_element,
                "member_kind": dim.member_kind,
                "explicit_member_concept_id": (
                    _concept_uuid(dim.member, what="dimension member")
                    if dim.member is not None
                    else None
                ),
                "typed_member": typed_member,
                "source_document_id": _resolve_optional_document(
                    documents,
                    dim.source_document_relative_path,
                    dim.source_locator,
                    what=f"dimension {dim.source_context_id}",
                ),
                "source_locator": _locator_json(dim.source_locator),
            }
        )
    conn.execute(src.source_context_dimension.insert(), rows)


def _bulk_insert_units(
    conn: Connection,
    report_id: int,
    units: Sequence[UnitRecord],
    documents: Mapping[str, int],
) -> dict[str, int]:
    if not units:
        return {}
    rows = [
        {
            "report_id": report_id,
            "source_unit_id": unit.source_unit_id,
            "source_document_id": _resolve_optional_document(
                documents,
                unit.source_document_relative_path,
                unit.source_locator,
                what=f"unit {unit.source_unit_id}",
            ),
            "source_locator": _locator_json(unit.source_locator),
        }
        for unit in units
    ]
    conn.execute(src.source_unit.insert(), rows)
    loaded = conn.execute(
        select(src.source_unit.c.source_unit_id, src.source_unit.c.id).where(
            src.source_unit.c.report_id == report_id
        )
    ).all()
    return {str(source_id): int(db_id) for source_id, db_id in loaded}


def _bulk_insert_measures(
    conn: Connection,
    unit_ids: Mapping[str, int],
    measures: Sequence[UnitMeasureRecord],
) -> None:
    if not measures:
        return
    rows: list[dict[str, Any]] = []
    for measure in measures:
        unit_id = unit_ids.get(measure.source_unit_id)
        if unit_id is None:
            raise PersistExtractionError(
                f"measure references unknown source_unit_id={measure.source_unit_id!r}"
            )
        rows.append(
            {
                "unit_id": unit_id,
                "side": measure.side,
                "ordinal": measure.ordinal,
                "measure_namespace_uri": measure.measure.namespace_uri,
                "measure_local_name": measure.measure.local_name,
            }
        )
    conn.execute(src.source_unit_measure.insert(), rows)


def _bulk_insert_facts(
    conn: Connection,
    report_id: int,
    facts: Sequence[FactRecord],
    context_ids: Mapping[str, int],
    unit_ids: Mapping[str, int],
    documents: Mapping[str, int],
) -> None:
    if not facts:
        return
    rows: list[dict[str, Any]] = []
    for fact in facts:
        context_id = context_ids.get(fact.source_context_id)
        if context_id is None:
            raise PersistExtractionError(
                f"fact source_order={fact.source_order} references unknown "
                f"source_context_id={fact.source_context_id!r}"
            )
        unit_id: int | None = None
        if fact.source_unit_id is not None:
            unit_id = unit_ids.get(fact.source_unit_id)
            if unit_id is None:
                raise PersistExtractionError(
                    f"fact source_order={fact.source_order} references unknown "
                    f"source_unit_id={fact.source_unit_id!r}"
                )
        source_document_id = _resolve_optional_document(
            documents,
            fact.source_document_relative_path,
            fact.source_locator,
            what=f"fact source_order={fact.source_order}",
        )
        continuation: Any = null()
        if fact.continuation_provenance:
            continuation = [dict(item) for item in fact.continuation_provenance]
        rows.append(
            {
                "report_id": report_id,
                "source_order": fact.source_order,
                "concept_id": _concept_uuid(fact.concept, what="fact"),
                "context_id": context_id,
                "unit_id": unit_id,
                "value_status": fact.value_status,
                "raw_lexical_value": fact.raw_lexical_value,
                "resolved_value_kind": fact.resolved_value_kind,
                "resolved_numeric": fact.resolved_numeric,
                "resolved_text": fact.resolved_text,
                "is_nil": fact.is_nil,
                "decimals": fact.decimals,
                "precision": fact.precision,
                "xml_lang": fact.xml_lang,
                "scale": fact.scale,
                "sign": fact.sign,
                "format_namespace_uri": fact.format_namespace_uri,
                "format_local_name": fact.format_local_name,
                "escape": fact.escape,
                "continuation_provenance": continuation,
                "source_xml_id": fact.source_xml_id,
                "source_document_id": source_document_id,
                "source_locator": _locator_json(fact.source_locator),
            }
        )
    conn.execute(src.source_fact.insert(), rows)


def _bulk_insert_relationships(
    conn: Connection,
    report_id: int,
    relationships: Sequence[RelationshipRecord],
    documents: Mapping[str, int],
) -> None:
    if not relationships:
        return
    rows = [
        {
            "report_id": report_id,
            "source_order": rel.source_order,
            "network_type": rel.network_type,
            "link_role_uri": rel.link_role_uri,
            "arcrole_uri": rel.arcrole_uri,
            "source_concept_id": _concept_uuid(rel.source_concept, what="relationship source"),
            "target_concept_id": _concept_uuid(rel.target_concept, what="relationship target"),
            "order_value": rel.order_value,
            "weight": rel.weight,
            "preferred_label": rel.preferred_label,
            "target_role": rel.target_role,
            "attributes": (dict(rel.attributes) if rel.attributes is not None else null()),
            "source_document_id": _resolve_optional_document(
                documents,
                rel.source_document_relative_path,
                rel.source_locator,
                what=f"relationship source_order={rel.source_order}",
            ),
            "source_locator": _locator_json(rel.source_locator),
        }
        for rel in relationships
    ]
    conn.execute(src.source_relationship.insert(), rows)


def _bulk_insert_document_blocks(
    conn: Connection,
    blocks: Sequence[DocumentBlockRecord],
    documents: Mapping[str, int],
) -> int:
    if not blocks:
        return 0
    rows: list[dict[str, Any]] = []
    for block in blocks:
        document_id = _resolve_optional_document(
            documents,
            block.document_relative_path,
            what=f"document_block ordinal={block.ordinal}",
        )
        if document_id is None:
            raise PersistExtractionError(
                "document_block requires a catalogued document_relative_path: "
                f"{block.document_relative_path!r}"
            )
        rows.append(
            {
                "document_id": document_id,
                "ordinal": block.ordinal,
                "parent_ordinal": block.parent_ordinal,
                "block_type": block.block_type,
                "text": block.text,
                "heading_level": block.heading_level,
                "source_locator": dict(block.source_locator),
                "parser_version": block.parser_version,
            }
        )
    conn.execute(src.source_document_block.insert(), rows)
    return len(rows)


def _bulk_insert_filing_sections(
    conn: Connection,
    sections: Sequence[FilingSectionRecord],
    documents: Mapping[str, int],
) -> int:
    if not sections:
        return 0
    rows: list[dict[str, Any]] = []
    for section in sections:
        document_id = _resolve_optional_document(
            documents,
            section.document_relative_path,
            what=f"filing_section key={section.section_key}",
        )
        if document_id is None:
            raise PersistExtractionError(
                "filing_section requires a catalogued document_relative_path: "
                f"{section.document_relative_path!r}"
            )
        rows.append(
            {
                "document_id": document_id,
                "section_key": section.section_key,
                "start_block_ordinal": section.start_block_ordinal,
                "end_block_ordinal_exclusive": section.end_block_ordinal_exclusive,
                "method": section.method,
                "confidence_score": section.confidence_score,
            }
        )
    conn.execute(src.source_filing_section.insert(), rows)
    return len(rows)


def list_source_document_sections(
    conn: Connection,
    document_id: int,
) -> list[dict[str, Any]]:
    """Compact section metadata for one ``source.document``."""
    rows = (
        conn.execute(
            select(
                src.source_filing_section.c.section_key,
                src.source_filing_section.c.start_block_ordinal,
                src.source_filing_section.c.end_block_ordinal_exclusive,
                src.source_filing_section.c.method,
                src.source_filing_section.c.confidence_score,
            )
            .where(src.source_filing_section.c.document_id == document_id)
            .order_by(src.source_filing_section.c.start_block_ordinal)
        )
        .mappings()
        .all()
    )
    return [
        {
            "section_key": str(r["section_key"]),
            "start_block_ordinal": int(r["start_block_ordinal"]),
            "end_block_ordinal_exclusive": int(r["end_block_ordinal_exclusive"]),
            "method": str(r["method"]),
            "confidence_score": int(r["confidence_score"]),
        }
        for r in rows
    ]


def _issue_row(
    *,
    filing_id: int,
    report_id: int | None,
    issue: ExtractionIssueRecord,
    documents: Mapping[str, int],
    created_at: datetime,
) -> dict[str, Any]:
    document_id = _resolve_optional_document(
        documents,
        issue.source_document_relative_path,
        issue.source_locator,
        what=f"issue code={issue.code}",
    )
    return {
        "filing_id": filing_id,
        "report_id": report_id,
        "document_id": document_id,
        "component": issue.component,
        "code": issue.code,
        "severity": issue.severity,
        "message": issue.message,
        "details": dict(issue.details),
        "source_locator": _locator_json(issue.source_locator),
        "created_at": created_at,
    }


def _resolve_optional_document(
    documents: Mapping[str, int],
    relative_path: str | None,
    locator: ElementLocator | None = None,
    *,
    what: str,
) -> int | None:
    if relative_path is None:
        if locator is not None:
            raise PersistExtractionError(f"{what}: locator without source document path")
        return None
    doc_id = documents.get(relative_path)
    if doc_id is None:
        raise PersistExtractionError(
            f"{what}: source document path not catalogued: {relative_path!r}"
        )
    return doc_id


def _concept_uuid(qname: ExpandedQName, *, what: str) -> UUID:
    if qname.namespace_uri is None or not qname.namespace_uri:
        raise PersistExtractionError(f"{what} requires a non-empty namespace_uri: {qname!r}")
    return concept_id(qname.namespace_uri, qname.local_name)


def _optional_clark(qname: ExpandedQName | None) -> str | None:
    if qname is None:
        return None
    return qname.clark


def _locator_json(locator: ElementLocator | None) -> Any:
    if locator is None:
        return null()
    return locator.to_dict()


def _parse_offset_aware_datetime(value: str | None) -> datetime | None:
    """Populate ``*_at`` only for offset-aware absolute ``xs:dateTime`` lexicals.

    Date-only and timezone-less dateTime values leave ``*_at`` NULL. A failed
    optional parse also returns NULL and never rejects the occurrence.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        return parsed
    return None
