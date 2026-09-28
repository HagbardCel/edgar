"""Annual-v1 as-filed observation selection."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from edgar.domain.identifiers import validate_cik
from edgar.financials.decimals import NumericFactOccurrence, oim_reduce_group
from edgar.financials.decisions import DecisionRegistry, decision_applies_to_filing
from edgar.financials.models import FactRow, Observation, Support, SupportRef
from edgar.financials.period import (
    SEC_CIK_SCHEME,
    MetricPeriodType,
    ReportingPeriod,
    period_matches_metric,
)

ISO_USD_NS = "http://www.xbrl.org/2003/iso4217"
ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})


def _is_pure_usd(measures: tuple) -> bool:
    from edgar.financials.models import UnitMeasureRow

    nums = [m for m in measures if m.side == "numerator"]
    dens = [m for m in measures if m.side == "denominator"]
    if dens or len(nums) != 1:
        return False
    m: UnitMeasureRow = nums[0]
    return m.measure_namespace_uri == ISO_USD_NS and m.measure_local_name == "USD"


def _entity_matches(fact: FactRow, filing_cik: str) -> bool:
    if fact.entity_scheme != SEC_CIK_SCHEME:
        return False
    return validate_cik(fact.entity_identifier) == validate_cik(filing_cik)


def _fact_qualifies_slot(
    fact: FactRow,
    filing_cik: str,
    period: ReportingPeriod,
    metric_period_type: MetricPeriodType,
) -> bool:
    if fact.has_dimensions:
        return False
    if fact.value_status != "valid" or fact.is_nil or fact.resolved_numeric is None:
        return False
    if not _entity_matches(fact, filing_cik):
        return False
    if not _is_pure_usd(fact.unit_measures):
        return False
    return period_matches_metric(
        metric_period_type,
        period,
        fact.period_kind,
        fact.instant_lexical,
        fact.start_lexical,
        fact.end_lexical,
    )


def select_metric(
    metric: str,
    form: str,
    filing_cik: str,
    accession: str,
    period: ReportingPeriod | None,
    facts: tuple[FactRow, ...],
    supports: tuple[Support, ...],
    registry: DecisionRegistry,
    available_at: str | None,
    *,
    metric_period_type: MetricPeriodType,
) -> Observation:
    base = Observation(
        cik=filing_cik,
        accession=accession,
        metric=metric,
        fy=period.fiscal_year_focus if period else None,
        report_focus=period.fiscal_period_focus if period else None,
        period_role=None,
        period_start=(
            period.start if period is not None and metric_period_type == "duration" else None
        ),
        period_end=period.end if period else None,
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
        available_at=available_at,
    )
    if form not in ANNUAL_FORMS:
        base.status = "unsupported"
        base.reason = "wrong_form"
        return base
    assert period is not None

    exact_all = [
        ld.record
        for ld in registry.decisions
        if not ld.stale_inactive
        and ld.record.status == "accepted"
        and ld.record.relation == "exact"
        and ld.record.metric == metric
    ]
    applicable = [r for r in exact_all if decision_applies_to_filing(r, filing_cik)]
    if exact_all and not applicable:
        base.status = "unsupported"
        base.reason = "decision_scope"
        return base

    exact_supports = [s for s in supports if s.metric == metric and s.relation == "exact"]
    candidates: list[tuple[Support, FactRow]] = []
    fact_by_id = {f.fact_id: f for f in facts}
    for s in exact_supports:
        fact = fact_by_id.get(s.fact_id)
        if fact is None:
            continue
        if _fact_qualifies_slot(fact, filing_cik, period, metric_period_type):
            candidates.append((s, fact))

    broader_supports = [s for s in supports if s.metric == metric and s.relation == "broader"]
    broader_qualified = any(
        _fact_qualifies_slot(fact_by_id[s.fact_id], filing_cik, period, metric_period_type)
        for s in broader_supports
        if s.fact_id in fact_by_id
    )

    if not candidates:
        base.status = "missing"
        if broader_qualified:
            base.reason = "broader_only"
        return base

    by_qname: dict[str, list[tuple[Support, FactRow]]] = defaultdict(list)
    for s, f in candidates:
        by_qname[s.source_qname].append((s, f))

    survivors: list[tuple[Support, FactRow, Decimal, str | None, tuple[int, ...]]] = []
    for _qname, group in by_qname.items():
        occs = tuple(
            NumericFactOccurrence(f.fact_id, f.resolved_numeric, f.decimals)
            for _, f in group
            if f.resolved_numeric is not None
        )
        reduced = oim_reduce_group(occs)
        if reduced is None:
            base.status = "conflict"
            base.reason = None
            return base
        rep_support, rep_fact = group[0]
        survivors.append(
            (
                rep_support,
                rep_fact,
                reduced.survivor_value,
                reduced.survivor_decimals,
                reduced.fact_ids,
            )
        )

    values = {sv[2] for sv in survivors}
    if len(values) > 1:
        base.status = "conflict"
        return base

    value = survivors[0][2]
    decimals = survivors[0][3]
    all_fact_ids: list[int] = []
    all_supports: list[SupportRef] = []
    decision_ids: set[str] = set()
    for s, _f, _, _, fids in survivors:
        decision_ids.add(s.decision_id)
        for fid in fids:
            all_supports.append(
                SupportRef(
                    fact_id=fid,
                    decision_id=s.decision_id,
                    relation="exact",
                    tier=1,
                    source_qname=s.source_qname,
                    application_method=s.application_method,
                )
            )
            all_fact_ids.append(fid)

    base.status = "value"
    base.numeric = value
    base.decimals = decimals
    base.relation = "exact"
    base.tier = 1
    base.decision_ids = tuple(sorted(decision_ids))
    base.fact_ids = tuple(sorted(set(all_fact_ids)))
    base.supports = tuple(sorted(all_supports, key=lambda r: (r.fact_id, r.decision_id)))
    return base
