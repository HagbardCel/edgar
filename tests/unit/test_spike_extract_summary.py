"""P2.3 extract summary joins sample CSV for primary gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar.spike.extract_summary import (
    ExtractPopulationError,
    assert_extract_population_matches_sample,
    summarize_extract_by_form,
)


def _write_sample(path: Path, rows: str) -> None:
    header = (
        "accession,cik,form,fiscal_year,sic,industry_bucket,issuer_size,taxonomy_era_note\n"
    )
    path.write_text(header + rows, encoding="utf-8")


def test_primary_success_rate_excludes_amendments(tmp_path: Path) -> None:
    sample = tmp_path / "sample.csv"
    _write_sample(
        sample,
        "0000000001-24-000001,0000000001,10-K,2023,7370,technology,large,\n"
        "0000000001-24-000002,0000000001,10-K/A,2023,7370,technology,large,\n"
        "0000000002-24-000001,0000000002,10-K,2023,7370,technology,large,\n",
    )
    records = [
        {"accession": "0000000001-24-000001", "success": True},
        {"accession": "0000000001-24-000002", "success": False},
        {"accession": "0000000002-24-000001", "success": False},
    ]
    summary = summarize_extract_by_form(records, sample)
    assert summary.primary.attempted == 2
    assert summary.primary.succeeded == 1
    assert summary.primary.success_rate == 0.5
    assert summary.amendments.attempted == 1
    assert summary.amendments.failed == 1
    assert summary.primary_meets_gate(0.90) is False


def test_population_mismatch_fails_closed(tmp_path: Path) -> None:
    sample = tmp_path / "sample.csv"
    _write_sample(
        sample,
        "0000000001-24-000001,0000000001,10-K,2023,7370,technology,large,\n"
        "0000000002-24-000001,0000000002,10-K,2023,7370,technology,large,\n",
    )
    records = [{"accession": "0000000001-24-000001", "success": True}]
    with pytest.raises(ExtractPopulationError, match="population mismatch"):
        assert_extract_population_matches_sample(records, sample)


def test_truncated_report_cannot_fake_perfect_primary_rate(tmp_path: Path) -> None:
    sample = tmp_path / "sample.csv"
    _write_sample(
        sample,
        "0000000001-24-000001,0000000001,10-K,2023,7370,technology,large,\n"
        "0000000002-24-000001,0000000002,10-K,2023,7370,technology,large,\n",
    )
    records = [{"accession": "0000000001-24-000001", "success": True}]
    with pytest.raises(ExtractPopulationError):
        summarize_extract_by_form(records, sample)


def test_summarize_script_gate_exit_code(tmp_path: Path) -> None:
    report = tmp_path / "p2-extract.json"
    sample = tmp_path / "sample.csv"
    _write_sample(
        sample,
        "0000000001-24-000001,0000000001,10-K,2023,7370,technology,large,\n",
    )
    report.write_text(
        json.dumps({"accessions": [{"accession": "0000000001-24-000001", "success": True}]}),
        encoding="utf-8",
    )
    from edgar.spike.extract_summary import load_extract_records, summarize_extract_by_form

    summary = summarize_extract_by_form(load_extract_records(report), sample)
    assert summary.primary_meets_gate() is True
