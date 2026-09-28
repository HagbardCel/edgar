from edgar.financials.exceptions import RequiredPeriodError
from edgar.financials.models import FactRow, UnitMeasureRow
from edgar.financials.period import (
    DeiPeriodCandidate,
    ReportingPeriod,
    period_matches_metric,
    resolve_required_reporting_period,
)

DEI_NS = "http://xbrl.sec.gov/dei/2023"


def _candidate(**kwargs: object) -> DeiPeriodCandidate:
    defaults = {
        "context_id": 10,
        "context_entity_scheme": "http://www.sec.gov/CIK",
        "context_entity_identifier": "0001065088",
        "period_kind": "duration",
        "instant_lexical": None,
        "start_lexical": "2023-01-01",
        "end_lexical": "2023-12-31",
        "document_period_end_value": "2023-12-31",
    }
    defaults.update(kwargs)
    return DeiPeriodCandidate(**defaults)  # type: ignore[arg-type]


def test_single_dei_candidate() -> None:
    period = resolve_required_reporting_period((_candidate(),), "0001065088")
    assert period == ReportingPeriod(start="2023-01-01", end="2023-12-31")


def test_zero_candidates_raises() -> None:
    try:
        resolve_required_reporting_period((), "0001065088")
    except RequiredPeriodError:
        return
    raise AssertionError("expected RequiredPeriodError")


def test_conflicting_period_end_values_raises() -> None:
    a = _candidate(document_period_end_value="2023-12-31")
    b = _candidate(document_period_end_value="2022-12-31")
    try:
        resolve_required_reporting_period((a, b), "0001065088")
    except RequiredPeriodError:
        return
    raise AssertionError("expected RequiredPeriodError")


def test_period_matches_duration_and_instant_same_window() -> None:
    period = ReportingPeriod(start="2023-01-01", end="2023-12-31")
    assert period_matches_metric(
        "duration",
        period,
        "duration",
        None,
        "2023-01-01",
        "2023-12-31",
    )
    assert period_matches_metric(
        "instant",
        period,
        "instant",
        "2023-12-31",
        None,
        None,
    )
    assert not period_matches_metric(
        "instant",
        period,
        "instant",
        "2023-01-01",
        None,
        None,
    )


def test_fiscal_focus_from_dei_facts() -> None:
    usd = UnitMeasureRow("numerator", 1, "http://www.xbrl.org/2003/iso4217", "USD")
    facts = (
        FactRow(
            fact_id=1,
            concept_namespace=DEI_NS,
            concept_local_name="DocumentFiscalYearFocus",
            source_qname=f"{{{DEI_NS}}}DocumentFiscalYearFocus",
            context_id=10,
            value_status="valid",
            resolved_numeric=None,
            is_nil=False,
            decimals=None,
            lexical_value="2023",
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0001065088",
            period_kind="duration",
            instant_lexical=None,
            start_lexical="2023-01-01",
            end_lexical="2023-12-31",
            has_dimensions=False,
            unit_measures=(usd,),
        ),
        FactRow(
            fact_id=2,
            concept_namespace=DEI_NS,
            concept_local_name="DocumentFiscalPeriodFocus",
            source_qname=f"{{{DEI_NS}}}DocumentFiscalPeriodFocus",
            context_id=10,
            value_status="valid",
            resolved_numeric=None,
            is_nil=False,
            decimals=None,
            lexical_value="FY",
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0001065088",
            period_kind="duration",
            instant_lexical=None,
            start_lexical="2023-01-01",
            end_lexical="2023-12-31",
            has_dimensions=False,
            unit_measures=(usd,),
        ),
    )
    period = resolve_required_reporting_period((_candidate(),), "0001065088", facts)
    assert period.fiscal_year_focus == "2023"
    assert period.fiscal_period_focus == "FY"
