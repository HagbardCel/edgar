"""Load source.* rows for financial selection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Connection, select
from sqlalchemy.engine import Engine

from edgar.db import source_schema as src
from edgar.domain.concept_id import clark_qname
from edgar.financials.models import FactRow, UnitMeasureRow
from edgar.financials.period import DEI_LOCAL_DOCUMENT_PERIOD_END, DeiPeriodCandidate
from edgar.xbrl.taxonomy_family import classify


@dataclass(frozen=True)
class FilingMetadata:
    accession: str
    cik: str
    form: str
    accepted_at: str | None
    filing_id: int


@dataclass(frozen=True)
class LoadedFiling:
    accession: str
    cik: str
    form: str
    accepted_at: str | None
    facts: tuple[FactRow, ...]
    dei_candidates: tuple[DeiPeriodCandidate, ...]


def load_filing_metadata(conn: Connection, accession: str) -> FilingMetadata | None:
    filing_row = (
        conn.execute(
            select(
                src.source_filing.c.accession,
                src.source_filing.c.issuer_cik,
                src.source_filing.c.form,
                src.source_filing.c.accepted_at,
                src.source_filing.c.id,
            ).where(src.source_filing.c.accession == accession)
        )
        .mappings()
        .first()
    )
    if filing_row is None:
        return None
    return FilingMetadata(
        accession=accession,
        cik=filing_row["issuer_cik"],
        form=filing_row["form"],
        accepted_at=_iso(filing_row["accepted_at"]),
        filing_id=filing_row["id"],
    )


def load_filing(conn: Connection, accession: str) -> LoadedFiling | None:
    meta = load_filing_metadata(conn, accession)
    if meta is None:
        return None
    return _load_filing_body(conn, meta)


def _load_filing_body(conn: Connection, meta: FilingMetadata) -> LoadedFiling:
    report_ids = [
        row[0]
        for row in conn.execute(
            select(src.source_xbrl_report.c.id)
            .where(src.source_xbrl_report.c.filing_id == meta.filing_id)
            .order_by(src.source_xbrl_report.c.id.asc())
        )
    ]
    if len(report_ids) > 1:
        raise ValueError(
            f"accession {meta.accession} has {len(report_ids)} xbrl_report rows; "
            "P1 requires exactly one report per filing"
        )
    if not report_ids:
        return LoadedFiling(
            accession=meta.accession,
            cik=meta.cik,
            form=meta.form,
            accepted_at=meta.accepted_at,
            facts=(),
            dei_candidates=(),
        )
    report_id = report_ids[0]
    dim_contexts = {
        row[0] for row in conn.execute(select(src.source_context_dimension.c.context_id).distinct())
    }
    unit_measures: dict[int, list[UnitMeasureRow]] = {}
    for row in conn.execute(
        select(
            src.source_unit_measure.c.unit_id,
            src.source_unit_measure.c.side,
            src.source_unit_measure.c.ordinal,
            src.source_unit_measure.c.measure_namespace_uri,
            src.source_unit_measure.c.measure_local_name,
        ).where(
            src.source_unit_measure.c.unit_id.in_(
                select(src.source_unit.c.id).where(src.source_unit.c.report_id == report_id)
            )
        )
    ):
        uid = row.unit_id
        measure = UnitMeasureRow(
            side=row.side,
            ordinal=row.ordinal,
            measure_namespace_uri=row.measure_namespace_uri,
            measure_local_name=row.measure_local_name,
        )
        unit_measures.setdefault(uid, []).append(measure)

    facts: list[FactRow] = []
    dei: list[DeiPeriodCandidate] = []
    stmt = (
        select(
            src.source_fact.c.id,
            src.source_fact.c.context_id,
            src.source_fact.c.unit_id,
            src.source_fact.c.value_status,
            src.source_fact.c.resolved_numeric,
            src.source_fact.c.is_nil,
            src.source_fact.c.decimals,
            src.source_concept.c.namespace_uri,
            src.source_concept.c.local_name,
            src.source_context.c.entity_scheme,
            src.source_context.c.entity_identifier,
            src.source_context.c.period_kind,
            src.source_context.c.instant_lexical,
            src.source_context.c.start_lexical,
            src.source_context.c.end_lexical,
            src.source_fact.c.raw_lexical_value,
        )
        .join(src.source_concept, src.source_fact.c.concept_id == src.source_concept.c.id)
        .join(src.source_context, src.source_fact.c.context_id == src.source_context.c.id)
        .where(src.source_fact.c.report_id == report_id)
    )
    for row in conn.execute(stmt):
        uid = row.unit_id
        measures = tuple(unit_measures.get(uid, [])) if uid is not None else ()
        numeric = row.resolved_numeric
        if numeric is not None and not isinstance(numeric, Decimal):
            numeric = Decimal(str(numeric))
        lexical = row.raw_lexical_value
        fr = FactRow(
            fact_id=row.id,
            concept_namespace=row.namespace_uri,
            concept_local_name=row.local_name,
            source_qname=clark_qname(row.namespace_uri, row.local_name),
            context_id=row.context_id,
            value_status=row.value_status,
            resolved_numeric=numeric,
            is_nil=row.is_nil,
            decimals=row.decimals,
            lexical_value=lexical,
            entity_scheme=row.entity_scheme,
            entity_identifier=row.entity_identifier,
            period_kind=row.period_kind,
            instant_lexical=row.instant_lexical,
            start_lexical=row.start_lexical,
            end_lexical=row.end_lexical,
            has_dimensions=row.context_id in dim_contexts,
            unit_measures=measures,
        )
        facts.append(fr)
        if (
            row.local_name == DEI_LOCAL_DOCUMENT_PERIOD_END
            and classify(row.namespace_uri).semantic_family == "dei"
            and row.context_id not in dim_contexts
            and lexical
        ):
            dei.append(
                DeiPeriodCandidate(
                    context_id=row.context_id,
                    context_entity_scheme=row.entity_scheme,
                    context_entity_identifier=row.entity_identifier,
                    period_kind=row.period_kind,
                    instant_lexical=row.instant_lexical,
                    start_lexical=row.start_lexical,
                    end_lexical=row.end_lexical,
                    document_period_end_value=lexical,
                )
            )
    return LoadedFiling(
        accession=meta.accession,
        cik=meta.cik,
        form=meta.form,
        accepted_at=meta.accepted_at,
        facts=tuple(facts),
        dei_candidates=tuple(dei),
    )


def _iso(value: object) -> str | None:
    if value is None:
        return None
    from datetime import datetime

    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@dataclass(frozen=True)
class QualityFilingSource:
    """Declaration and period inputs for the quality report. Not an observation."""

    accession: str
    cik: str
    form: str
    report_period_year: str | None
    declared_namespaces: tuple[str, ...]
    declared_concepts: tuple[tuple[str, str], ...]
    fact_concepts: tuple[tuple[str, str], ...]


def load_quality_filing_source(conn: Connection, accession: str) -> QualityFilingSource | None:
    meta = load_filing_metadata(conn, accession)
    if meta is None:
        return None
    period_row = (
        conn.execute(
            select(
                src.source_filing.c.report_period_end,
                src.source_filing.c.filing_date,
            ).where(src.source_filing.c.accession == accession)
        )
        .mappings()
        .first()
    )
    report_year: str | None = None
    if period_row is not None:
        period_end = period_row["report_period_end"]
        filing_date = period_row["filing_date"]
        if period_end is not None:
            report_year = str(period_end.year)
        elif filing_date is not None:
            report_year = str(filing_date.year)
    report_ids = [
        row[0]
        for row in conn.execute(
            select(src.source_xbrl_report.c.id)
            .where(src.source_xbrl_report.c.filing_id == meta.filing_id)
            .order_by(src.source_xbrl_report.c.id.asc())
        )
    ]
    if len(report_ids) > 1:
        raise ValueError(
            f"accession {accession} has {len(report_ids)} xbrl_report rows; "
            "quality reporting requires exactly one report per filing"
        )
    declared: list[tuple[str, str]] = []
    fact_concepts: list[tuple[str, str]] = []
    if report_ids:
        report_id = report_ids[0]
        declared = [
            (row.namespace_uri, row.local_name)
            for row in conn.execute(
                select(src.source_concept.c.namespace_uri, src.source_concept.c.local_name)
                .join(
                    src.source_concept_declaration,
                    src.source_concept_declaration.c.concept_id == src.source_concept.c.id,
                )
                .where(src.source_concept_declaration.c.report_id == report_id)
                .distinct()
            )
        ]
        dimensional = (
            select(src.source_context_dimension.c.context_id)
            .where(src.source_context_dimension.c.context_id == src.source_context.c.id)
            .exists()
        )
        fact_concepts = [
            (row.namespace_uri, row.local_name)
            for row in conn.execute(
                select(src.source_concept.c.namespace_uri, src.source_concept.c.local_name)
                .join(src.source_fact, src.source_fact.c.concept_id == src.source_concept.c.id)
                .join(src.source_context, src.source_fact.c.context_id == src.source_context.c.id)
                .where(src.source_fact.c.report_id == report_id)
                .where(~dimensional)
                .distinct()
            )
        ]
    return QualityFilingSource(
        accession=accession,
        cik=meta.cik,
        form=meta.form,
        report_period_year=report_year,
        declared_namespaces=tuple(namespace for namespace, _local in declared),
        declared_concepts=tuple(declared),
        fact_concepts=tuple(fact_concepts),
    )


def load_filing_engine(engine: Engine, accession: str) -> LoadedFiling | None:
    with engine.connect() as conn:
        return load_filing(conn, accession)
