"""Unit tests for half-bounded mapping interval helpers."""

from __future__ import annotations

from datetime import date

from edgar.registry.interval import interval_contains, intervals_overlap, scopes_overlap


def test_unbounded_contains_null_period_end() -> None:
    assert interval_contains(valid_from=None, valid_to=None, report_period_end=None)
    assert interval_contains(valid_from=None, valid_to=None, report_period_end=date(2020, 1, 1))


def test_half_bounded_contains() -> None:
    start = date(2020, 1, 1)
    assert interval_contains(valid_from=start, valid_to=None, report_period_end=date(2020, 1, 1))
    assert interval_contains(valid_from=start, valid_to=None, report_period_end=date(2021, 12, 31))
    assert not interval_contains(
        valid_from=start, valid_to=None, report_period_end=date(2019, 12, 31)
    )
    assert not interval_contains(valid_from=start, valid_to=None, report_period_end=None)
    assert interval_contains(
        valid_from=None, valid_to=date(2020, 12, 31), report_period_end=date(2020, 12, 31)
    )
    assert not interval_contains(
        valid_from=None, valid_to=date(2020, 12, 31), report_period_end=date(2021, 1, 1)
    )


def test_interval_overlap_null_unbounded() -> None:
    assert intervals_overlap(date(2020, 1, 1), None, date(2021, 1, 1), date(2021, 12, 31))
    assert not intervals_overlap(
        date(2020, 1, 1), date(2020, 12, 31), date(2021, 1, 1), date(2021, 12, 31)
    )
    assert intervals_overlap(None, None, date(2010, 1, 1), date(2010, 12, 31))


def test_issuer_scopes_do_not_overlap_across_ciks() -> None:
    assert not scopes_overlap(
        left_scope="issuer",
        left_issuer_cik="0000000001",
        left_from=None,
        left_to=None,
        right_scope="issuer",
        right_issuer_cik="0000000002",
        right_from=None,
        right_to=None,
    )
    assert scopes_overlap(
        left_scope="global",
        left_issuer_cik=None,
        left_from=None,
        left_to=None,
        right_scope="issuer",
        right_issuer_cik="0000000002",
        right_from=None,
        right_to=None,
    )
