from decimal import Decimal

from edgar.financials.decimals import ClosedInterval
from edgar.financials.models import FactRow, UnitMeasureRow
from edgar.financials.period import ReportingPeriod
from edgar.financials.validate import run_identity_checks

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
    period = ReportingPeriod(kind="duration", start="2023-01-01", end="2023-12-31")
    facts = (
        _duration_fact("ProfitLoss", Decimal("100"), "0"),
        _duration_fact("NetIncomeLoss", Decimal("80"), "0"),
        _duration_fact("NetIncomeLossAttributableToNoncontrollingInterest", Decimal("20"), "0"),
    )
    findings = run_identity_checks("acc", "0001065088", period, facts)
    nci = next(f for f in findings if f.name == "nci_split")
    assert nci.status == "pass"


def test_nci_split_not_applicable_when_missing() -> None:
    period = ReportingPeriod(kind="duration", start="2023-01-01", end="2023-12-31")
    findings = run_identity_checks("acc", "0001065088", period, ())
    assert all(f.status == "not_applicable" for f in findings)


def test_interval_intersection_semantics() -> None:
    a = ClosedInterval(Decimal("2450"), Decimal("2500"))
    b = ClosedInterval(Decimal("2500"), Decimal("3500"))
    assert a.intersects(b)
    summed = a + ClosedInterval(Decimal("0"), Decimal("0"))
    assert summed.lo == Decimal("2450")
