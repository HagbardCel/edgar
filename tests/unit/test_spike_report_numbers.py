"""P2 report numeric parsing."""

from __future__ import annotations

import pytest

from edgar.spike.report_numbers import (
    ReportFieldError,
    optional_report_float,
    parse_report_int,
    parse_report_int_field,
)


def test_parse_report_int_accepts_str_and_int() -> None:
    assert parse_report_int(42, field="x") == 42
    assert parse_report_int("42", field="x") == 42


def test_parse_report_int_rejects_bool() -> None:
    with pytest.raises(ReportFieldError):
        parse_report_int(True, field="x")


def test_optional_and_payload_field() -> None:
    row = {"wall_seconds": "1.5"}
    assert optional_report_float(row, "wall_seconds") == 1.5
    assert parse_report_int_field({"cumulative_retrieved": "3"}, "cumulative_retrieved") == 3
    assert parse_report_int_field({"retrieved": 2}, "cumulative_retrieved", fallback_field="retrieved") == 2
