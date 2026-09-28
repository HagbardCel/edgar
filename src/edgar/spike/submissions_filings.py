"""Iterate 10-K rows from SEC submissions JSON (recent + one historical block)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from edgar.domain.identifiers import validate_accession, validate_cik

_ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})


@dataclass(frozen=True)
class SubmissionsFilingRow:
    cik: str
    accession: str
    form: str
    filing_date: date | None
    report_period_end: date | None
    sic: str | None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def _rows_from_block(
    cik: str,
    block: Mapping[str, Any],
    *,
    sic: str | None,
) -> Iterator[SubmissionsFilingRow]:
    accessions = block.get("accessionNumber") or []
    forms = block.get("form") or []
    filing_dates = block.get("filingDate") or []
    report_dates = block.get("reportDate") or []
    for index, raw_accession in enumerate(accessions):
        if not isinstance(raw_accession, str):
            continue
        try:
            accession = validate_accession(raw_accession)
        except ValueError:
            continue
        form = forms[index] if index < len(forms) else None
        if form not in _ANNUAL_FORMS:
            continue
        filing_date = _parse_date(filing_dates[index] if index < len(filing_dates) else None)
        report_end = _parse_date(report_dates[index] if index < len(report_dates) else None)
        yield SubmissionsFilingRow(
            cik=validate_cik(cik),
            accession=accession,
            form=str(form),
            filing_date=filing_date,
            report_period_end=report_end,
            sic=sic,
        )


def iter_submissions_annual_filings(
    cik: str,
    payload: Mapping[str, Any],
    *,
    historical_blocks: tuple[Mapping[str, Any], ...] = (),
) -> Iterator[SubmissionsFilingRow]:
    """Yield 10-K / 10-K/A rows from recent and optional historical filing blocks."""
    sic_raw = payload.get("sic")
    sic = str(sic_raw).strip() if sic_raw not in (None, "") else None
    filings = payload.get("filings") or {}
    recent = filings.get("recent") or {}
    yield from _rows_from_block(cik, recent, sic=sic)
    for block in historical_blocks:
        yield from _rows_from_block(cik, block, sic=sic)
