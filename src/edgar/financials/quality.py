"""Quality report over filing × metric slots.

Taxonomy release is a property of the filing, taken from US-GAAP declarations
before selection. Observation statuses partition ``n_slots``. Oracle labels
partition ``n_slots`` separately and never change the observation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy.engine import Engine

from edgar.financials.census import name_reuse_aggregate, qname_census
from edgar.financials.companyfacts_cache import load_cached_companyfacts
from edgar.financials.decisions import DecisionRegistry, decision_applies_to_filing
from edgar.financials.models import FactRow, Observation
from edgar.financials.oracle import oracle_label_for_observation
from edgar.financials.sample_index import SampleRow, load_sample_csv
from edgar.financials.select import ANNUAL_FORMS
from edgar.financials.source_load import LoadedFiling, load_filing, load_quality_filing_source
from edgar.financials.taxonomy_release import filing_taxonomy_release, us_gaap_release_token
from edgar.storage.objects import write_bytes_atomic, write_json_atomic


class QualityReportError(ValueError):
    """A quality-report identity does not hold."""


@dataclass
class QualityCell:
    metric: str
    fiscal_year: str
    filing_taxonomy_release: str
    industry_bucket: str
    n_slots: int = 0
    n_slot_eligible: int = 0
    n_value: int = 0
    n_missing: int = 0
    n_conflict: int = 0
    n_unsupported: int = 0
    n_reason_wrong_form: int = 0
    n_reason_decision_scope: int = 0
    n_reason_other_unsupported: int = 0
    n_decision_applicable: int = 0
    n_no_applicable_decision: int = 0
    oracle_agree: int = 0
    oracle_differ: int = 0
    oracle_absent: int = 0
    oracle_ambiguous: int = 0
    oracle_na: int = 0
    publication_rate: str | None = None
    selector_yield: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "fiscal_year": self.fiscal_year,
            "filing_taxonomy_release": self.filing_taxonomy_release,
            "industry_bucket": self.industry_bucket,
            "n_slots": self.n_slots,
            "n_slot_eligible": self.n_slot_eligible,
            "n_value": self.n_value,
            "n_missing": self.n_missing,
            "n_conflict": self.n_conflict,
            "n_unsupported": self.n_unsupported,
            "n_reason_wrong_form": self.n_reason_wrong_form,
            "n_reason_decision_scope": self.n_reason_decision_scope,
            "n_reason_other_unsupported": self.n_reason_other_unsupported,
            "n_decision_applicable": self.n_decision_applicable,
            "n_no_applicable_decision": self.n_no_applicable_decision,
            "oracle_agree": self.oracle_agree,
            "oracle_differ": self.oracle_differ,
            "oracle_absent": self.oracle_absent,
            "oracle_ambiguous": self.oracle_ambiguous,
            "oracle_na": self.oracle_na,
            "publication_rate": self.publication_rate,
            "selector_yield": self.selector_yield,
        }


@dataclass(frozen=True)
class FilingFrame:
    accession: str
    cik: str
    form: str
    fiscal_year: str
    industry_bucket: str
    filing_taxonomy_release: str
    us_gaap_concepts: frozenset[tuple[str, str]]


def _rate(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return format(Decimal(numerator) / Decimal(denominator), "f")


def slot_decision_applicable(
    frame: FilingFrame,
    metric: str,
    registry: DecisionRegistry,
) -> bool:
    """Eligible slot with an exact decision that applies and is declared in the release."""
    if frame.form not in ANNUAL_FORMS:
        return False
    if frame.filing_taxonomy_release == "unknown":
        return False
    exact = [
        loaded.record
        for loaded in registry.decisions
        if not loaded.stale_inactive
        and loaded.record.status == "accepted"
        and loaded.record.relation == "exact"
        and loaded.record.metric == metric
        and loaded.record.source.family == "us-gaap"
        and decision_applies_to_filing(loaded.record, frame.cik)
    ]
    if not exact:
        return False
    for record in exact:
        local_name = record.source.local_name
        if frame.filing_taxonomy_release == "mixed":
            if any(name == local_name for name, _token in frame.us_gaap_concepts):
                return True
        elif any(
            name == local_name and token == frame.filing_taxonomy_release
            for name, token in frame.us_gaap_concepts
        ):
            return True
    return False


def _us_gaap_concepts(declared: Sequence[tuple[str, str]]) -> frozenset[tuple[str, str]]:
    concepts: set[tuple[str, str]] = set()
    for namespace, local_name in declared:
        token = us_gaap_release_token(namespace)
        if token is not None:
            concepts.add((local_name, token))
    return frozenset(concepts)


def filing_frame_for_source(
    accession: str,
    cik: str,
    form: str,
    *,
    observation_years: Sequence[str | None],
    report_period_year: str | None,
    industry_bucket: str,
    declared_concepts: Sequence[tuple[str, str]],
) -> FilingFrame:
    years = {year for year in observation_years if year}
    if len(years) == 1:
        fiscal_year = next(iter(years))
    elif len(years) > 1:
        fiscal_year = "mixed"
    elif report_period_year:
        fiscal_year = report_period_year
    else:
        fiscal_year = "unknown"
    namespaces = [namespace for namespace, _local in declared_concepts]
    return FilingFrame(
        accession=accession,
        cik=cik,
        form=form,
        fiscal_year=fiscal_year,
        industry_bucket=industry_bucket or "unknown",
        filing_taxonomy_release=filing_taxonomy_release(namespaces),
        us_gaap_concepts=_us_gaap_concepts(declared_concepts),
    )


def build_quality_document(
    observations: Sequence[Observation],
    filings: Mapping[str, FilingFrame],
    registry: DecisionRegistry,
    oracle_by_slot: Mapping[tuple[str, str], str],
    census_facts: Sequence[tuple[str, str, str]] = (),
) -> dict[str, object]:
    cells: dict[tuple[str, str, str, str], QualityCell] = {}

    def _cell(frame: FilingFrame, metric: str) -> QualityCell:
        key = (metric, frame.fiscal_year, frame.filing_taxonomy_release, frame.industry_bucket)
        existing = cells.get(key)
        if existing is not None:
            return existing
        created = QualityCell(
            metric=metric,
            fiscal_year=frame.fiscal_year,
            filing_taxonomy_release=frame.filing_taxonomy_release,
            industry_bucket=frame.industry_bucket,
        )
        cells[key] = created
        return created

    for observation in observations:
        frame = filings.get(observation.accession)
        if frame is None:
            frame = FilingFrame(
                accession=observation.accession,
                cik=observation.cik,
                form="",
                fiscal_year=observation.fy or "unknown",
                industry_bucket="unknown",
                filing_taxonomy_release="unknown",
                us_gaap_concepts=frozenset(),
            )
        cell = _cell(frame, observation.metric)
        cell.n_slots += 1
        if frame.form in ANNUAL_FORMS:
            cell.n_slot_eligible += 1
        if observation.status == "value":
            cell.n_value += 1
        elif observation.status == "missing":
            cell.n_missing += 1
        elif observation.status == "unsupported":
            cell.n_unsupported += 1
            if observation.reason == "wrong_form":
                cell.n_reason_wrong_form += 1
            elif observation.reason == "decision_scope":
                cell.n_reason_decision_scope += 1
            else:
                cell.n_reason_other_unsupported += 1
        else:
            cell.n_conflict += 1
        applicable = slot_decision_applicable(frame, observation.metric, registry)
        if applicable:
            cell.n_decision_applicable += 1
        if observation.status == "value" and not applicable:
            raise QualityReportError(
                "published value without an applicable decision: "
                f"{observation.accession} {observation.metric}"
            )
        label = oracle_by_slot.get((observation.accession, observation.metric), "na")
        if label == "agree":
            cell.oracle_agree += 1
        elif label == "differ":
            cell.oracle_differ += 1
        elif label == "absent":
            cell.oracle_absent += 1
        elif label == "ambiguous":
            cell.oracle_ambiguous += 1
        elif label == "na":
            cell.oracle_na += 1
        else:
            raise QualityReportError(f"unknown oracle label {label}")

    rows: list[dict[str, object]] = []
    for key in sorted(cells):
        cell = cells[key]
        status_sum = cell.n_value + cell.n_missing + cell.n_unsupported + cell.n_conflict
        reason_sum = (
            cell.n_reason_wrong_form
            + cell.n_reason_decision_scope
            + cell.n_reason_other_unsupported
        )
        oracle_sum = (
            cell.oracle_agree
            + cell.oracle_differ
            + cell.oracle_absent
            + cell.oracle_ambiguous
            + cell.oracle_na
        )
        partitions = (
            status_sum == cell.n_slots
            and oracle_sum == cell.n_slots
            and reason_sum == cell.n_unsupported
        )
        if not partitions:
            raise QualityReportError(f"cell {key} does not partition n_slots")
        if not (cell.n_decision_applicable <= cell.n_slot_eligible <= cell.n_slots):
            raise QualityReportError(f"cell {key} breaks eligibility bounds")
        if cell.n_value > cell.n_decision_applicable:
            raise QualityReportError(f"cell {key} publishes more values than applicable decisions")
        cell.n_no_applicable_decision = cell.n_slot_eligible - cell.n_decision_applicable
        cell.publication_rate = _rate(cell.n_value, cell.n_slot_eligible)
        cell.selector_yield = _rate(cell.n_value, cell.n_decision_applicable)
        rows.append(cell.to_dict())

    return {
        "grain": "metric × fiscal_year × filing_taxonomy_release × industry_bucket",
        "filing_taxonomy_release_source": "us-gaap concept declarations",
        "cells": rows,
        "name_census": {
            "by_qname": list(qname_census(census_facts)),
            "name_reuse_aggregate": list(name_reuse_aggregate(census_facts)),
        },
    }


def render_quality_markdown(document: Mapping[str, object]) -> str:
    cells = document.get("cells")
    if not isinstance(cells, list):
        raise QualityReportError("quality document is missing cells")
    lines = [
        "# Quality report",
        "",
        "Taxonomy release is the filing's US-GAAP declaration release, not the selected concept.",
        "",
        "| metric | fiscal_year | taxonomy_release | industry | n_slots | n_slot_eligible | "
        "n_value | n_missing | n_unsupported | n_conflict | n_decision_applicable | "
        "publication_rate | selector_yield | oracle_agree | oracle_differ | oracle_absent | "
        "oracle_ambiguous | oracle_na |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        lines.append(
            "| {metric} | {fiscal_year} | {filing_taxonomy_release} | {industry_bucket} | "
            "{n_slots} | {n_slot_eligible} | {n_value} | {n_missing} | {n_unsupported} | "
            "{n_conflict} | {n_decision_applicable} | {publication_rate} | {selector_yield} | "
            "{oracle_agree} | {oracle_differ} | {oracle_absent} | {oracle_ambiguous} | "
            "{oracle_na} |".format(**cell)
        )
    lines.append("")
    return "\n".join(lines)


def _fiscal_years_by_accession(
    observations: Sequence[Observation],
) -> dict[str, list[str | None]]:
    grouped: dict[str, list[str | None]] = defaultdict(list)
    for observation in observations:
        grouped[observation.accession].append(observation.fy)
    return grouped


def write_quality_report(
    engine: Engine,
    observations: Sequence[Observation],
    registry: DecisionRegistry,
    *,
    sample_csv: Path,
    data_root: Path,
    output_json: Path,
) -> dict[str, object]:
    sample: dict[str, SampleRow] = {}
    if sample_csv.is_file():
        sample = load_sample_csv(sample_csv)
    years = _fiscal_years_by_accession(observations)
    accessions = tuple(dict.fromkeys(observation.accession for observation in observations))
    frames: dict[str, FilingFrame] = {}
    census: list[tuple[str, str, str]] = []
    facts_by_accession: dict[str, dict[int, FactRow]] = {}
    with engine.connect() as conn:
        for accession in accessions:
            source = load_quality_filing_source(conn, accession)
            loaded = load_filing(conn, accession)
            if loaded is not None:
                facts_by_accession[accession] = {fact.fact_id: fact for fact in loaded.facts}
            if source is None:
                continue
            industry = "unknown"
            sample_row = sample.get(accession)
            if sample_row is not None and sample_row.industry_bucket:
                industry = sample_row.industry_bucket
            frames[accession] = filing_frame_for_source(
                source.accession,
                source.cik,
                source.form,
                observation_years=years.get(accession, ()),
                report_period_year=source.report_period_year,
                industry_bucket=industry,
                declared_concepts=source.declared_concepts,
            )
            for namespace, local_name in source.fact_concepts:
                census.append((accession, namespace, local_name))
        oracle_by_slot = _oracle_labels(observations, facts_by_accession, data_root)
    document = build_quality_document(
        observations,
        frames,
        registry,
        oracle_by_slot,
        census,
    )
    write_json_atomic(output_json, document)
    markdown_path = output_json.with_suffix(".md")
    write_bytes_atomic(markdown_path, render_quality_markdown(document).encode("utf-8"))
    return document


def _oracle_labels(
    observations: Sequence[Observation],
    facts_by_accession: Mapping[str, Mapping[int, FactRow]],
    data_root: Path,
) -> dict[tuple[str, str], str]:
    cache: dict[str, bytes | None] = {}
    labels: dict[tuple[str, str], str] = {}
    for observation in observations:
        payload = cache.get(observation.cik)
        if observation.cik not in cache:
            payload = load_cached_companyfacts(data_root, observation.cik)
            cache[observation.cik] = payload
        facts = facts_by_accession.get(observation.accession, {})
        labels[(observation.accession, observation.metric)] = oracle_label_for_observation(
            observation,
            facts,
            payload,
        )
    return labels


def filing_facts_for_oracle(loaded: LoadedFiling | None) -> dict[int, FactRow]:
    if loaded is None:
        return {}
    return {fact.fact_id: fact for fact in loaded.facts}
