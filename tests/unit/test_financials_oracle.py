"""Companyfacts oracle: Decimal fidelity, family identity, and ambiguity."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from edgar.financials.models import FactRow, Observation, UnitMeasureRow
from edgar.financials.oracle import (
    OracleAmbiguous,
    OracleHit,
    OracleInputError,
    oracle_label_for_observation,
    oracle_value,
    source_fact_oracle_eligible,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_TWO = (_FIXTURES / "companyfacts_two_periods.json").read_text(encoding="utf-8")
_AMBIGUOUS = (_FIXTURES / "companyfacts_ambiguous.json").read_text(encoding="utf-8")
USD = UnitMeasureRow("numerator", 1, "http://www.xbrl.org/2003/iso4217", "USD")


def test_two_periods_select_the_matching_accession() -> None:
    hit = oracle_value(
        _TWO,
        cik="0001065088",
        taxonomy_family="us-gaap",
        local_name="Assets",
        accession="0001065088-23-000006",
        period_end="2022-12-31",
        unit="USD",
    )
    assert isinstance(hit, OracleHit)
    assert hit.value == Decimal("20850000000")
    other = oracle_value(
        _TWO,
        cik="0001065088",
        taxonomy_family="us-gaap",
        local_name="Assets",
        accession="0001065088-24-000036",
        period_end="2023-12-31",
        unit="USD",
    )
    assert isinstance(other, OracleHit)
    assert other.value == Decimal("21620000000")


def test_decimal_token_is_not_a_binary_float() -> None:
    hit = oracle_value(
        _TWO,
        cik="1065088",
        taxonomy_family="us-gaap",
        local_name="RevenueFromContractWithCustomerExcludingAssessedTax",
        accession="0001065088-23-000006",
        period_end="2022-12-31",
        period_start="2022-01-01",
        unit="USD",
    )
    assert isinstance(hit, OracleHit)
    assert hit.value == Decimal("9795000000.10")


def test_identical_duplicates_are_one_hit_and_distinct_values_are_ambiguous() -> None:
    cash = oracle_value(
        _AMBIGUOUS,
        cik="0000104169",
        taxonomy_family="us-gaap",
        local_name="CashAndCashEquivalentsAtCarryingValue",
        accession="0000104169-24-000056",
        period_end="2024-01-31",
        unit="USD",
    )
    assert isinstance(cash, OracleAmbiguous)
    assert cash.values == (Decimal("9867000000"), Decimal("9900000000"))
    assets = oracle_value(
        _AMBIGUOUS,
        cik="0000104169",
        taxonomy_family="us-gaap",
        local_name="Assets",
        accession="0000104169-24-000056",
        period_end="2024-01-31",
        unit="USD",
    )
    assert isinstance(assets, OracleHit)
    assert assets.value == Decimal("252399000000")


def test_local_name_without_family_is_rejected() -> None:
    with pytest.raises(OracleInputError):
        oracle_value(
            _TWO,
            cik="0001065088",
            taxonomy_family="",
            local_name="Assets",
            accession="0001065088-23-000006",
            period_end="2022-12-31",
            unit="USD",
        )


def test_binary_float_in_a_mapping_is_rejected() -> None:
    payload = {
        "cik": 1065088,
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "accn": "0001065088-23-000006",
                                "end": "2022-12-31",
                                "val": 1.25,
                            }
                        ]
                    }
                }
            }
        },
    }
    with pytest.raises(OracleInputError):
        oracle_value(
            payload,
            cik="0001065088",
            taxonomy_family="us-gaap",
            local_name="Assets",
            accession="0001065088-23-000006",
            period_end="2022-12-31",
            unit="USD",
        )


def _fact(*, dimensional: bool = False, namespace: str = "http://fasb.org/us-gaap/2024") -> FactRow:
    return FactRow(
        fact_id=1,
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
        instant_lexical="2023-12-31",
        start_lexical=None,
        end_lexical=None,
        has_dimensions=dimensional,
        unit_measures=(USD,),
    )


def test_dimensional_and_issuer_facts_are_not_oracle_eligible() -> None:
    assert source_fact_oracle_eligible(_fact()) is True
    assert source_fact_oracle_eligible(_fact(dimensional=True)) is False
    assert source_fact_oracle_eligible(_fact(namespace="http://example.com/issuer/2024")) is False


def test_missing_observation_is_oracle_na_without_calling_a_value() -> None:
    observation = Observation(
        cik="0001065088",
        accession="0001065088-23-000006",
        metric="total_assets",
        fy="2022",
        report_focus="FY",
        period_role=None,
        period_start=None,
        period_end="2022-12-31",
        status="missing",
        reason=None,
        numeric=None,
        decimals=None,
        unit="USD",
        decision_ids=(),
        fact_ids=(),
        supports=(),
        relation=None,
        tier=None,
        available_at=None,
    )
    assert oracle_label_for_observation(observation, {1: _fact()}, _TWO) == "na"
