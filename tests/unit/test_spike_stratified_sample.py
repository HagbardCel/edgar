"""Unit tests for P2 stratified accession selection."""

from __future__ import annotations

from datetime import date

import pytest

from edgar.spike.stratified_sample import (
    IssuerSeed,
    fiscal_year_bucket,
    is_primary_eligible,
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
        sic="7370",
    )


def test_select_primary_respects_target_bounds() -> None:
    seeds = {
        "0000000001": IssuerSeed("0000000001", "large"),
        "0000000002": IssuerSeed("0000000002", "large"),
    }
    rows: list[SubmissionsFilingRow] = []
    for cik_index, cik in enumerate(seeds):
        for year in range(2010, 2026):
            acc = f"000000000{cik_index + 1}-{year % 100:02d}-000001"
            rows.append(_row(acc, cik, year=year))
    sample = select_stratified_filings(
        rows,
        seeds,
        target_min=10,
        target_max=15,
        per_bucket_min=1,
    )
    assert 10 <= len(sample.primary) <= 15
    assert all(pick.form == "10-K" for pick in sample.primary)
    accessions = [pick.accession for pick in sample.primary]
    assert len(accessions) == len(set(accessions))


def test_amendments_and_pre_2010_do_not_satisfy_primary_target() -> None:
    seeds = {"0000000001": IssuerSeed("0000000001", "large")}
    rows = [
        _row("0000000001-08-000001", "0000000001", year=2008, form="10-K"),
        _row("0000000001-24-000002", "0000000001", year=2024, form="10-K/A"),
        _row("0000000001-23-000003", "0000000001", year=2023, form="10-K"),
    ]
    with pytest.raises(ValueError, match="need at least 5"):
        select_stratified_filings(rows, seeds, target_min=5, target_max=10)
    sample = select_stratified_filings(rows, seeds, target_min=1, target_max=5)
    assert len(sample.primary) == 1
    assert sample.primary[0].accession == "0000000001-23-000003"
    assert sample.amendment_count == 1
    assert sample.amendments[0].form == "10-K/A"


def test_pre_2010_primary_is_not_eligible() -> None:
    row = _row("0000000001-08-000001", "0000000001", year=2008, form="10-K")
    assert is_primary_eligible(row) is False
