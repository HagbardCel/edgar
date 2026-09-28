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


def _form_for_accession(sample: Mapping[str, SampleRow], accession: str) -> str | None:
    row = sample.get(accession)
    if row is None:
        return None
    form = row.form.strip()
    return form or None


def summarize_extract_by_form(
    extract_records: Sequence[Mapping[str, object]],
    sample_csv: Path,
) -> ExtractSummary:
    sample = load_sample_csv(sample_csv)
    by_form: dict[str, list[bool]] = {}
    for record in extract_records:
        accession = str(record.get("accession") or "").strip()
        if not accession:
            continue
        form = _form_for_accession(sample, accession)
        if form is None:
            form = "unknown"
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
