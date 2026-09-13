"""Constructed two-issuer / two-accession source corpus for mapping inspection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import Connection, Engine

from edgar.db.source import catalog_source_filing, persist_extraction
from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.domain.concept_id import concept_id
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.objects import ObjectStore
from edgar.xbrl.records import ExpandedQName
from edgar.xbrl.source_records import (
    EXTRACTOR_VERSION,
    ConceptRecord,
    ContextDimensionRecord,
    ContextRecord,
    ElementLocator,
    FactRecord,
    FilingExtraction,
    ReportExtraction,
    UnitMeasureRecord,
    UnitRecord,
)

NS = "http://example.com/acme"
DIM_NS = "http://example.com/acme/dim"
SALES_LOCAL = "NetSales"
SALES_QNAME = f"{{{NS}}}{SALES_LOCAL}"
ISSUER_A = "0000000001"
ISSUER_B = "0000000002"
ACCESSION_A_2023 = "0000000001-23-000001"
ACCESSION_A_2024 = "0000000001-24-000001"
ACCESSION_A_UNDATED = "0000000001-24-000099"
ACCESSION_B_2024 = "0000000002-24-000001"
DOC_A = "accession/a.htm"
DOC_B = "accession/b.htm"


@dataclass(frozen=True)
class MappingSourceCorpus:
    sales_concept_id: UUID
    sales_qname: str = SALES_QNAME
    issuer_a: str = ISSUER_A
    issuer_b: str = ISSUER_B
    accession_a_2023: str = ACCESSION_A_2023
    accession_a_2024: str = ACCESSION_A_2024
    accession_a_undated: str = ACCESSION_A_UNDATED
    accession_b_2024: str = ACCESSION_B_2024


def sales_concept_id() -> UUID:
    return concept_id(NS, SALES_LOCAL)


def seed_mapping_source_corpus(engine: Engine, data_root: Path) -> MappingSourceCorpus:
    """Persist consolidated, segment, duplicate, and undated NetSales facts."""
    store = ObjectStore(data_root)
    with engine.begin() as conn:
        _catalog_and_extract(
            conn,
            store,
            cik=ISSUER_A,
            name="Acme",
            accession=ACCESSION_A_2023,
            filing_date=date(2024, 2, 15),
            report_period_end=date(2023, 12, 31),
            year=2023,
            facts=_year_facts(
                year=2023,
                consolidated=Decimal("90"),
                documents=(DOC_A,),
            ),
        )
        _catalog_and_extract(
            conn,
            store,
            cik=ISSUER_A,
            name="Acme",
            accession=ACCESSION_A_2024,
            filing_date=date(2025, 2, 15),
            report_period_end=date(2024, 12, 31),
            year=2024,
            facts=_year_facts(
                year=2024,
                consolidated=Decimal("100"),
                duplicate=Decimal("100"),
                segment=Decimal("40"),
                documents=(DOC_A, DOC_B),
            ),
        )
        _catalog_and_extract(
            conn,
            store,
            cik=ISSUER_A,
            name="Acme",
            accession=ACCESSION_A_UNDATED,
            filing_date=date(2025, 3, 1),
            report_period_end=None,
            year=2024,
            facts=_year_facts(
                year=2024,
                consolidated=Decimal("7"),
                documents=(DOC_A,),
                locator_prefix="undated",
            ),
        )
        _catalog_and_extract(
            conn,
            store,
            cik=ISSUER_B,
            name="Beta",
            accession=ACCESSION_B_2024,
            filing_date=date(2025, 2, 20),
            report_period_end=date(2024, 12, 31),
            year=2024,
            facts=_year_facts(
                year=2024,
                consolidated=Decimal("50"),
                documents=(DOC_A,),
                locator_prefix="beta",
            ),
        )
    return MappingSourceCorpus(sales_concept_id=sales_concept_id())


def _qname(local: str, namespace: str = NS) -> ExpandedQName:
    return ExpandedQName(namespace_uri=namespace, local_name=local)


def _locator(value: str) -> ElementLocator:
    return ElementLocator(scheme="xml_id", value=value)


def _report_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _year_facts(
    *,
    year: int,
    consolidated: Decimal,
    documents: tuple[str, ...],
    duplicate: Decimal | None = None,
    segment: Decimal | None = None,
    locator_prefix: str = "sales",
) -> tuple[FactRecord, ...]:
    facts: list[FactRecord] = [
        FactRecord(
            source_order=0,
            concept=_qname(SALES_LOCAL),
            source_context_id="c-cons",
            value_status="valid",
            source_unit_id="u1",
            raw_lexical_value=format(consolidated, "f"),
            resolved_value_kind="numeric",
            resolved_numeric=consolidated,
            source_document_relative_path=documents[0],
            source_locator=_locator(f"{locator_prefix}-cons-{year}"),
        )
    ]
    order = 1
    if duplicate is not None:
        facts.append(
            FactRecord(
                source_order=order,
                concept=_qname(SALES_LOCAL),
                source_context_id="c-cons",
                value_status="valid",
                source_unit_id="u1",
                raw_lexical_value=format(duplicate, "f"),
                resolved_value_kind="numeric",
                resolved_numeric=duplicate,
                source_document_relative_path=documents[-1],
                source_locator=_locator(f"{locator_prefix}-dup-{year}"),
            )
        )
        order += 1
    if segment is not None:
        facts.append(
            FactRecord(
                source_order=order,
                concept=_qname(SALES_LOCAL),
                source_context_id="c-seg",
                value_status="valid",
                source_unit_id="u1",
                raw_lexical_value=format(segment, "f"),
                resolved_value_kind="numeric",
                resolved_numeric=segment,
                source_document_relative_path=documents[0],
                source_locator=_locator(f"{locator_prefix}-seg-{year}"),
            )
        )
    return tuple(facts)


def _catalog_and_extract(
    conn: Connection,
    store: ObjectStore,
    *,
    cik: str,
    name: str,
    accession: str,
    filing_date: date,
    report_period_end: date | None,
    year: int,
    facts: tuple[FactRecord, ...],
) -> None:
    paths = tuple(
        dict.fromkeys(
            fact.source_document_relative_path
            for fact in facts
            if fact.source_document_relative_path
        )
    )
    bundle = _bundle(
        store,
        cik=cik,
        accession=accession,
        filing_date=filing_date,
        report_period_end=report_period_end,
        paths=paths,
    )
    catalog = catalog_source_filing(conn, bundle, issuer_name=name)
    extraction = FilingExtraction(
        reports=(
            _report(
                accession=accession,
                year=year,
                entity_identifier=cik,
                facts=facts,
                paths=paths,
            ),
        )
    )
    persist_extraction(conn, filing_id=catalog.filing_id, extraction=extraction)


def _bundle(
    store: ObjectStore,
    *,
    cik: str,
    accession: str,
    filing_date: date,
    report_period_end: date | None,
    paths: tuple[str, ...],
) -> FilingBundle:
    artifacts: list[BundleArtifact] = []
    bindings: list[UriBinding] = []
    uris: list[str] = []
    for index, path in enumerate(paths):
        obj = store.put_bytes(f"{accession}:{path}".encode())
        artifacts.append(
            BundleArtifact(
                logical_path=path,
                content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
                artifact_kind="primary_document" if index == 0 else "attachment",
                required=True,
            )
        )
        uri = f"https://example.com/{path}"
        uris.append(uri)
        bindings.append(
            UriBinding(
                document_uri=uri,
                artifact_path=path,
                content_sha256=obj.sha256,
                replay_aliases=(),
            )
        )
    artifact_tuple = tuple(artifacts)
    return FilingBundle(
        filing=FilingIdentity(
            cik=cik,
            accession=accession,
            form_type="10-K",
            filing_date=filing_date,
            accepted_at=None,
            report_period_end=report_period_end,
            primary_document=Path(paths[0]).name,
        ),
        payload_hash=compute_payload_hash(artifact_tuple),
        artifacts=artifact_tuple,
        report_inputs=(InstanceReportInput(document_uris=(uris[0],)),),
        uri_bindings=tuple(bindings),
    )


def _report(
    *,
    accession: str,
    year: int,
    entity_identifier: str,
    facts: tuple[FactRecord, ...],
    paths: tuple[str, ...],
) -> ReportExtraction:
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    contexts = [
        ContextRecord(
            source_context_id="c-cons",
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier=entity_identifier,
            period_kind="duration",
            period_start=start,
            period_end=end,
            source_document_relative_path=paths[0],
            source_locator=_locator(f"ctx-cons-{year}"),
        )
    ]
    dimensions: list[ContextDimensionRecord] = []
    if any(fact.source_context_id == "c-seg" for fact in facts):
        contexts.append(
            ContextRecord(
                source_context_id="c-seg",
                entity_scheme="http://www.sec.gov/CIK",
                entity_identifier=entity_identifier,
                period_kind="duration",
                period_start=start,
                period_end=end,
                source_document_relative_path=paths[0],
                source_locator=_locator(f"ctx-seg-{year}"),
            )
        )
        dimensions.append(
            ContextDimensionRecord(
                source_context_id="c-seg",
                dimension=_qname("BusinessSegment", DIM_NS),
                context_element="segment",
                member_kind="explicit",
                member=_qname("NorthAmerica", DIM_NS),
                source_document_relative_path=paths[0],
                source_locator=_locator(f"dim-seg-{year}"),
            )
        )
    concepts = [
        ConceptRecord(namespace_uri=NS, local_name=SALES_LOCAL),
        ConceptRecord(namespace_uri=DIM_NS, local_name="BusinessSegment"),
        ConceptRecord(namespace_uri=DIM_NS, local_name="NorthAmerica"),
    ]
    return ReportExtraction(
        report_input={"kind": "instance", "document_uris": [f"https://example.com/{paths[0]}"]},
        report_key=_report_key(accession, "sales"),
        extractor_version=EXTRACTOR_VERSION,
        arelle_version="2.43.1",
        arelle_item_fact_count=len(facts),
        concepts=tuple(concepts),
        contexts=tuple(contexts),
        dimensions=tuple(dimensions),
        units=(
            UnitRecord(
                source_unit_id="u1",
                source_document_relative_path=paths[0],
                source_locator=_locator("unit-usd"),
            ),
        ),
        measures=(
            UnitMeasureRecord(
                source_unit_id="u1",
                side="numerator",
                ordinal=1,
                measure=ExpandedQName(
                    namespace_uri="http://www.xbrl.org/2003/iso4217",
                    local_name="USD",
                ),
            ),
        ),
        facts=facts,
    )
