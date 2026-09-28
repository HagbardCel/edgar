"""Quality report over filing × metric slots.

Taxonomy release for P2 measurement comes from captured DTS closure XSD
``targetNamespace`` values (see ``taxonomy_availability``), not from bounded
``source.concept_declaration`` rows or selected observations. Eligible
observation statuses partition ``n_slot_eligible``.
``wrong_form`` is ``n_ineligible_wrong_form`` and sits outside that partition.
Oracle labels partition ``n_slots`` separately and never change the observation.

Identity columns copy ``BuildResult.findings`` once per accession in the cell.
This module does not rerun identity checks.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy.engine import Engine

from edgar.financials.census import name_reuse_aggregate, qname_census
from edgar.financials.companyfacts_cache import load_cached_companyfacts
from edgar.financials.decisions import (
    DecisionRegistry,
    concept_matches_decision,
    decision_applies_to_filing,
)
from edgar.financials.models import FactRow, Observation
from edgar.financials.oracle import OracleComparison, oracle_comparison_for_observation
from edgar.financials.sample_index import SampleRow, load_sample_csv
from edgar.financials.select import ANNUAL_FORMS
from edgar.financials.source_load import LoadedFiling, load_filing, load_quality_filing_source
from edgar.financials.taxonomy_availability import (
    FilingTaxonomyAvailability,
    TaxonomyAvailabilityError,
    load_filing_taxonomy_availability,
)
from edgar.financials.taxonomy_release import filing_taxonomy_release, us_gaap_release_token
from edgar.storage.objects import write_bytes_atomic, write_json_atomic

_ORACLE_FINDING_STATUSES = frozenset({"differ", "ambiguous"})
_IDENTITY_INDEX = {"pass": 0, "fail": 1, "not_applicable": 2}


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
    n_ineligible_wrong_form: int = 0
    n_value: int = 0
    n_missing: int = 0
    n_conflict: int = 0
    n_unsupported: int = 0
    n_reason_decision_scope: int = 0
    n_reason_other_unsupported: int = 0
    n_decision_applicable: int = 0
    n_no_applicable_decision: int = 0
    identity_pass: int = 0
    identity_fail: int = 0
    identity_na: int = 0
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
            "n_ineligible_wrong_form": self.n_ineligible_wrong_form,
            "n_value": self.n_value,
            "n_missing": self.n_missing,
            "n_conflict": self.n_conflict,
            "n_unsupported": self.n_unsupported,
            "n_reason_decision_scope": self.n_reason_decision_scope,
            "n_reason_other_unsupported": self.n_reason_other_unsupported,
            "n_decision_applicable": self.n_decision_applicable,
            "n_no_applicable_decision": self.n_no_applicable_decision,
            "identity_pass": self.identity_pass,
            "identity_fail": self.identity_fail,
            "identity_na": self.identity_na,
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
    declared_concepts: frozenset[tuple[str, str]]
    taxonomy_concepts: frozenset[tuple[str, str]]


def _rate(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return format(Decimal(numerator) / Decimal(denominator), "f")


def slot_decision_applicable(
    frame: FilingFrame,
    metric: str,
    registry: DecisionRegistry,
) -> bool:
    """Eligible slot whose exact US-GAAP decision matches a global taxonomy concept.

    Matching uses captured DTS closure XSD global element declarations and
    ``concept_matches_decision``, including ``exclude_qnames``.
    """
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
        for namespace, local_name in frame.taxonomy_concepts:
            token = us_gaap_release_token(namespace)
            if token is None:
                continue
            if frame.filing_taxonomy_release != "mixed" and token != frame.filing_taxonomy_release:
                continue
            if concept_matches_decision(record, frame.cik, namespace, local_name):
                return True
    return False


def filing_frame_for_source(
    accession: str,
    cik: str,
    form: str,
    *,
    observation_years: Sequence[str | None],
    report_period_year: str | None,
    industry_bucket: str,
    declared_concepts: Sequence[tuple[str, str]],
    taxonomy_availability: FilingTaxonomyAvailability | None = None,
    taxonomy_concepts: Iterable[tuple[str, str]] | None = None,
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
    if taxonomy_availability is not None:
        taxonomy_release = taxonomy_availability.filing_taxonomy_release
        concepts = taxonomy_availability.concepts
    else:
        concepts = frozenset(taxonomy_concepts or ())
        taxonomy_release = filing_taxonomy_release(namespace for namespace, _local in concepts)
    return FilingFrame(
        accession=accession,
        cik=cik,
        form=form,
        fiscal_year=fiscal_year,
        industry_bucket=industry_bucket or "unknown",
        filing_taxonomy_release=taxonomy_release,
        declared_concepts=frozenset(declared_concepts),
        taxonomy_concepts=concepts,
    )


def _identity_counts(
    findings: Sequence[Mapping[str, str]],
) -> dict[str, tuple[int, int, int]]:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for finding in findings:
        accession = finding.get("accession")
        status = finding.get("status")
        if not isinstance(accession, str) or not accession:
            raise QualityReportError("identity finding is missing accession")
        index = _IDENTITY_INDEX.get(status or "")
        if index is None:
            raise QualityReportError(f"unknown identity status {status!r}")
        counts[accession][index] += 1
    return {accession: (values[0], values[1], values[2]) for accession, values in counts.items()}


def _normalize_oracle_findings(
    findings: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in findings:
        status = item.get("status")
        if status not in _ORACLE_FINDING_STATUSES:
            raise QualityReportError(f"oracle finding status must be differ or ambiguous: {status}")
        values = item.get("oracle_values")
        if not isinstance(values, list | tuple):
            raise QualityReportError("oracle finding is missing oracle_values")
        rows.append(
            {
                "accession": str(item.get("accession") or ""),
                "metric": str(item.get("metric") or ""),
                "status": status,
                "family": str(item.get("family") or ""),
                "local_name": str(item.get("local_name") or ""),
                "observation": str(item.get("observation") or ""),
                "oracle_values": [str(value) for value in values],
            }
        )
    rows.sort(key=lambda row: (str(row["accession"]), str(row["metric"]), str(row["status"])))
    return rows


def build_quality_document(
    observations: Sequence[Observation],
    filings: Mapping[str, FilingFrame],
    registry: DecisionRegistry,
    oracle_by_slot: Mapping[tuple[str, str], str],
    census_facts: Sequence[tuple[str, str, str]] = (),
    identity_findings: Sequence[Mapping[str, str]] = (),
    oracle_findings: Sequence[Mapping[str, object]] = (),
    oracle_sources: Mapping[str, str] | None = None,
    filing_taxonomy_sources: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    pinned_oracle = dict(oracle_sources or {})
    pinned_taxonomy = dict(filing_taxonomy_sources or {})
    cells: dict[tuple[str, str, str, str], QualityCell] = {}
    members: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)

    def _cell(frame: FilingFrame, metric: str) -> tuple[tuple[str, str, str, str], QualityCell]:
        key = (metric, frame.fiscal_year, frame.filing_taxonomy_release, frame.industry_bucket)
        existing = cells.get(key)
        if existing is not None:
            return key, existing
        created = QualityCell(
            metric=metric,
            fiscal_year=frame.fiscal_year,
            filing_taxonomy_release=frame.filing_taxonomy_release,
            industry_bucket=frame.industry_bucket,
        )
        cells[key] = created
        return key, created

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
                declared_concepts=frozenset(),
                taxonomy_concepts=frozenset(),
            )
        key, cell = _cell(frame, observation.metric)
        members[key].add(observation.accession)
        cell.n_slots += 1
        if frame.form in ANNUAL_FORMS:
            cell.n_slot_eligible += 1
            if observation.status == "value":
                cell.n_value += 1
            elif observation.status == "missing":
                cell.n_missing += 1
            elif observation.status == "unsupported":
                cell.n_unsupported += 1
                if observation.reason == "decision_scope":
                    cell.n_reason_decision_scope += 1
                else:
                    cell.n_reason_other_unsupported += 1
            else:
                cell.n_conflict += 1
        else:
            cell.n_ineligible_wrong_form += 1
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

    identity = _identity_counts(identity_findings)
    for key, cell in cells.items():
        for accession in members[key]:
            passed, failed, na = identity.get(accession, (0, 0, 0))
            cell.identity_pass += passed
            cell.identity_fail += failed
            cell.identity_na += na

    rows: list[dict[str, object]] = []
    for key in sorted(cells):
        cell = cells[key]
        status_sum = cell.n_value + cell.n_missing + cell.n_unsupported + cell.n_conflict
        reason_sum = cell.n_reason_decision_scope + cell.n_reason_other_unsupported
        oracle_sum = (
            cell.oracle_agree
            + cell.oracle_differ
            + cell.oracle_absent
            + cell.oracle_ambiguous
            + cell.oracle_na
        )
        partitions = (
            status_sum == cell.n_slot_eligible
            and cell.n_ineligible_wrong_form + cell.n_slot_eligible == cell.n_slots
            and oracle_sum == cell.n_slots
            and reason_sum == cell.n_unsupported
        )
        if not partitions:
            raise QualityReportError(f"cell {key} does not partition its denominators")
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
        "filing_taxonomy_release_source": "captured US-GAAP XSD targetNamespaces in DTS closure",
        "identity_source": "build findings, once per accession in the cell",
        "decision_applicability_source": "captured DTS closure XSD schema documents",
        "cells": rows,
        "oracle_findings": _normalize_oracle_findings(oracle_findings),
        "oracle_sources": dict(sorted(pinned_oracle.items())),
        "filing_taxonomy_sources": dict(sorted(pinned_taxonomy.items())),
        "name_census": {
            "fact_scope": "non_dimensional",
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
        "Taxonomy release is from captured US-GAAP XSD namespaces in the DTS closure.",
        "Status counts partition eligible slots. Wrong-form slots are n_ineligible_wrong_form.",
        "Identity columns copy build findings once per accession in the cell.",
        "",
        "| metric | fiscal_year | taxonomy_release | industry | n_slots | n_slot_eligible | "
        "n_ineligible_wrong_form | n_value | n_missing | n_unsupported | n_conflict | "
        "n_decision_applicable | publication_rate | selector_yield | identity_pass | "
        "identity_fail | identity_na | oracle_agree | oracle_differ | oracle_absent | "
        "oracle_ambiguous | oracle_na |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
        "---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        lines.append(
            "| {metric} | {fiscal_year} | {filing_taxonomy_release} | {industry_bucket} | "
            "{n_slots} | {n_slot_eligible} | {n_ineligible_wrong_form} | {n_value} | "
            "{n_missing} | {n_unsupported} | {n_conflict} | {n_decision_applicable} | "
            "{publication_rate} | {selector_yield} | {identity_pass} | {identity_fail} | "
            "{identity_na} | {oracle_agree} | {oracle_differ} | {oracle_absent} | "
            "{oracle_ambiguous} | {oracle_na} |".format(**cell)
        )
    lines.extend(["", "## Oracle findings", ""])
    findings = document.get("oracle_findings")
    if not isinstance(findings, list) or not findings:
        lines.append("None.")
    else:
        for item in findings:
            if not isinstance(item, dict):
                continue
            values = item.get("oracle_values")
            rendered = ", ".join(str(value) for value in values) if isinstance(values, list) else ""
            lines.append(
                f"- {item.get('accession')} {item.get('metric')} {item.get('status')} "
                f"{item.get('family')}:{item.get('local_name')} "
                f"observation={item.get('observation')} oracle=[{rendered}]"
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


def oracle_slot_reports(
    observations: Sequence[Observation],
    facts_by_accession: Mapping[str, Mapping[int, FactRow]],
    payloads_by_cik: Mapping[str, str | bytes | None],
) -> tuple[dict[tuple[str, str], str], tuple[dict[str, object], ...]]:
    """Labels for every slot, plus differ/ambiguous findings. Does not fetch."""
    labels: dict[tuple[str, str], str] = {}
    findings: list[dict[str, object]] = []
    for observation in observations:
        comparison: OracleComparison = oracle_comparison_for_observation(
            observation,
            facts_by_accession.get(observation.accession, {}),
            payloads_by_cik.get(observation.cik),
        )
        labels[(observation.accession, observation.metric)] = comparison.status
        if comparison.status in _ORACLE_FINDING_STATUSES:
            findings.append(comparison.finding(observation))
    findings.sort(key=lambda row: (str(row["accession"]), str(row["metric"]), str(row["status"])))
    return labels, tuple(findings)


def write_quality_report(
    engine: Engine,
    observations: Sequence[Observation],
    registry: DecisionRegistry,
    *,
    sample_csv: Path,
    data_root: Path,
    output_json: Path,
    identity_findings: Sequence[Mapping[str, str]] = (),
) -> dict[str, object]:
    sample: dict[str, SampleRow] = {}
    if sample_csv.is_file():
        sample = load_sample_csv(sample_csv)
    years = _fiscal_years_by_accession(observations)
    accessions = tuple(dict.fromkeys(observation.accession for observation in observations))
    frames: dict[str, FilingFrame] = {}
    filing_taxonomy_sources: dict[str, dict[str, object]] = {}
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
            try:
                taxonomy = load_filing_taxonomy_availability(
                    data_root,
                    source.cik,
                    source.accession,
                )
            except TaxonomyAvailabilityError as exc:
                raise QualityReportError(str(exc)) from exc
            filing_taxonomy_sources[accession] = {
                "filing_taxonomy_release": taxonomy.filing_taxonomy_release,
                "schema_sha256s": list(taxonomy.schema_sha256s),
            }
            frames[accession] = filing_frame_for_source(
                source.accession,
                source.cik,
                source.form,
                observation_years=years.get(accession, ()),
                report_period_year=source.report_period_year,
                industry_bucket=industry,
                declared_concepts=source.declared_concepts,
                taxonomy_availability=taxonomy,
            )
            for namespace, local_name in source.fact_concepts:
                census.append((accession, namespace, local_name))
    payloads: dict[str, bytes | None] = {}
    oracle_sources: dict[str, str] = {}
    for observation in observations:
        if observation.cik in payloads:
            continue
        cached = load_cached_companyfacts(data_root, observation.cik)
        payloads[observation.cik] = cached.payload if cached is not None else None
        if cached is not None:
            oracle_sources[observation.cik] = cached.sha256
    oracle_by_slot, oracle_findings = oracle_slot_reports(
        observations,
        facts_by_accession,
        payloads,
    )
    document = build_quality_document(
        observations,
        frames,
        registry,
        oracle_by_slot,
        census,
        identity_findings,
        oracle_findings,
        oracle_sources,
        filing_taxonomy_sources,
    )
    write_json_atomic(output_json, document)
    markdown_path = output_json.with_suffix(".md")
    write_bytes_atomic(markdown_path, render_quality_markdown(document).encode("utf-8"))
    return document


def filing_facts_for_oracle(loaded: LoadedFiling | None) -> dict[int, FactRow]:
    if loaded is None:
        return {}
    return {fact.fact_id: fact for fact in loaded.facts}
