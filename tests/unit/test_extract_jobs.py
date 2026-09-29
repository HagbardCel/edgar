"""Accession-file parser and batch-extract report semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar.ingestion.accession_file import (
    AccessionFileError,
    parse_accession_file,
    parse_accession_lines,
)
from edgar.ingestion.batch_extract import AccessionExtractRecord, run_batch_extract


def test_parser_accepts_one_accession_per_line() -> None:
    text = "0001065088-23-000006\n0000104169-24-000056\n"
    assert parse_accession_lines(text) == (
        "0001065088-23-000006",
        "0000104169-24-000056",
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n",
        "0001065088-23-000006\n\n",
        "# comment\n",
        "0001065088-23-000006\n# note\n",
        "not-an-accession\n",
        "0001065088-23-000006 \n",
        "0001065088-23-000006\n0001065088-23-000006\n",
    ],
)
def test_parser_rejects_blank_comments_malformed_and_duplicates(text: str) -> None:
    with pytest.raises(AccessionFileError):
        parse_accession_lines(text)


def test_parser_reads_frozen_spike_baseline() -> None:
    path = Path(__file__).resolve().parents[2] / "fixtures" / "spike" / "p2-accessions-baseline.txt"
    accessions = parse_accession_file(path)
    assert len(accessions) == 6
    assert len(set(accessions)) == 6


def _record(accession: str, *, success: bool) -> AccessionExtractRecord:
    return AccessionExtractRecord(
        accession=accession,
        success=success,
        wall_seconds=0.1,
        fact_count=3 if success else None,
        declaration_count=2 if success else None,
        relationship_count=1 if success else None,
        extractor_version="source-extract-v6",
        failure_class=None if success else "BundleResolutionError",
        failure_message=None if success else "missing bundle",
    )


def test_batch_report_is_sorted_and_partial_failure_is_not_ok(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake(data_root: str, database_url: str, accession: str) -> AccessionExtractRecord:
        del data_root, database_url
        calls.append(accession)
        return _record(accession, success=accession.endswith("000001"))

    result = run_batch_extract(
        data_root=tmp_path,
        database_url="postgresql+psycopg://unused",
        accessions=("0000000001-00-000002", "0000000001-00-000001"),
        jobs=1,
        extract_fn=fake,
    )
    assert calls == ["0000000001-00-000002", "0000000001-00-000001"]
    assert result.ok is False
    assert [record.accession for record in result.records] == [
        "0000000001-00-000001",
        "0000000001-00-000002",
    ]
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert [row["accession"] for row in payload["accessions"]] == [
        "0000000001-00-000001",
        "0000000001-00-000002",
    ]
    assert payload["accessions"][0]["success"] is True
    assert payload["accessions"][1]["failure_class"] == "BundleResolutionError"
    assert result.report_path == tmp_path / "reports" / "p2-extract.json"
