"""Quality-report grain, denominators, and QName census."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from edgar.domain.concept_id import clark_qname
from edgar.financials.census import name_reuse_aggregate, qname_census
from edgar.financials.decisions import DecisionRegistry, LoadedDecision, load_decisions
from edgar.financials.models import FactRow, Observation, UnitMeasureRow
from edgar.financials.oracle import oracle_comparison_for_observation
from edgar.financials.quality import (
    FilingFrame,
    QualityReportError,
    build_quality_document,
    filing_frame_for_source,
    oracle_slot_reports,
    render_quality_markdown,
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
        declared_concepts=frozenset({(_NS_2023, _REVENUE)}),
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
    assert cell["n_ineligible_wrong_form"] == 1
    assert cell["n_unsupported"] == 0
    assert cell["n_value"] + cell["n_missing"] + cell["n_conflict"] + cell["n_unsupported"] == 0
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
        declared_concepts=frozenset({(_NS_2024, _REVENUE)}),
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
    assert cell["n_ineligible_wrong_form"] == 0
    assert cell["n_decision_applicable"] == 0
    assert cell["n_unsupported"] == 1
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
        declared_concepts=frozenset(),
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


def test_identity_findings_are_counted_once_per_accession_in_the_cell() -> None:
    registry = load_decisions(_REGISTRY)
    first = "0001065088-24-000036"
    second = "0000104169-24-000056"
    frame_a = FilingFrame(
        accession=first,
        cik="0001065088",
        form="10-K",
        fiscal_year="2023",
        industry_bucket="technology",
        filing_taxonomy_release="2023",
        declared_concepts=frozenset({(_NS_2023, _REVENUE)}),
    )
    frame_b = FilingFrame(
        accession=second,
        cik="0000104169",
        form="10-K",
        fiscal_year="2023",
        industry_bucket="technology",
        filing_taxonomy_release="2023",
        declared_concepts=frozenset({(_NS_2023, _REVENUE)}),
    )
    document = build_quality_document(
        (
            _obs(first, "revenue", "missing"),
            _obs(first, "total_assets", "missing"),
            _obs(second, "revenue", "missing", cik="0000104169"),
        ),
        {first: frame_a, second: frame_b},
        registry,
        {},
        identity_findings=(
            {"accession": first, "name": "nci_split", "status": "pass", "detail": ""},
            {
                "accession": first,
                "name": "balance_sheet",
                "status": "fail",
                "detail": "intervals disjoint",
            },
            {
                "accession": second,
                "name": "nci_split",
                "status": "not_applicable",
                "detail": "",
            },
            {
                "accession": second,
                "name": "balance_sheet",
                "status": "not_applicable",
                "detail": "",
            },
        ),
    )
    by_metric = {cell["metric"]: cell for cell in document["cells"]}
    revenue = by_metric["revenue"]
    assets = by_metric["total_assets"]
    assert revenue["identity_pass"] == 1
    assert revenue["identity_fail"] == 1
    assert revenue["identity_na"] == 2
    assert assets["identity_pass"] == 1
    assert assets["identity_fail"] == 1
    assert assets["identity_na"] == 0
    rendered = render_quality_markdown(document)
    assert "identity_pass" in rendered
    assert "n_ineligible_wrong_form" in rendered


def test_excluded_qname_is_not_decision_applicable() -> None:
    registry = load_decisions(_REGISTRY)
    qname = clark_qname(_NS_2024, _REVENUE)
    replaced: list[LoadedDecision] = []
    for loaded in registry.decisions:
        record = loaded.record
        if (
            record.metric == "revenue"
            and record.relation == "exact"
            and record.source.family == "us-gaap"
            and record.status == "accepted"
        ):
            source = record.source.model_copy(update={"exclude_qnames": (qname,)})
            record = record.model_copy(update={"source": source})
            loaded = LoadedDecision(record=record, path=loaded.path)
        replaced.append(loaded)
    excluded = DecisionRegistry(decisions=tuple(replaced), metrics_by_key=registry.metrics_by_key)
    frame = FilingFrame(
        accession="0001065088-24-000036",
        cik="0001065088",
        form="10-K",
        fiscal_year="2023",
        industry_bucket="technology",
        filing_taxonomy_release="2024",
        declared_concepts=frozenset({(_NS_2024, _REVENUE)}),
    )
    document = build_quality_document(
        (_obs("0001065088-24-000036", "revenue", "missing", fy="2023"),),
        {frame.accession: frame},
        excluded,
        {},
    )
    assert document["cells"][0]["n_decision_applicable"] == 0
    assert document["cells"][0]["n_slot_eligible"] == 1


def test_oracle_findings_keep_differ_and_ambiguous_values() -> None:
    namespace = "http://fasb.org/us-gaap/2024"
    usd = UnitMeasureRow("numerator", 1, "http://www.xbrl.org/2003/iso4217", "USD")
    differ_fact = FactRow(
        fact_id=7,
        concept_namespace=namespace,
        concept_local_name="Assets",
        source_qname=f"{{{namespace}}}Assets",
        context_id=1,
        value_status="valid",
        resolved_numeric=Decimal("10"),
        is_nil=False,
        decimals="-3",
        lexical_value=None,
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier="0001065088",
        period_kind="instant",
        instant_lexical="2022-12-31",
        start_lexical=None,
        end_lexical=None,
        has_dimensions=False,
        unit_measures=(usd,),
    )
    ambiguous_fact = FactRow(
        fact_id=8,
        concept_namespace=namespace,
        concept_local_name="CashAndCashEquivalentsAtCarryingValue",
        source_qname=f"{{{namespace}}}CashAndCashEquivalentsAtCarryingValue",
        context_id=2,
        value_status="valid",
        resolved_numeric=Decimal("9867000000"),
        is_nil=False,
        decimals="-6",
        lexical_value=None,
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier="0000104169",
        period_kind="instant",
        instant_lexical="2024-01-31",
        start_lexical=None,
        end_lexical=None,
        has_dimensions=False,
        unit_measures=(usd,),
    )
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    two = (fixtures / "companyfacts_two_periods.json").read_bytes()
    ambiguous = (fixtures / "companyfacts_ambiguous.json").read_bytes()
    differ = _obs(
        "0001065088-23-000006",
        "total_assets",
        "value",
        numeric="10",
        fy="2022",
    )
    differ.period_start = None
    differ.period_end = "2022-12-31"
    differ.fact_ids = (7,)
    cash = _obs(
        "0000104169-24-000056",
        "cash",
        "value",
        cik="0000104169",
        numeric="9867000000",
        fy="2024",
    )
    cash.period_start = None
    cash.period_end = "2024-01-31"
    cash.fact_ids = (8,)
    labels, findings = oracle_slot_reports(
        (differ, cash),
        {
            differ.accession: {7: differ_fact},
            cash.accession: {8: ambiguous_fact},
        },
        {differ.cik: two, cash.cik: ambiguous},
    )
    assert labels[(differ.accession, "total_assets")] == "differ"
    assert labels[(cash.accession, "cash")] == "ambiguous"
    assert [item["status"] for item in findings] == ["ambiguous", "differ"]
    differ_row = findings[1]
    assert differ_row["oracle_values"] == ["20850000000"]
    assert differ_row["observation"] == "10"
    assert differ_row["family"] == "us-gaap"
    assert differ_row["local_name"] == "Assets"
    assert findings[0]["oracle_values"] == ["9867000000", "9900000000"]
    comparison = oracle_comparison_for_observation(differ, {7: differ_fact}, two)
    assert comparison.status == "differ"
