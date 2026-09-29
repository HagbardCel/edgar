"""Join P2 extract reports with sample metadata for gate evaluation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from edgar.financials.sample_index import SampleRow, load_sample_csv

PRIMARY_FORM = "10-K"
AMENDMENT_FORM = "10-K/A"
PRIMARY_SUCCESS_RATE_MIN = 0.90


class ExtractPopulationError(ValueError):
    """Extract report accessions do not match the sample CSV population."""


@dataclass(frozen=True)
class FormExtractCounts:
    attempted: int
    succeeded: int
    failed: int

    @property
    def success_rate(self) -> float | None:
        if self.attempted == 0:
            return None
        return self.succeeded / self.attempted


@dataclass(frozen=True)
class ExtractSummary:
    by_form: Mapping[str, FormExtractCounts]
    primary: FormExtractCounts
    amendments: FormExtractCounts

    def primary_meets_gate(self, minimum: float = PRIMARY_SUCCESS_RATE_MIN) -> bool:
        rate = self.primary.success_rate
        return rate is not None and rate >= minimum


def assert_extract_population_matches_sample(
    extract_records: Sequence[Mapping[str, object]],
    sample_csv: Path,
) -> None:
    sample = load_sample_csv(sample_csv)
    report_accessions: set[str] = set()
    for record in extract_records:
        accession = str(record.get("accession") or "").strip()
        if not accession:
            raise ExtractPopulationError("extract report row missing accession")
        if accession in report_accessions:
            raise ExtractPopulationError(f"duplicate accession in extract report: {accession}")
        report_accessions.add(accession)
    sample_accessions = set(sample.keys())
    if report_accessions != sample_accessions:
        missing = sorted(sample_accessions - report_accessions)
        extra = sorted(report_accessions - sample_accessions)
        raise ExtractPopulationError(
            f"extract report population mismatch: missing={missing[:5]} "
            f"extra={extra[:5]} (showing up to 5 each)",
        )


def _form_for_accession(sample: Mapping[str, SampleRow], accession: str) -> str:
    row = sample.get(accession)
    if row is None:
        raise ExtractPopulationError(f"accession {accession} missing from sample csv")
    form = row.form.strip()
    if not form:
        raise ExtractPopulationError(f"accession {accession} has empty form in sample csv")
    return form


def summarize_extract_by_form(
    extract_records: Sequence[Mapping[str, object]],
    sample_csv: Path,
) -> ExtractSummary:
    assert_extract_population_matches_sample(extract_records, sample_csv)
    sample = load_sample_csv(sample_csv)
    by_form: dict[str, list[bool]] = {}
    for record in extract_records:
        accession = str(record.get("accession") or "").strip()
        form = _form_for_accession(sample, accession)
        success = bool(record.get("success"))
        by_form.setdefault(form, []).append(success)

    def _counts(form_key: str) -> FormExtractCounts:
        outcomes = by_form.get(form_key, [])
        succeeded = sum(1 for ok in outcomes if ok)
        return FormExtractCounts(
            attempted=len(outcomes),
            succeeded=succeeded,
            failed=len(outcomes) - succeeded,
        )

    primary = _counts(PRIMARY_FORM)
    amendments = _counts(AMENDMENT_FORM)
    all_forms = {
        form: FormExtractCounts(
            attempted=len(outcomes),
            succeeded=sum(1 for ok in outcomes if ok),
            failed=sum(1 for ok in outcomes if not ok),
        )
        for form, outcomes in by_form.items()
    }
    return ExtractSummary(by_form=all_forms, primary=primary, amendments=amendments)


def load_extract_records(report_path: Path) -> list[dict[str, object]]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    records = payload.get("accessions") or []
    if not isinstance(records, list):
        raise ValueError("report accessions must be a list")
    return [row for row in records if isinstance(row, dict)]
