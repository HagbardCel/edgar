"""Report-set completeness validation (M1A-3)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence


class ReportSetError(ValueError):
    """Expected report keys do not match outcome inventory."""


def assert_unique_report_keys(report_keys: Sequence[str]) -> None:
    seen: set[str] = set()
    for key in report_keys:
        if key in seen:
            raise ReportSetError(f"duplicate expected report_key: {key!r}")
        seen.add(key)


def validate_outcome_keys[T](
    expected_keys: frozenset[str],
    outcomes: Sequence[T],
    *,
    key_of: Callable[[T], str],
    label: str,
) -> dict[str, T]:
    """Validate outcomes cover expected keys exactly once; then index by key."""
    keys_in_order: list[str] = []
    for outcome in outcomes:
        key = key_of(outcome)
        keys_in_order.append(key)

    seen: set[str] = set()
    for key in keys_in_order:
        if key in seen:
            raise ReportSetError(f"duplicate {label} outcome for report_key={key!r}")
        seen.add(key)

    outcome_keys = frozenset(keys_in_order)
    if outcome_keys != expected_keys:
        missing = sorted(expected_keys - outcome_keys)
        extra = sorted(outcome_keys - expected_keys)
        parts: list[str] = []
        if missing:
            parts.append(f"missing={missing!r}")
        if extra:
            parts.append(f"unexpected={extra!r}")
        raise ReportSetError(f"{label} outcomes mismatch expected report keys: {', '.join(parts)}")

    return {key_of(o): o for o in outcomes}


def expected_keys_from_inputs(
    report_keys: Iterable[str],
) -> frozenset[str]:
    keys = tuple(report_keys)
    assert_unique_report_keys(keys)
    return frozenset(keys)
