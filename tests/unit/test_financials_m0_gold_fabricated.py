"""Fabricated rows prove m0 gold value assertions are reproducible by selection."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from edgar.financials.decisions import load_decisions
from edgar.financials.gold import compare_gold, load_gold
from edgar.financials.models import FactRow, UnitMeasureRow
from edgar.financials.period import ReportingPeriod
from edgar.financials.resolve import resolve_supports
from edgar.financials.select import select_metric
from edgar.registry.loader import load_canonical_registry

_REPO = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO / "registry"
USD = UnitMeasureRow("numerator", 1, "http://www.xbrl.org/2003/iso4217", "USD")
NS = "http://fasb.org/us-gaap/2024"

_METRIC_CONCEPT: dict[str, str] = {
    "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "total_assets": "Assets",
    "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
    "operating_income": "OperatingIncomeLoss",
    "research_and_development": "ResearchAndDevelopmentExpense",
    "net_income_attributable_to_parent": "NetIncomeLoss",
    "cash_excluding_restricted_cash": "CashAndCashEquivalentsAtCarryingValue",
    "cash_purchases_of_ppe": "PaymentsToAcquirePropertyPlantAndEquipment",
}

_CIK_BY_ACCESSION: dict[str, str] = {
    "0001065088-23-000006": "0001065088",
    "0001065088-24-000036": "0001065088",
    "0000104169-24-000056": "0000104169",
}


def _reporting_periods(gold_path: Path) -> dict[str, ReportingPeriod]:
    gold = load_gold(gold_path)
    out: dict[str, ReportingPeriod] = {}
    for assertion in gold.assertions:
        if assertion.period.kind != "duration":
            continue
        out[assertion.accession] = ReportingPeriod(
            start=assertion.period.start,
            end=assertion.period.end,
        )
    return out


def _fabricated_fact(
    assertion_id: str,
    local: str,
    value: Decimal,
    *,
    duration: bool,
    start: str | None,
    end: str,
    cik: str,
) -> FactRow:
    return FactRow(
        fact_id=hash(assertion_id) % 1_000_000,
        concept_namespace=NS,
        concept_local_name=local,
        source_qname=f"{{{NS}}}{local}",
        context_id=1,
        value_status="valid",
        resolved_numeric=value,
        is_nil=False,
        decimals="0",
        lexical_value=None,
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier=cik,
        period_kind="duration" if duration else "instant",
        instant_lexical=end if not duration else None,
        start_lexical=start if duration else None,
        end_lexical=end if duration else None,
        has_dimensions=False,
        unit_measures=(USD,),
    )


@pytest.fixture(scope="module")
def gold_value_assertions() -> tuple:
    gold = load_gold(_REGISTRY / "gold" / "m0-annual.yml")
    return tuple(a for a in gold.assertions if a.status == "value")


def test_fifteen_m0_gold_values_fabricated(gold_value_assertions: tuple) -> None:
    assert len(gold_value_assertions) == 15
    registry = load_decisions(_REGISTRY)
    metrics = {m.key: m for m in load_canonical_registry(_REGISTRY).metrics}
    periods = _reporting_periods(_REGISTRY / "gold" / "m0-annual.yml")
    for assertion in gold_value_assertions:
        cik = _CIK_BY_ACCESSION[assertion.accession]
        period = periods[assertion.accession]
        metric_def = metrics[assertion.metric]
        local = _METRIC_CONCEPT[assertion.metric]
        duration = assertion.period.kind == "duration"
        start = assertion.period.start if duration else None
        end = assertion.period.end
        value = Decimal(assertion.numeric) if assertion.numeric else Decimal(0)
        facts = (
            _fabricated_fact(
                assertion.id,
                local,
                value,
                duration=duration,
                start=start,
                end=end,
                cik=cik,
            ),
        )
        supports = resolve_supports(facts, registry, assertion.accession, cik)
        obs = select_metric(
            assertion.metric,
            "10-K",
            cik,
            assertion.accession,
            period,
            facts,
            supports,
            registry,
            None,
            metric_period_type=metric_def.period_type,
        )
        err = compare_gold(assertion, obs)
        assert err is None, f"{assertion.id}: {err}"
