"""Quality-report grain, denominators, and QName census."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from edgar.financials.census import name_reuse_aggregate, qname_census
from edgar.financials.decisions import load_decisions
from edgar.financials.models import Observation
from edgar.financials.quality import (
    FilingFrame,
    QualityReportError,
    build_quality_document,
    filing_frame_for_source,
)
from edgar.financials.taxonomy_release import filing_taxonomy_release

_REGISTRY = Path(__file__).resolve().parents[2] / "registry"
_NS_2023 = "http://fasb.org/us-gaap/2023"
_NS_2024 = "http://fasb.org/us-gaap/2024"
_REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"


def _obs(
    accession: str,
    metric: str,
    status: str,
    *,
    cik: str = "0001065088",
    reason: str | None = None,
    numeric: str | None = None,
    fy: str | None = "2023",
) -> Observation:
    return Observation(
        cik=cik,
        accession=accession,
        metric=metric,
        fy=fy,
        report_focus="FY",
        period_role=None,
        period_start="2023-01-01",
        period_end="2023-12-31",
        status=status,  # type: ignore[arg-type]
        reason=reason,
        numeric=Decimal(numeric) if numeric is not None else None,
        decimals="-6" if numeric is not None else None,
        unit="USD",
        decision_ids=(),
        fact_ids=(),
        supports=(),
        relation="exact" if status == "value" else None,
        tier=1 if status == "value" else None,
        available_at=None,
    )


def test_taxonomy_release_ignores_selection_outcome() -> None:
    assert filing_taxonomy_release(()) == "unknown"
    assert filing_taxonomy_release((_NS_2023,)) == "2023"
    assert filing_taxonomy_release((_NS_2023, _NS_2024)) == "mixed"
    assert filing_taxonomy_release(("http://example.com/issuer/2024",)) == "unknown"


def test_missing_slot_keeps_the_filing_release() -> None:
    registry = load_decisions(_REGISTRY)
    frame = FilingFrame(
        accession="0001065088-24-000036",
        cik="0001065088",
        form="10-K",
        fiscal_year="2023",
        industry_bucket="technology",
        filing_taxonomy_release="2023",
        us_gaap_concepts=frozenset({(_REVENUE, "2023")}),
    )
    document = build_quality_document(
        (_obs("0001065088-24-000036", "revenue", "missing"),),
        {"0001065088-24-000036": frame},
        registry,
        {},
    )
    cell = document["cells"][0]
    assert cell["filing_taxonomy_release"] == "2023"
    assert cell["n_slots"] == 1
    assert cell["n_missing"] == 1
    assert cell["n_slot_eligible"] == 1
    assert cell["n_decision_applicable"] == 1
    assert cell["publication_rate"] == "0"
    assert cell["selector_yield"] == "0"
    assert cell["oracle_na"] == 1


def test_wrong_form_is_outside_the_eligible_denominator() -> None:
    registry = load_decisions(_REGISTRY)
    frame = filing_frame_for_source(
        "0000019617-24-000453",
        "0000019617",
        "10-Q",
        observation_years=(None,),
        report_period_year="2024",
        industry_bucket="banking",
        declared_concepts=((_NS_2024, _REVENUE),),
    )
    document = build_quality_document(
        (
            _obs(
                "0000019617-24-000453",
                "revenue",
                "unsupported",
                cik="0000019617",
                reason="wrong_form",
                fy=None,
            ),
        ),
        {frame.accession: frame},
        registry,
        {},
    )
    cell = document["cells"][0]
    assert cell["n_slots"] == 1
    assert cell["n_slot_eligible"] == 0
    assert cell["n_unsupported"] == 1
    assert cell["n_reason_wrong_form"] == 1
    assert cell["n_decision_applicable"] == 0
    assert cell["publication_rate"] is None
    assert cell["fiscal_year"] == "2024"
    assert cell["filing_taxonomy_release"] == "2024"


def test_scope_exclusion_stays_eligible_and_inapplicable() -> None:
    registry = load_decisions(_REGISTRY)
    frame = FilingFrame(
        accession="0000019617-24-000099",
        cik="0000019617",
        form="10-K",
        fiscal_year="2024",
        industry_bucket="banking",
        filing_taxonomy_release="2024",
        us_gaap_concepts=frozenset({(_REVENUE, "2024")}),
    )
    document = build_quality_document(
        (
            _obs(
                frame.accession,
                "revenue",
                "unsupported",
                cik="0000019617",
                reason="decision_scope",
                fy="2024",
            ),
        ),
        {frame.accession: frame},
        registry,
        {},
    )
    cell = document["cells"][0]
    assert cell["n_slot_eligible"] == 1
    assert cell["n_decision_applicable"] == 0
    assert cell["n_reason_decision_scope"] == 1
    assert cell["n_value"] == 0


def test_value_without_a_declared_concept_fails() -> None:
    registry = load_decisions(_REGISTRY)
    frame = FilingFrame(
        accession="0001065088-24-000036",
        cik="0001065088",
        form="10-K",
        fiscal_year="2023",
        industry_bucket="technology",
        filing_taxonomy_release="unknown",
        us_gaap_concepts=frozenset(),
    )
    with pytest.raises(QualityReportError):
        build_quality_document(
            (_obs("0001065088-24-000036", "revenue", "value", numeric="1"),),
            {frame.accession: frame},
            registry,
            {("0001065088-24-000036", "revenue"): "agree"},
        )


def test_qname_census_does_not_collapse_local_names() -> None:
    facts = (
        ("0000000001-00-000001", _NS_2023, "Assets"),
        ("0000000001-00-000002", _NS_2024, "Assets"),
        ("0000000001-00-000001", _NS_2023, "Assets"),
    )
    census = qname_census(facts)
    assert census == (
        {"qname": f"{{{_NS_2023}}}Assets", "n_accessions": 1},
        {"qname": f"{{{_NS_2024}}}Assets", "n_accessions": 1},
    )
    reuse = name_reuse_aggregate(facts)
    assert all(row["aggregate"] == "name_reuse_aggregate" for row in reuse)
    assert {row["namespace_release"] for row in reuse} == {"2023", "2024"}
    assert {row["local_name"] for row in reuse} == {"Assets"}
