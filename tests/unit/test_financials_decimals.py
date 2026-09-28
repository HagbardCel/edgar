from decimal import Decimal

from edgar.financials.decimals import (
    ClosedInterval,
    NumericFactOccurrence,
    fact_interval,
    oim_reduce_group,
)


def test_walmart_cash_consistent_survivor() -> None:
    group = (
        NumericFactOccurrence(1, Decimal("9867000000"), "-6"),
        NumericFactOccurrence(2, Decimal("9900000000"), "-8"),
    )
    res = oim_reduce_group(group)
    assert res is not None
    assert res.survivor_value == Decimal("9867000000")
    assert res.fact_ids == (1, 2)


def test_oim_2500_3000_consistent() -> None:
    group = (
        NumericFactOccurrence(1, Decimal("2500"), "-2"),
        NumericFactOccurrence(2, Decimal("3000"), "-3"),
    )
    res = oim_reduce_group(group)
    assert res is not None
    assert res.survivor_value == Decimal("2500")
    assert res.consistent_interval.lo == Decimal("2500")
    assert res.consistent_interval.hi == Decimal("2550")


def test_same_decimals_unequal_conflict() -> None:
    group = (
        NumericFactOccurrence(1, Decimal("100"), "-2"),
        NumericFactOccurrence(2, Decimal("200"), "-2"),
    )
    assert oim_reduce_group(group) is None


def test_interval_identity_counterexample() -> None:
    a = fact_interval(Decimal("2500"), "-2")
    b = fact_interval(Decimal("2000"), "-3")
    intersection = ClosedInterval(
        max(a.lo, b.lo),
        min(a.hi, b.hi),
    )
    assert intersection.hi == Decimal("2500")
    rhs = Decimal("2525")
    assert not (intersection.lo <= rhs <= intersection.hi)
