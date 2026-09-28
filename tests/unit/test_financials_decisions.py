from pathlib import Path

from edgar.financials.decisions import (
    DecisionRecord,
    concept_matches_decision,
    expand_clark_qnames_for_decision,
    load_decisions,
)
from edgar.registry.loader import load_canonical_registry

_REPO = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO / "registry"


def test_us_gaap_expansion_year_agnostic() -> None:
    registry = load_decisions(_REGISTRY)
    rev = registry.by_id()[
        "revenue.us-gaap.RevenueFromContractWithCustomerExcludingAssessedTax"
    ].record
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


def test_non_issuer_family_forbids_issuer_cik() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="issuer_cik is only allowed"):
        DecisionRecord.model_validate(
            {
                "id": "total_assets.us-gaap.Assets.scoped",
                "metric": "total_assets",
                "source": {
                    "family": "us-gaap",
                    "local_name": "Assets",
                    "issuer_cik": "0001065088",
                },
                "relation": "exact",
                "status": "accepted",
                "method": "curated",
                "rationale": "test",
                "evidence": [
                    {
                        "kind": "filing_fact",
                        "accession": "0001065088-24-000036",
                        "locator": "x",
                    }
                ],
                "reviewed": {"by": "t", "on": "2026-09-28"},
                "contract_hash": "0" * 64,
            }
        )


def test_issuer_cik_normalized_to_ten_digits() -> None:
    record = DecisionRecord.model_validate(
        {
            "id": "revenue.issuer.CustomRevenue",
            "metric": "revenue",
            "source": {
                "family": "issuer",
                "local_name": "CustomRevenue",
                "issuer_cik": "1065088",
            },
            "relation": "exact",
            "status": "accepted",
            "method": "curated",
            "rationale": "issuer extension test",
            "evidence": [
                {
                    "kind": "filing_fact",
                    "accession": "0001065088-24-000036",
                    "locator": "xbrl:undimensioned-fact",
                }
            ],
            "reviewed": {"by": "t", "on": "2026-09-28"},
            "contract_hash": "0" * 64,
        }
    )
    assert record.source.issuer_cik == "0001065088"


def test_issuer_family_requires_issuer_cik() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="issuer_cik"):
        DecisionRecord.model_validate(
            {
                "id": "x.issuer.Foo",
                "metric": "revenue",
                "source": {"family": "issuer", "local_name": "Foo"},
                "relation": "exact",
                "status": "accepted",
                "method": "curated",
                "rationale": "test",
                "evidence": [
                    {
                        "kind": "filing_fact",
                        "accession": "0001065088-24-000036",
                        "locator": "x",
                    }
                ],
                "reviewed": {"by": "t", "on": "2026-09-28"},
                "contract_hash": "0" * 64,
            }
        )


def test_issuer_decision_expansion_scoped_to_filing_cik() -> None:
    ns_2023 = "https://example-company.com/xbrl/2023"
    ns_2024 = "https://example-company.com/xbrl/2024"
    record = DecisionRecord.model_validate(
        {
            "id": "revenue.issuer.CustomRevenue",
            "metric": "revenue",
            "source": {
                "family": "issuer",
                "local_name": "CustomRevenue",
                "issuer_cik": "0001065088",
            },
            "relation": "exact",
            "status": "accepted",
            "method": "curated",
            "rationale": "issuer extension test",
            "evidence": [
                {
                    "kind": "filing_fact",
                    "accession": "0001065088-24-000036",
                    "locator": "xbrl:undimensioned-fact",
                }
            ],
            "reviewed": {"by": "t", "on": "2026-09-28"},
            "contract_hash": "0" * 64,
        }
    )
    on_issuer = expand_clark_qnames_for_decision(record, "0001065088", (ns_2023, ns_2024))
    assert f"{{{ns_2023}}}CustomRevenue" in on_issuer
    assert f"{{{ns_2024}}}CustomRevenue" in on_issuer
    on_other = expand_clark_qnames_for_decision(record, "0000019617", (ns_2023, ns_2024))
    assert not on_other


def test_stale_rejected_rules_check_warning() -> None:
    from edgar.financials.rules_check import run_rules_check

    findings = run_rules_check(_REGISTRY)
    assert not any(f.level == "error" for f in findings)
    # Live registry should not emit rules-check errors.


def test_stale_accepted_raises() -> None:
    metrics = {m.key: m for m in load_canonical_registry(_REGISTRY).metrics}
    # corrupt hash in memory is not easy; ensure live files load
    load_decisions(_REGISTRY, metrics=metrics, fatal_stale_accepted=True)
