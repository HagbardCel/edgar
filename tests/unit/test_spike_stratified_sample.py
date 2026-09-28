"""Unit tests for P2 stratified accession selection."""

from __future__ import annotations

from datetime import date

import pytest

from edgar.spike.stratified_sample import (
    IssuerSeed,
    fiscal_year_bucket,
    select_stratified_filings,
)
from edgar.spike.submissions_filings import SubmissionsFilingRow


def test_fiscal_year_bucket_labels() -> None:
    assert fiscal_year_bucket(2011) == "2010-2012"
    assert fiscal_year_bucket(2024) == "2022-2025"
    assert fiscal_year_bucket(2005) is None


def _row(
    accession: str,
    cik: str,
    *,
    year: int,
    form: str = "10-K",
) -> SubmissionsFilingRow:
    return SubmissionsFilingRow(
        cik=cik,
        accession=accession,
        form=form,
        filing_date=date(year, 3, 1),
        report_period_end=date(year - 1, 12, 31),
        sic="1234",
    )


def test_select_stratified_respects_target_bounds() -> None:
    seeds = {
        "0000000001": IssuerSeed("0000000001", "retail", "large"),
        "0000000002": IssuerSeed("0000000002", "technology", "large"),
    }
    rows: list[SubmissionsFilingRow] = []
    for cik_index, cik in enumerate(seeds):
        for year in range(2010, 2026):
            acc = f"000000000{cik_index + 1}-{year % 100:02d}-000001"
            rows.append(_row(acc, cik, year=year))
    picks = select_stratified_filings(
        rows,
        seeds,
        target_min=10,
        target_max=15,
        per_bucket_min=1,
    )
    assert 10 <= len(picks) <= 15
    accessions = [pick.accession for pick in picks]
    assert len(accessions) == len(set(accessions))
    assert all(pick.industry_bucket in {"retail", "technology"} for pick in picks)


def test_select_stratified_raises_when_insufficient_candidates() -> None:
    seeds = {"0000000001": IssuerSeed("0000000001", "retail", "large")}
    rows = [_row("0000000001-24-000001", "0000000001", year=2024)]
    with pytest.raises(ValueError, match="need at least"):
        select_stratified_filings(rows, seeds, target_min=5, target_max=10)
