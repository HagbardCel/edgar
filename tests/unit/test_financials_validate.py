from decimal import Decimal

from edgar.financials.decimals import ClosedInterval
from edgar.financials.models import FactRow, UnitMeasureRow
from edgar.financials.period import ReportingPeriod
from edgar.financials.validate import _operand_interval, run_identity_checks

USD = UnitMeasureRow("numerator", 1, "http://www.xbrl.org/2003/iso4217", "USD")
NS = "http://fasb.org/us-gaap/2024"


def _duration_fact(local: str, value: Decimal, decimals: str) -> FactRow:
    return FactRow(
        fact_id=hash(local) % 10000,
        concept_namespace=NS,
        concept_local_name=local,
        source_qname=f"{{{NS}}}{local}",
        context_id=1,
        value_status="valid",
        resolved_numeric=value,
        is_nil=False,
        decimals=decimals,
        lexical_value=None,
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier="0001065088",
        period_kind="duration",
        instant_lexical=None,
        start_lexical="2023-01-01",
        end_lexical="2023-12-31",
        has_dimensions=False,
        unit_measures=(USD,),
    )


def test_nci_split_pass() -> None:
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    facts = (
        _duration_fact("ProfitLoss", Decimal("100"), "0"),
        _duration_fact("NetIncomeLoss", Decimal("80"), "0"),
        _duration_fact("NetIncomeLossAttributableToNoncontrollingInterest", Decimal("20"), "0"),
    )
    findings = run_identity_checks("acc", "0001065088", period, facts)
    nci = next(f for f in findings if f.name == "nci_split")
    assert nci.status == "pass"


def test_nci_split_not_applicable_when_missing() -> None:
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    findings = run_identity_checks("acc", "0001065088", period, ())
    assert all(f.status == "not_applicable" for f in findings)


def _instant_fact(local: str, value: Decimal, decimals: str) -> FactRow:
    return FactRow(
        fact_id=hash(local) % 10000 + 1,
        concept_namespace=NS,
        concept_local_name=local,
        source_qname=f"{{{NS}}}{local}",
        context_id=2,
        value_status="valid",
        resolved_numeric=value,
        is_nil=False,
        decimals=decimals,
        lexical_value=None,
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier="0001065088",
        period_kind="instant",
        instant_lexical="2023-12-31",
        start_lexical=None,
        end_lexical=None,
        has_dimensions=False,
        unit_measures=(USD,),
    )


def test_balance_sheet_pass() -> None:
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    facts = (
        _instant_fact("Assets", Decimal("1000"), "0"),
        _instant_fact("Liabilities", Decimal("400"), "0"),
        _instant_fact("StockholdersEquity", Decimal("600"), "0"),
    )
    findings = run_identity_checks("acc", "0001065088", period, facts)
    bs = next(f for f in findings if f.name == "balance_sheet")
    assert bs.status == "pass"


def test_operand_interval_cross_qname_survivor_disagree() -> None:
    facts = (
        _duration_fact("ProfitLoss", Decimal("2500"), "-2"),
        _duration_fact("NetIncomeLoss", Decimal("3000"), "-3"),
    )
    assert _operand_interval(facts) is None


def test_nci_split_fail_disjoint_intervals() -> None:
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    facts = (
        _duration_fact("ProfitLoss", Decimal("5000"), "0"),
        _duration_fact("NetIncomeLoss", Decimal("80"), "0"),
        _duration_fact("NetIncomeLossAttributableToNoncontrollingInterest", Decimal("20"), "0"),
    )
    findings = run_identity_checks("acc", "0001065088", period, facts)
    nci = next(f for f in findings if f.name == "nci_split")
    assert nci.status == "fail"


def test_interval_intersection_semantics() -> None:
    a = ClosedInterval(Decimal("2450"), Decimal("2500"))
    b = ClosedInterval(Decimal("2500"), Decimal("3500"))
    assert a.intersects(b)
    summed = a + ClosedInterval(Decimal("0"), Decimal("0"))
    assert summed.lo == Decimal("2450")
