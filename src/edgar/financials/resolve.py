"""Map source facts to mapping supports."""

from __future__ import annotations

from edgar.domain.concept_id import clark_qname
from edgar.financials.decisions import DecisionRegistry, issuer_excluded
from edgar.financials.models import FactRow, Support


def resolve_supports(
    facts: tuple[FactRow, ...],
    registry: DecisionRegistry,
    accession: str,
    filing_cik: str,
) -> tuple[Support, ...]:
    supports: list[Support] = []
    for fact in facts:
        for ld in registry.decisions:
            record = ld.record
            if ld.stale_inactive or record.status != "accepted":
                continue
            if issuer_excluded(record, filing_cik):
                continue
            if not _concept_matches(
                record, filing_cik, fact.concept_namespace, fact.concept_local_name
            ):
                continue
            supports.append(
                Support(
                    fact_id=fact.fact_id,
                    accession=accession,
                    concept_namespace=fact.concept_namespace,
                    concept_local_name=fact.concept_local_name,
                    source_qname=clark_qname(fact.concept_namespace, fact.concept_local_name),
                    metric=record.metric,
                    relation=record.relation,
                    decision_id=record.id,
                    application_method=record.method,
                    tier=1,
                )
            )
    return tuple(supports)


def _concept_matches(record, filing_cik: str, namespace_uri: str, local_name: str) -> bool:
    from edgar.financials.decisions import concept_matches_decision

    return concept_matches_decision(record, filing_cik, namespace_uri, local_name)
