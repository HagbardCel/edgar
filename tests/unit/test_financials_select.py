from decimal import Decimal
from pathlib import Path

from edgar.financials.decisions import load_decisions
from edgar.financials.models import FactRow, UnitMeasureRow
from edgar.financials.period import ReportingPeriod
from edgar.financials.resolve import resolve_supports
from edgar.financials.select import select_metric

_REGISTRY = Path(__file__).resolve().parents[2] / "registry"
USD = UnitMeasureRow("numerator", 1, "http://www.xbrl.org/2003/iso4217", "USD")
NS = "http://fasb.org/us-gaap/2024"


def _fact(
    fact_id: int,
    local: str,
    value: Decimal,
    decimals: str,
    *,
    context_id: int = 1,
    start: str = "2023-01-01",
    end: str = "2023-12-31",
    instant: str | None = None,
    duration: bool = True,
    cik: str = "0001065088",
) -> FactRow:
    return FactRow(
        fact_id=fact_id,
        concept_namespace=NS,
        concept_local_name=local,
        source_qname=f"{{{NS}}}{local}",
        context_id=context_id,
        value_status="valid",
        resolved_numeric=value,
        is_nil=False,
        decimals=decimals,
        lexical_value=None,
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier=cik,
        period_kind="duration" if duration else "instant",
        instant_lexical=instant,
        start_lexical=start if duration else None,
        end_lexical=end if duration else None,
        has_dimensions=False,
        unit_measures=(USD,),
    )


def test_one_reporting_period_duration_and_instant() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    facts = (
        _fact(
            1,
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            Decimal("100"),
            "-3",
            start="2023-01-01",
            end="2023-12-31",
        ),
        _fact(
            2,
            "Assets",
            Decimal("500"),
            "-3",
            instant="2023-12-31",
            duration=False,
            context_id=2,
        ),
    )
    supports = resolve_supports(facts, registry, "0001065088-24-000036", "0001065088")
    rev = select_metric(
        "revenue",
        "10-K",
        "0001065088",
        "0001065088-24-000036",
        period,
        facts,
        supports,
        registry,
        None,
        metric_period_type="duration",
    )
    assets = select_metric(
        "total_assets",
        "10-K",
        "0001065088",
        "0001065088-24-000036",
        period,
        facts,
        supports,
        registry,
        None,
        metric_period_type="instant",
    )
    assert rev.status == "value"
    assert rev.numeric == Decimal("100")
    assert rev.period_start == "2023-01-01"
    assert rev.period_end == "2023-12-31"
    assert assets.status == "value"
    assert assets.numeric == Decimal("500")
    assert assets.period_start is None
    assert assets.period_end == "2023-12-31"


def test_walmart_cash_oim_survivor() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-02-01", end="2024-01-31")
    facts = (
        _fact(
            1,
            "CashAndCashEquivalentsAtCarryingValue",
            Decimal("9867000000"),
            "-6",
            instant="2024-01-31",
            duration=False,
            cik="0000104169",
        ),
        _fact(
            2,
            "CashAndCashEquivalentsAtCarryingValue",
            Decimal("9900000000"),
            "-8",
            instant="2024-01-31",
            duration=False,
            context_id=2,
            cik="0000104169",
        ),
    )
    supports = resolve_supports(facts, registry, "0000104169-24-000056", "0000104169")
    obs = select_metric(
        "cash_excluding_restricted_cash",
        "10-K",
        "0000104169",
        "0000104169-24-000056",
        period,
        facts,
        supports,
        registry,
        None,
        metric_period_type="instant",
    )
    assert obs.status == "value"
    assert obs.numeric == Decimal("9867000000")


def test_10q_wrong_form() -> None:
    registry = load_decisions(_REGISTRY)
    obs = select_metric(
        "revenue",
        "10-Q",
        "0000019617",
        "0000019617-24-000453",
        None,
        (),
        (),
        registry,
        None,
        metric_period_type="duration",
    )
    assert obs.status == "unsupported"
    assert obs.reason == "wrong_form"


def test_broader_only_missing() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-02-01", end="2024-01-31")
    facts = (
        _fact(
            1,
            "Revenues",
            Decimal("100"),
            "-3",
            start="2023-02-01",
            end="2024-01-31",
            cik="0000104169",
        ),
    )
    supports = resolve_supports(facts, registry, "0000104169-24-000056", "0000104169")
    obs = select_metric(
        "revenue",
        "10-K",
        "0000104169",
        "0000104169-24-000056",
        period,
        facts,
        supports,
        registry,
        None,
        metric_period_type="duration",
    )
    assert obs.status == "missing"
    assert obs.reason == "broader_only"


def test_equal_precision_order_does_not_change_observation() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    local = "RevenueFromContractWithCustomerExcludingAssessedTax"
    accession = "0001065088-24-000036"
    cik = "0001065088"

    def _observe(facts: tuple[FactRow, ...]) -> object:
        supports = resolve_supports(facts, registry, accession, cik)
        return select_metric(
            "revenue",
            "10-K",
            cik,
            accession,
            period,
            facts,
            supports,
            registry,
            None,
            metric_period_type="duration",
        )

    first = _fact(7, local, Decimal("100"), "-3")
    second = _fact(3, local, Decimal("100"), "-3", context_id=2)
    left = _observe((first, second))
    right = _observe((second, first))
    assert left == right
    assert left.fact_ids == (3, 7)
    assert left.numeric == Decimal("100")
    assert left.decimals == "-3"
