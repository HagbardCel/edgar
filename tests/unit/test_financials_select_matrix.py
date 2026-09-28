"""Additional P1 selector contract cases (fabricated rows)."""

from decimal import Decimal
from pathlib import Path

from edgar.financials.decisions import load_decisions
from edgar.financials.models import FactRow, Support, UnitMeasureRow
from edgar.financials.period import ReportingPeriod
from edgar.financials.resolve import resolve_supports
from edgar.financials.select import select_metric

_REGISTRY = Path(__file__).resolve().parents[2] / "registry"
USD = UnitMeasureRow("numerator", 1, "http://www.xbrl.org/2003/iso4217", "USD")
SHARES = UnitMeasureRow("denominator", 1, "http://www.xbrl.org/2003/iso4217", "shares")
NS = "http://fasb.org/us-gaap/2024"


def _base_fact(**overrides: object) -> FactRow:
    defaults: dict[str, object] = {
        "fact_id": 1,
        "concept_namespace": NS,
        "concept_local_name": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "source_qname": f"{{{NS}}}RevenueFromContractWithCustomerExcludingAssessedTax",
        "context_id": 1,
        "value_status": "valid",
        "resolved_numeric": Decimal("100"),
        "is_nil": False,
        "decimals": "0",
        "lexical_value": None,
        "entity_scheme": "http://www.sec.gov/CIK",
        "entity_identifier": "0001065088",
        "period_kind": "duration",
        "instant_lexical": None,
        "start_lexical": "2023-01-01",
        "end_lexical": "2023-12-31",
        "has_dimensions": False,
        "unit_measures": (USD,),
    }
    defaults.update(overrides)
    return FactRow(**defaults)  # type: ignore[arg-type]


def test_dimensioned_fact_rejected() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    facts = (_base_fact(has_dimensions=True),)
    supports = resolve_supports(facts, registry, "acc", "0001065088")
    obs = select_metric(
        "revenue",
        "10-K",
        "0001065088",
        "acc",
        period,
        facts,
        supports,
        registry,
        None,
        metric_period_type="duration",
    )
    assert obs.status == "missing"


def test_usd_per_share_rejected() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    facts = (_base_fact(unit_measures=(USD, SHARES)),)
    supports = resolve_supports(facts, registry, "acc", "0001065088")
    obs = select_metric(
        "revenue",
        "10-K",
        "0001065088",
        "acc",
        period,
        facts,
        supports,
        registry,
        None,
        metric_period_type="duration",
    )
    assert obs.status == "missing"


def test_wrong_entity_scheme_rejected() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    facts = (_base_fact(entity_scheme="http://example.com/id"),)
    supports = resolve_supports(facts, registry, "acc", "0001065088")
    obs = select_metric(
        "revenue",
        "10-K",
        "0001065088",
        "acc",
        period,
        facts,
        supports,
        registry,
        None,
        metric_period_type="duration",
    )
    assert obs.status == "missing"


def test_same_concept_inconsistent_conflict() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    facts = (
        _base_fact(fact_id=1, resolved_numeric=Decimal("100"), decimals="-2"),
        _base_fact(
            fact_id=2,
            resolved_numeric=Decimal("200"),
            decimals="-2",
            context_id=2,
        ),
    )
    supports = resolve_supports(facts, registry, "acc", "0001065088")
    obs = select_metric(
        "revenue",
        "10-K",
        "0001065088",
        "acc",
        period,
        facts,
        supports,
        registry,
        None,
        metric_period_type="duration",
    )
    assert obs.status == "conflict"


def test_oim_2500_3000_same_concept_value() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    facts = (
        _base_fact(fact_id=1, resolved_numeric=Decimal("2500"), decimals="-2"),
        _base_fact(
            fact_id=2,
            resolved_numeric=Decimal("3000"),
            decimals="-3",
            context_id=2,
        ),
    )
    supports = resolve_supports(facts, registry, "acc", "0001065088")
    obs = select_metric(
        "revenue",
        "10-K",
        "0001065088",
        "acc",
        period,
        facts,
        supports,
        registry,
        None,
        metric_period_type="duration",
    )
    assert obs.status == "value"
    assert obs.numeric == Decimal("2500")


def test_cross_exact_concepts_conflict() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    q1 = f"{{{NS}}}RevenueFromContractWithCustomerExcludingAssessedTax"
    q2 = f"{{{NS}}}Revenues"
    facts = (
        _base_fact(fact_id=1, resolved_numeric=Decimal("100")),
        _base_fact(
            fact_id=2,
            concept_local_name="Revenues",
            source_qname=q2,
            resolved_numeric=Decimal("200"),
            context_id=2,
        ),
    )
    supports = (
        Support(
            fact_id=1,
            accession="acc",
            concept_namespace=NS,
            concept_local_name="RevenueFromContractWithCustomerExcludingAssessedTax",
            source_qname=q1,
            metric="revenue",
            relation="exact",
            decision_id="d1",
            application_method="curated",
            tier=1,
        ),
        Support(
            fact_id=2,
            accession="acc",
            concept_namespace=NS,
            concept_local_name="Revenues",
            source_qname=q2,
            metric="revenue",
            relation="exact",
            decision_id="d2",
            application_method="curated",
            tier=1,
        ),
    )
    obs = select_metric(
        "revenue",
        "10-K",
        "0001065088",
        "acc",
        period,
        facts,
        supports,
        registry,
        None,
        metric_period_type="duration",
    )
    assert obs.status == "conflict"


def test_decision_scope_when_all_exact_exclude_issuer() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    facts = (_base_fact(entity_identifier="0000019617"),)
    supports = resolve_supports(facts, registry, "acc", "0000019617")
    obs = select_metric(
        "revenue",
        "10-K",
        "0000019617",
        "acc",
        period,
        facts,
        supports,
        registry,
        None,
        metric_period_type="duration",
    )
    assert obs.status == "unsupported"
    assert obs.reason == "decision_scope"


def test_one_applicable_exact_missing_not_decision_scope() -> None:
    """One exact applies; another exact excludes this issuer → missing, not unsupported."""
    from edgar.financials.decisions import (
        DecisionRegistry,
        DecisionScope,
        LoadedDecision,
        load_decisions,
    )
    from edgar.registry.loader import load_canonical_registry

    base = load_decisions(_REGISTRY)
    metrics = {m.key: m for m in load_canonical_registry(_REGISTRY).metrics}
    applies = base.by_id()[
        "revenue.us-gaap.RevenueFromContractWithCustomerExcludingAssessedTax"
    ].record
    excluded_parallel = applies.model_copy(
        update={
            "id": "revenue.us-gaap.SalesRevenueNet.fixture",
            "source": applies.source.model_copy(update={"local_name": "SalesRevenueNet"}),
            "scope": DecisionScope(exclude_ciks=("0001065088",)),
        }
    )
    registry = DecisionRegistry(
        decisions=base.decisions
        + (LoadedDecision(excluded_parallel, _REGISTRY / "decisions" / "fixture.yml"),),
        metrics_by_key=metrics,
    )
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    obs = select_metric(
        "revenue",
        "10-K",
        "0001065088",
        "acc",
        period,
        (),
        (),
        registry,
        None,
        metric_period_type="duration",
    )
    assert obs.status == "missing"
    assert obs.reason != "decision_scope"


def test_amendment_missing_without_facts() -> None:
    registry = load_decisions(_REGISTRY)
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    obs = select_metric(
        "revenue",
        "10-K/A",
        "0001065088",
        "0001065088-24-000094",
        period,
        (),
        (),
        registry,
        None,
        metric_period_type="duration",
    )
    assert obs.status == "missing"
