"""Accounting identity diagnostics and gold checking."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from edgar.financials.decimals import ClosedInterval, NumericFactOccurrence, oim_reduce_group
from edgar.financials.gold import GoldAssertion, compare_gold
from edgar.financials.models import FactRow, Observation
from edgar.financials.period import ReportingPeriod, period_matches_metric
from edgar.financials.select import _entity_matches, _is_pure_usd

FindingStatus = Literal["pass", "fail", "not_applicable"]


@dataclass(frozen=True)
class IdentityFinding:
    name: str
    accession: str
    status: FindingStatus
    detail: str | None = None


def _qualifying_facts(
    facts: tuple[FactRow, ...],
    filing_cik: str,
    period: ReportingPeriod,
    local_name: str,
    duration: bool,
) -> tuple[FactRow, ...]:
    out: list[FactRow] = []
    for f in facts:
        if f.concept_local_name != local_name:
            continue
        if "us-gaap" not in f.concept_namespace and "xbrl.us/us-gaap" not in f.concept_namespace:
            continue
        if f.has_dimensions or f.value_status != "valid" or f.is_nil or f.resolved_numeric is None:
            continue
        if not _entity_matches(f, filing_cik) or not _is_pure_usd(f.unit_measures):
            continue
        metric_period_type = "duration" if duration else "instant"
        if not period_matches_metric(
            metric_period_type,
            period,
            f.period_kind,
            f.instant_lexical,
            f.start_lexical,
            f.end_lexical,
        ):
            continue
        out.append(f)
    return tuple(out)


def _operand_interval(facts: tuple[FactRow, ...]) -> ClosedInterval | None:
    by_qname: dict[str, list[FactRow]] = defaultdict(list)
    for f in facts:
        by_qname[f"{f.concept_namespace}|{f.concept_local_name}"].append(f)
    intervals: list[ClosedInterval] = []
    survivor_values: list[Decimal] = []
    for group in by_qname.values():
        occs = tuple(
            NumericFactOccurrence(f.fact_id, f.resolved_numeric, f.decimals)
            for f in group
            if f.resolved_numeric is not None
        )
        reduced = oim_reduce_group(occs)
        if reduced is None:
            return None
        survivor_values.append(reduced.survivor_value)
        intervals.append(reduced.consistent_interval)
    if not intervals:
        return None
    if len(set(survivor_values)) > 1:
        return None
    if len(intervals) > 1:
        lo = max(i.lo for i in intervals)
        hi = min(i.hi for i in intervals)
        if lo > hi:
            return None
        return ClosedInterval(lo, hi)
    return intervals[0]


def run_identity_checks(
    accession: str,
    filing_cik: str,
    period: ReportingPeriod,
    facts: tuple[FactRow, ...],
) -> tuple[IdentityFinding, ...]:
    findings: list[IdentityFinding] = []
    findings.append(_nci_split(accession, filing_cik, period, facts))
    findings.append(_balance_sheet(accession, filing_cik, period, facts))
    return tuple(findings)


def _nci_split(
    accession: str,
    filing_cik: str,
    period: ReportingPeriod,
    facts: tuple[FactRow, ...],
) -> IdentityFinding:
    name = "nci_split"
    pl = _qualifying_facts(facts, filing_cik, period, "ProfitLoss", duration=True)
    ni = _qualifying_facts(facts, filing_cik, period, "NetIncomeLoss", duration=True)
    nci_local = "NetIncomeLossAttributableToNoncontrollingInterest"
    nci = _qualifying_facts(facts, filing_cik, period, nci_local, duration=True)
    if not pl or not ni or not nci:
        return IdentityFinding(name, accession, "not_applicable", None)
    i_pl = _operand_interval(pl)
    i_ni = _operand_interval(ni)
    i_nci = _operand_interval(nci)
    if i_pl is None or i_ni is None or i_nci is None:
        return IdentityFinding(name, accession, "fail", "inconsistent duplicate facts")
    rhs = i_ni + i_nci
    if i_pl.intersects(rhs):
        return IdentityFinding(name, accession, "pass", None)
    return IdentityFinding(name, accession, "fail", "intervals disjoint")


def _balance_sheet(
    accession: str,
    filing_cik: str,
    period: ReportingPeriod,
    facts: tuple[FactRow, ...],
) -> IdentityFinding:
    name = "balance_sheet"
    assets = _qualifying_facts(facts, filing_cik, period, "Assets", duration=False)
    liab = _qualifying_facts(facts, filing_cik, period, "Liabilities", duration=False)
    if not assets or not liab:
        return IdentityFinding(name, accession, "not_applicable", None)
    total_eq = _qualifying_facts(
        facts,
        filing_cik,
        period,
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        duration=False,
    )
    equity_facts: tuple[FactRow, ...]
    if total_eq:
        equity_facts = total_eq
    else:
        has_nci_balance = bool(
            _qualifying_facts(facts, filing_cik, period, "MinorityInterest", False)
        )
        has_nci_activity = bool(
            _qualifying_facts(
                facts,
                filing_cik,
                period,
                "NetIncomeLossAttributableToNoncontrollingInterest",
                duration=True,
            )
        )
        parent_eq = _qualifying_facts(
            facts, filing_cik, period, "StockholdersEquity", duration=False
        )
        if parent_eq and not has_nci_balance and not has_nci_activity:
            equity_facts = parent_eq
        else:
            return IdentityFinding(name, accession, "not_applicable", None)
    i_a = _operand_interval(assets)
    i_l = _operand_interval(liab)
    i_e = _operand_interval(equity_facts)
    if i_a is None or i_l is None or i_e is None:
        return IdentityFinding(name, accession, "fail", "inconsistent duplicate facts")
    rhs = i_l + i_e
    if i_a.intersects(rhs):
        return IdentityFinding(name, accession, "pass", None)
    return IdentityFinding(name, accession, "fail", "intervals disjoint")


def check_gold_assertions(
    assertions: tuple[GoldAssertion, ...],
    observations: tuple[Observation, ...],
    build_accessions: frozenset[str],
) -> tuple[int, list[str]]:
    obs_index = {(o.accession, o.metric): o for o in observations}
    errors: list[str] = []
    checked = 0
    for assertion in assertions:
        if assertion.accession not in build_accessions:
            continue
        checked += 1
        obs = obs_index.get((assertion.accession, assertion.metric))
        if obs is None:
            errors.append(f"{assertion.id}: no observation for {assertion.metric}")
            continue
        err = compare_gold(assertion, obs)
        if err:
            errors.append(f"{assertion.id}: {err}")
    return checked, errors
