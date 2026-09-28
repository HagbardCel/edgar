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


def test_inf_equal_values_reduce() -> None:
    group = (
        NumericFactOccurrence(1, Decimal("100"), "INF"),
        NumericFactOccurrence(2, Decimal("100"), "INF"),
    )
    res = oim_reduce_group(group)
    assert res is not None
    assert res.survivor_value == Decimal("100")


def test_inf_unequal_conflict() -> None:
    group = (
        NumericFactOccurrence(1, Decimal("100"), "INF"),
        NumericFactOccurrence(2, Decimal("200"), "INF"),
    )
    assert oim_reduce_group(group) is None


def test_same_decimals_lexical_zero_equivalent() -> None:
    group = (
        NumericFactOccurrence(1, Decimal("100"), "0"),
        NumericFactOccurrence(2, Decimal("200"), "+0"),
    )
    assert oim_reduce_group(group) is None


def test_equal_precision_tie_uses_minimum_fact_id() -> None:
    forward = (
        NumericFactOccurrence(5, Decimal("100"), "-3"),
        NumericFactOccurrence(2, Decimal("100"), "-3"),
    )
    reverse = (forward[1], forward[0])
    left = oim_reduce_group(forward)
    right = oim_reduce_group(reverse)
    assert left is not None and right is not None
    assert left.survivor_fact_id == 2
    assert right.survivor_fact_id == 2
    assert left.survivor_value == right.survivor_value == Decimal("100")
    assert left.fact_ids == right.fact_ids == (2, 5)


def test_chain_overlap_without_common_intersection_conflicts() -> None:
    # A overlaps B and B overlaps C, but A does not overlap C.
    group = (
        NumericFactOccurrence(1, Decimal("100"), "0"),
        NumericFactOccurrence(2, Decimal("101"), "-1"),
        NumericFactOccurrence(3, Decimal("106"), "1"),
    )
    assert oim_reduce_group(group) is None
    assert oim_reduce_group((group[2], group[0], group[1])) is None


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
