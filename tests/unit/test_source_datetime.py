"""Unit tests for optional offset-aware context ``*_at`` normalization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from edgar.db.source import _parse_offset_aware_datetime


def test_date_only_and_naive_datetime_leave_at_null() -> None:
    assert _parse_offset_aware_datetime("2024-12-31") is None
    assert _parse_offset_aware_datetime("2024-06-15T12:30:00") is None
    assert _parse_offset_aware_datetime(None) is None
    assert _parse_offset_aware_datetime("not-a-datetime") is None


def test_z_and_numeric_offset_populate_aware_datetime() -> None:
    zulu = _parse_offset_aware_datetime("2024-06-15T12:30:00Z")
    assert zulu == datetime(2024, 6, 15, 12, 30, tzinfo=UTC)
    offset = _parse_offset_aware_datetime("2024-06-15T12:30:00-04:00")
    assert offset is not None
    assert offset.tzinfo is not None
    assert offset.utcoffset() == timedelta(hours=-4)
    assert offset.year == 2024
    assert offset.month == 6
    assert offset.day == 15
