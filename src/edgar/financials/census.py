"""Distinct-accession counts keyed by expanded QName.

A name-reuse rollup is a separate aggregate. It is not source identity.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from edgar.domain.concept_id import clark_qname
from edgar.financials.taxonomy_release import namespace_release_token
from edgar.xbrl.taxonomy_family import classify


def qname_census(facts: Iterable[tuple[str, str, str]]) -> tuple[dict[str, object], ...]:
    """Count distinct accessions per Clark QName.

    Each item is ``(accession, namespace_uri, local_name)``.
    """
    accessions: dict[str, set[str]] = defaultdict(set)
    for accession, namespace_uri, local_name in facts:
        accessions[clark_qname(namespace_uri, local_name)].add(accession)
    rows = [
        {"qname": qname, "n_accessions": len(seen)} for qname, seen in sorted(accessions.items())
    ]
    return tuple(rows)


def name_reuse_aggregate(
    facts: Sequence[tuple[str, str, str]],
) -> tuple[dict[str, object], ...]:
    """Group by family, namespace release, and local name.

    This rollup is labeled for callers as ``name_reuse_aggregate``. It is not
    a substitute for the QName census.
    """
    accessions: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for accession, namespace_uri, local_name in facts:
        classification = classify(namespace_uri)
        release = namespace_release_token(namespace_uri) or "unknown"
        key = (classification.semantic_family, release, local_name)
        accessions[key].add(accession)
    rows = [
        {
            "aggregate": "name_reuse_aggregate",
            "semantic_family": family,
            "namespace_release": release,
            "local_name": local_name,
            "n_accessions": len(seen),
        }
        for (family, release, local_name), seen in sorted(accessions.items())
    ]
    return tuple(rows)
