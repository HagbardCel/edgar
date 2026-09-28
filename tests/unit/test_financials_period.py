from edgar.financials.exceptions import RequiredPeriodError
from edgar.financials.period import DeiPeriodCandidate, ReportingPeriod, resolve_required_reporting_period


def _candidate(**kwargs: object) -> DeiPeriodCandidate:
    defaults = {
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
    assert period == ReportingPeriod(
        kind="duration", start="2023-01-01", end="2023-12-31"
    )


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
