"""XBRL OIM duplicate-fact interval consistency."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

FactId = int


@dataclass(frozen=True)
class ClosedInterval:
    lo: Decimal
    hi: Decimal

    def intersects(self, other: ClosedInterval) -> bool:
        return self.lo <= other.hi and other.lo <= self.hi

    def __add__(self, other: ClosedInterval) -> ClosedInterval:
        return ClosedInterval(self.lo + other.lo, self.hi + other.hi)


@dataclass(frozen=True)
class OimResolution:
    survivor_value: Decimal
    survivor_decimals: str | None
    survivor_fact_id: FactId
    fact_ids: tuple[FactId, ...]
    consistent_interval: ClosedInterval


def _parse_decimals(decimals: str | None) -> int | Literal["INF"] | None:
    if decimals is None:
        return None
    if decimals.upper() == "INF":
        return "INF"
    return int(decimals)


def survivor_rank(decimals: str | None, fact_id: FactId) -> tuple[int, int, int]:
    """Order key for the published fact. Smaller is better.

    ``INF`` outranks every finite ``decimals``. A larger finite integer is more
    precise. Equal precision keeps the minimum ``fact_id``, so row order cannot
    choose the representative.
    """
    parsed = _parse_decimals(decimals)
    if parsed == "INF":
        return (0, 0, fact_id)
    if parsed is None:
        return (2, 0, fact_id)
    return (1, -parsed, fact_id)


def fact_interval(value: Decimal, decimals: str | None) -> ClosedInterval:
    parsed = _parse_decimals(decimals)
    if parsed == "INF":
        return ClosedInterval(value, value)
    if parsed is None:
        return ClosedInterval(value, value)
    half = Decimal("0.5") * (Decimal(10) ** (-parsed))
    return ClosedInterval(value - half, value + half)


@dataclass(frozen=True)
class NumericFactOccurrence:
    fact_id: FactId
    value: Decimal
    decimals: str | None


def oim_reduce_group(facts: tuple[NumericFactOccurrence, ...]) -> OimResolution | None:
    if not facts:
        return None
    intervals = [(f, fact_interval(f.value, f.decimals)) for f in facts]
    intersection = intervals[0][1]
    for _, interval in intervals[1:]:
        if not intersection.intersects(interval):
            return None
        intersection = ClosedInterval(
            max(intersection.lo, interval.lo),
            min(intersection.hi, interval.hi),
        )
    for f in facts:
        for other in facts:
            if f is other:
                continue
            same_dec = _parse_decimals(f.decimals) == _parse_decimals(other.decimals)
            if same_dec and f.value != other.value:
                return None

    survivor = min(facts, key=lambda f: survivor_rank(f.decimals, f.fact_id))
    return OimResolution(
        survivor_value=survivor.value,
        survivor_decimals=survivor.decimals,
        survivor_fact_id=survivor.fact_id,
        fact_ids=tuple(sorted(f.fact_id for f in facts)),
        consistent_interval=intersection,
    )
