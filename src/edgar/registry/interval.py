"""Half-bounded report-period interval semantics for mapping assertions."""

from __future__ import annotations

from datetime import date


def interval_contains(
    *,
    valid_from: date | None,
    valid_to: date | None,
    report_period_end: date | None,
) -> bool:
    """Return whether assertion validity contains ``report_period_end``."""
    if valid_from is None and valid_to is None:
        return True
    if report_period_end is None:
        return False
    if valid_from is not None and report_period_end < valid_from:
        return False
    return not (valid_to is not None and report_period_end > valid_to)


def intervals_overlap(
    left_from: date | None,
    left_to: date | None,
    right_from: date | None,
    right_to: date | None,
) -> bool:
    """Return whether two inclusive intervals overlap; NULL endpoints are unbounded."""
    left_start = left_from if left_from is not None else date.min
    left_end = left_to if left_to is not None else date.max
    right_start = right_from if right_from is not None else date.min
    right_end = right_to if right_to is not None else date.max
    return left_start <= right_end and right_start <= left_end


def scopes_overlap(
    *,
    left_scope: str,
    left_issuer_cik: str | None,
    left_from: date | None,
    left_to: date | None,
    right_scope: str,
    right_issuer_cik: str | None,
    right_from: date | None,
    right_to: date | None,
) -> bool:
    """Return whether two mapping scopes apply to an overlapping issuer/time set."""
    if left_scope == "issuer" and right_scope == "issuer" and left_issuer_cik != right_issuer_cik:
        return False
    return intervals_overlap(left_from, left_to, right_from, right_to)
