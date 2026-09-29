"""Unit tests for SEC submissions 10-K row iteration."""

from __future__ import annotations

from datetime import date

from edgar.spike.submissions_filings import iter_submissions_annual_filings


def test_iter_recent_annual_filings_skips_quarterly() -> None:
    payload = {
        "sic": "7370",
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-24-000123",
                    "0000320193-24-000050",
                ],
                "form": ["10-K", "10-Q"],
                "filingDate": ["2024-11-01", "2024-08-02"],
                "reportDate": ["2024-09-28", "2024-06-29"],
            },
        },
    }
    rows = list(iter_submissions_annual_filings("320193", payload))
    assert len(rows) == 1
    row = rows[0]
    assert row.accession == "0000320193-24-000123"
    assert row.cik == "0000320193"
    assert row.form == "10-K"
    assert row.filing_date == date(2024, 11, 1)
    assert row.report_period_end == date(2024, 9, 28)
    assert row.sic == "7370"


def test_iter_includes_historical_blocks() -> None:
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": [],
                "form": [],
                "filingDate": [],
                "reportDate": [],
            },
        },
    }
    historical = (
        {
            "accessionNumber": ["0000320193-10-000001"],
            "form": ["10-K/A"],
            "filingDate": ["2010-02-01"],
            "reportDate": ["2009-09-26"],
        },
    )
    rows = list(
        iter_submissions_annual_filings(
            "0000320193",
            payload,
            historical_blocks=historical,
        ),
    )
    assert len(rows) == 1
    assert rows[0].form == "10-K/A"
