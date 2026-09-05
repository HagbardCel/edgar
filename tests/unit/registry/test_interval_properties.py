"""Hypothesis properties for mapping interval helpers."""

from __future__ import annotations

from datetime import date

from hypothesis import assume, given
from hypothesis import strategies as st

from edgar.registry.interval import interval_contains, intervals_overlap, scopes_overlap

_DATES = st.dates(min_value=date(1990, 1, 1), max_value=date(2040, 12, 31))
_OPTIONAL_DATES = st.one_of(st.none(), _DATES)
_CIKS = st.sampled_from(["0000000001", "0000000002", "0000000003"])


def _ordered(left: date | None, right: date | None) -> bool:
    return left is None or right is None or left <= right


@given(_OPTIONAL_DATES, _OPTIONAL_DATES, _OPTIONAL_DATES)
def test_contains_matches_half_bounded_spec(
    valid_from: date | None, valid_to: date | None, period: date | None
) -> None:
    assume(_ordered(valid_from, valid_to))
    expected = True
    if valid_from is not None or valid_to is not None:
        expected = period is not None
        if expected and valid_from is not None:
            expected = period >= valid_from
        if expected and valid_to is not None:
            expected = period <= valid_to
    assert (
        interval_contains(valid_from=valid_from, valid_to=valid_to, report_period_end=period)
        is expected
    )


@given(_OPTIONAL_DATES, _OPTIONAL_DATES, _OPTIONAL_DATES, _OPTIONAL_DATES)
def test_overlap_is_symmetric(
    left_from: date | None,
    left_to: date | None,
    right_from: date | None,
    right_to: date | None,
) -> None:
    assume(_ordered(left_from, left_to) and _ordered(right_from, right_to))
    assert intervals_overlap(left_from, left_to, right_from, right_to) == intervals_overlap(
        right_from, right_to, left_from, left_to
    )


@given(
    st.sampled_from(["global", "issuer"]),
    _CIKS,
    st.sampled_from(["global", "issuer"]),
    _CIKS,
)
def test_distinct_issuer_scopes_do_not_overlap(
    left_scope: str, left_cik: str, right_scope: str, right_cik: str
) -> None:
    left_issuer = left_cik if left_scope == "issuer" else None
    right_issuer = right_cik if right_scope == "issuer" else None
    overlap = scopes_overlap(
        left_scope=left_scope,
        left_issuer_cik=left_issuer,
        left_from=None,
        left_to=None,
        right_scope=right_scope,
        right_issuer_cik=right_issuer,
        right_from=None,
        right_to=None,
    )
    if left_scope == "issuer" and right_scope == "issuer" and left_cik != right_cik:
        assert overlap is False
    else:
        assert overlap is True
