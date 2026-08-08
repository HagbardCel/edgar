"""Unit tests for CIK/accession identifiers."""

from __future__ import annotations

import pytest

from edgar.domain.identifiers import (
    accession_archive_base,
    accession_dashless,
    accession_to_cik,
    assert_cik_accession_consistent,
    validate_accession,
    validate_cik,
    validate_logical_path,
)


def test_normalize_cik() -> None:
    assert validate_cik("1065088") == "0001065088"
    assert validate_cik("0001065088") == "0001065088"


def test_cik_rejects_whitespace_and_signed() -> None:
    with pytest.raises(ValueError):
        validate_cik(" 1065088")
    with pytest.raises(ValueError):
        validate_cik("+1065088")
    with pytest.raises(ValueError):
        validate_cik("-1065088")


def test_accession_validation() -> None:
    assert validate_accession("0001065088-24-000036") == "0001065088-24-000036"
    with pytest.raises(ValueError):
        validate_accession("000106508824000036")
    with pytest.raises(ValueError):
        validate_accession(" 0001065088-24-000036")


def test_cik_accession_consistency() -> None:
    assert_cik_accession_consistent("1065088", "0001065088-24-000036")
    with pytest.raises(ValueError):
        assert_cik_accession_consistent("0000000001", "0001065088-24-000036")


def test_archive_url_and_dashless() -> None:
    assert accession_dashless("0001065088-24-000036") == "000106508824000036"
    assert accession_to_cik("0001065088-24-000036") == "0001065088"
    assert (
        accession_archive_base("1065088", "0001065088-24-000036")
        == "https://www.sec.gov/Archives/edgar/data/1065088/000106508824000036/"
    )


def test_logical_path_traversal_rejected() -> None:
    with pytest.raises(ValueError):
        validate_logical_path("../etc/passwd")
    with pytest.raises(ValueError):
        validate_logical_path("/absolute")
    assert validate_logical_path("accession/a.htm") == "accession/a.htm"
