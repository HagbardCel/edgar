"""Required reporting period from DEI DocumentPeriodEndDate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from edgar.domain.identifiers import validate_cik
from edgar.financials.exceptions import RequiredPeriodError

SEC_CIK_SCHEME = "http://www.sec.gov/CIK"
DEI_LOCAL_DOCUMENT_PERIOD_END = "DocumentPeriodEndDate"


@dataclass(frozen=True)
class ReportingPeriod:
    kind: Literal["duration", "instant"]
    start: str | None
    end: str
    fiscal_year_focus: str | None = None
    fiscal_period_focus: str | None = None


@dataclass(frozen=True)
class DeiPeriodCandidate:
    context_entity_scheme: str
    context_entity_identifier: str
    period_kind: str
    instant_lexical: str | None
    start_lexical: str | None
    end_lexical: str | None
    document_period_end_value: str


def _period_end_lexical(candidate: DeiPeriodCandidate) -> str:
    if candidate.period_kind == "instant":
        if candidate.instant_lexical is None:
            raise RequiredPeriodError("DEI context missing instant_lexical")
        return candidate.instant_lexical
    if candidate.end_lexical is None:
        raise RequiredPeriodError("DEI duration context missing end_lexical")
    return candidate.end_lexical


def _candidates_equivalent(a: DeiPeriodCandidate, b: DeiPeriodCandidate) -> bool:
    if validate_cik(a.context_entity_identifier) != validate_cik(b.context_entity_identifier):
        return False
    if a.context_entity_scheme != b.context_entity_scheme:
        return False
    if (
        a.period_kind,
        a.instant_lexical,
        a.start_lexical,
        a.end_lexical,
    ) != (
        b.period_kind,
        b.instant_lexical,
        b.start_lexical,
        b.end_lexical,
    ):
        return False
    if a.document_period_end_value.strip() != b.document_period_end_value.strip():
        return False
    end_a = _period_end_lexical(a)
    end_b = _period_end_lexical(b)
    if end_a != end_b:
        return False
    return a.document_period_end_value.strip() == end_a


def resolve_required_reporting_period(
    candidates: tuple[DeiPeriodCandidate, ...],
    filing_cik: str,
) -> ReportingPeriod:
    if not candidates:
        raise RequiredPeriodError("no undimensioned dei:DocumentPeriodEndDate fact")
    normalized_filing_cik = validate_cik(filing_cik)
    filtered: list[DeiPeriodCandidate] = []
    for c in candidates:
        if c.context_entity_scheme != SEC_CIK_SCHEME:
            continue
        if validate_cik(c.context_entity_identifier) != normalized_filing_cik:
            continue
        filtered.append(c)
    if not filtered:
        raise RequiredPeriodError("no DEI DocumentPeriodEndDate with SEC CIK entity")
    groups: list[list[DeiPeriodCandidate]] = []
    for c in filtered:
        placed = False
        for group in groups:
            if _candidates_equivalent(group[0], c):
                group.append(c)
                placed = True
                break
        if not placed:
            groups.append([c])
    if len(groups) > 1:
        raise RequiredPeriodError("conflicting DEI DocumentPeriodEndDate contexts")
    chosen = groups[0][0]
    end = _period_end_lexical(chosen)
    if chosen.period_kind == "instant":
        return ReportingPeriod(kind="instant", start=None, end=end)
    if chosen.start_lexical is None:
        raise RequiredPeriodError("DEI duration context missing start_lexical")
    return ReportingPeriod(
        kind="duration",
        start=chosen.start_lexical,
        end=chosen.end_lexical or end,
    )


def period_matches(
    period: ReportingPeriod,
    context_period_kind: str,
    instant_lexical: str | None,
    start_lexical: str | None,
    end_lexical: str | None,
) -> bool:
    if period.kind == "duration":
        if context_period_kind != "duration":
            return False
        return start_lexical == period.start and end_lexical == period.end
    if context_period_kind != "instant":
        return False
    return instant_lexical == period.end
