"""Pure policy for P0 v5→v6 structural baseline comparison (testable)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from edgar.xbrl.taxonomy_family import classify

ConceptKey = tuple[str | None, str]


def concept_key(qname: Mapping[str, Any]) -> ConceptKey:
    local = qname["local_name"]
    if not isinstance(local, str):
        raise TypeError("concept local_name must be str")
    namespace = qname.get("namespace_uri")
    if namespace is not None and not isinstance(namespace, str):
        raise TypeError("concept namespace_uri must be str or None")
    return (namespace, local)


def declaration_concept_key(declaration: Mapping[str, Any]) -> ConceptKey:
    return concept_key(declaration["concept"])


def filed_keep(baseline: Mapping[str, Any]) -> frozenset[ConceptKey]:
    keys: set[ConceptKey] = set()
    for fact in baseline.get("facts") or ():
        keys.add(concept_key(fact["concept"]))
    for relationship in baseline.get("relationships") or ():
        keys.add(concept_key(relationship["source_concept"]))
        keys.add(concept_key(relationship["target_concept"]))
    for dimension in baseline.get("dimensions") or ():
        keys.add(concept_key(dimension["dimension"]))
        if dimension.get("member_kind") == "explicit":
            member = dimension.get("member")
            if member is not None:
                keys.add(concept_key(member))
    return frozenset(keys)


def issuer_declaration_keys(baseline: Mapping[str, Any]) -> frozenset[ConceptKey]:
    issuer: set[ConceptKey] = set()
    for declaration in baseline.get("declarations") or ():
        key = declaration_concept_key(declaration)
        if classify(key[0]).origin == "issuer":
            issuer.add(key)
    return frozenset(issuer)


def expected_keep(baseline: Mapping[str, Any]) -> frozenset[ConceptKey]:
    return filed_keep(baseline) | issuer_declaration_keys(baseline)


def declaration_keys(baseline: Mapping[str, Any]) -> frozenset[ConceptKey]:
    return frozenset(declaration_concept_key(d) for d in baseline.get("declarations") or ())


def assert_filed_keep_in_declarations(baseline: Mapping[str, Any]) -> None:
    filed = filed_keep(baseline)
    declared = declaration_keys(baseline)
    missing = filed - declared
    if missing:
        raise ValueError(
            f"filed_keep concepts missing from baseline declarations: {sorted(missing)}"
        )


def filter_declarations(
    baseline: Mapping[str, Any], keep: frozenset[ConceptKey]
) -> list[dict[str, Any]]:
    return [
        dict(declaration)
        for declaration in baseline.get("declarations") or ()
        if declaration_concept_key(declaration) in keep
    ]


def filter_concepts(
    baseline: Mapping[str, Any], keep: frozenset[ConceptKey]
) -> list[dict[str, Any]]:
    return [
        dict(concept) for concept in baseline.get("concepts") or () if concept_key(concept) in keep
    ]


def filter_labels(baseline: Mapping[str, Any], keep: frozenset[ConceptKey]) -> list[dict[str, Any]]:
    return [
        dict(label)
        for label in baseline.get("labels") or ()
        if concept_key(label["concept"]) in keep
    ]


def filter_references(
    baseline: Mapping[str, Any], keep: frozenset[ConceptKey]
) -> list[dict[str, Any]]:
    return [
        dict(reference)
        for reference in baseline.get("references") or ()
        if concept_key(reference["concept"]) in keep
    ]


def without_source_order(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "source_order"}


def normalized_resource_sequence(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [without_source_order(record) for record in records]


def assert_contiguous_source_order(records: Sequence[Mapping[str, Any]], *, what: str) -> None:
    orders = [record.get("source_order") for record in records]
    expected = list(range(len(records)))
    if orders != expected:
        raise ValueError(f"{what} source_order must be contiguous 0..n-1: got {orders}")


def issue_code_counts(issues: Sequence[Mapping[str, Any]]) -> Counter[str]:
    return Counter(str(issue["code"]) for issue in issues)


def issue_delta(baseline: Counter[str], current: Counter[str]) -> tuple[Counter[str], Counter[str]]:
    return current - baseline, baseline - current


@dataclass(frozen=True)
class FilterCompareResult:
    errors: tuple[str, ...]
    issuer_declarations: int
    issuer_only: int


def compare_v6_filter(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
) -> FilterCompareResult:
    """Compare v6 output to the expected filter transformation of v5."""
    errors: list[str] = []
    try:
        assert_filed_keep_in_declarations(baseline)
    except ValueError as exc:
        return FilterCompareResult(errors=(str(exc),), issuer_declarations=0, issuer_only=0)

    keep = expected_keep(baseline)
    filed = filed_keep(baseline)
    issuer_decl = issuer_declaration_keys(baseline)
    issuer_only = issuer_decl - filed

    expected_declarations = filter_declarations(baseline, keep)
    expected_concepts = filter_concepts(baseline, keep)
    expected_labels = filter_labels(baseline, keep)
    expected_references = filter_references(baseline, keep)

    if current.get("declarations") != expected_declarations:
        errors.append("declarations do not match expected v6 filter from baseline")
    if current.get("concepts") != expected_concepts:
        errors.append("concepts do not match expected v6 filter from baseline")

    current_labels = list(current.get("labels") or ())
    current_references = list(current.get("references") or ())
    try:
        assert_contiguous_source_order(current_labels, what="labels")
        assert_contiguous_source_order(current_references, what="references")
    except ValueError as exc:
        errors.append(str(exc))

    if normalized_resource_sequence(current_labels) != normalized_resource_sequence(
        expected_labels
    ):
        errors.append("labels do not match expected v6 filter from baseline")
    if normalized_resource_sequence(current_references) != normalized_resource_sequence(
        expected_references
    ):
        errors.append("references do not match expected v6 filter from baseline")

    return FilterCompareResult(
        errors=tuple(errors),
        issuer_declarations=len(issuer_decl),
        issuer_only=len(issuer_only),
    )
