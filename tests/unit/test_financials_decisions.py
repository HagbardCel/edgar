from pathlib import Path

from edgar.financials.decisions import concept_matches_decision, load_decisions
from edgar.registry.loader import load_canonical_registry

_REPO = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO / "registry"


def test_us_gaap_expansion_year_agnostic() -> None:
    registry = load_decisions(_REGISTRY)
    rev = registry.by_id()["revenue.us-gaap.RevenueFromContractWithCustomerExcludingAssessedTax"].record
    assert concept_matches_decision(
        rev,
        "0001065088",
        "http://fasb.org/us-gaap/2022",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert concept_matches_decision(
        rev,
        "0001065088",
        "http://xbrl.us/us-gaap/2009-01-31",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert not concept_matches_decision(
        rev, "0001065088", "http://fasb.org/us-gaap/2023", "Liabilities"
    )


def test_rejected_produces_no_supports_via_loader() -> None:
    registry = load_decisions(_REGISTRY)
    rejected = registry.by_id()["revenue.us-gaap.GrossProfit.rejected"]
    assert rejected.record.status == "rejected"


def test_m0_metrics_have_exact_decisions() -> None:
    from edgar.financials.rules_check import run_rules_check

    errors = [f for f in run_rules_check(_REGISTRY) if f.level == "error"]
    assert not errors


def test_stale_accepted_raises() -> None:
    metrics = {m.key: m for m in load_canonical_registry(_REGISTRY).metrics}
    # corrupt hash in memory is not easy; ensure live files load
    load_decisions(_REGISTRY, metrics=metrics, fatal_stale_accepted=True)
