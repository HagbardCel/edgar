"""Referential and structural validation of a semantic projection record set.

These checks run before persistence, on the adapter's output alone. They protect
the invariants that make the projection reconstructable and traceable:

- every fact resolves to exactly one concept declaration, exactly one context,
  and — when a unit is referenced — exactly one unit of the same projection
- every relationship endpoint, dimension, member, label, and reference resolves
  to exactly one concept declaration
- locator-addressed rows (contexts, units, fact occurrences) are uniquely
  addressable, so occurrence identity cannot silently collapse
- declared period kinds and their period fields agree

Failures are reported as stable messages rather than raised one at a time, so a
projection attempt can record the complete defect set as quality issues.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from edgar.xbrl.records import (
    ExpandedQName,
    SemanticProjectionData,
    SourceLocator,
)


class SemanticProjectionDataInvalid(ValueError):
    """Raised when a semantic projection record set fails validation."""


def _locator_text(locator: SourceLocator) -> str:
    return f"{locator.document_uri}#{locator.scheme}:{locator.value}"


def _check_declared(
    concept: ExpandedQName,
    declared: Counter[ExpandedQName],
    *,
    label: str,
    role: str,
    errors: list[str],
) -> None:
    count = declared[concept]
    if count != 1:
        errors.append(
            f"{label}: {role} {concept.clark} has {count} concept declarations (expected exactly 1)"
        )


def _check_locator(
    locator: SourceLocator,
    known: Counter[SourceLocator],
    *,
    label: str,
    role: str,
    errors: list[str],
) -> None:
    count = known[locator]
    if count != 1:
        errors.append(
            f"{label}: {role} {_locator_text(locator)} matches {count} rows (expected exactly 1)"
        )


def _report_duplicates(
    counts: Counter[SourceLocator], *, collection: str, errors: list[str]
) -> None:
    for locator, count in sorted(counts.items(), key=lambda item: item[0].sort_key()):
        if count > 1:
            errors.append(
                f"{collection}: duplicate source locator {_locator_text(locator)} "
                f"appears {count} times"
            )


def _validate_contexts(data: SemanticProjectionData, errors: list[str]) -> None:
    for index, context in enumerate(data.contexts):
        label = f"contexts[{index}]"
        has_instant = context.period_instant is not None
        has_start = context.period_start is not None
        has_end = context.period_end is not None
        if context.period_kind == "instant" and not (has_instant and not has_start and not has_end):
            errors.append(f"{label}: instant period requires period_instant only")
        if context.period_kind == "duration" and not (has_start and has_end and not has_instant):
            errors.append(f"{label}: duration period requires period_start and period_end only")
        if context.period_kind == "forever" and (has_instant or has_start or has_end):
            errors.append(f"{label}: forever period must not carry period fields")


def _validate_facts(
    data: SemanticProjectionData,
    declared: Counter[ExpandedQName],
    context_locators: Counter[SourceLocator],
    unit_locators: Counter[SourceLocator],
    errors: list[str],
) -> None:
    for index, fact in enumerate(data.facts):
        label = f"facts[{index}]"
        _check_declared(fact.concept_qname, declared, label=label, role="concept", errors=errors)
        _check_locator(
            fact.context_locator, context_locators, label=label, role="context", errors=errors
        )
        if fact.unit_locator is not None:
            _check_locator(
                fact.unit_locator, unit_locators, label=label, role="unit", errors=errors
            )


def _validate_unit_measures(
    data: SemanticProjectionData,
    unit_locators: Counter[SourceLocator],
    errors: list[str],
) -> None:
    ordinals: dict[tuple[SourceLocator, str], list[int]] = {}
    for index, measure in enumerate(data.unit_measures):
        label = f"unit_measures[{index}]"
        _check_locator(measure.unit_locator, unit_locators, label=label, role="unit", errors=errors)
        ordinals.setdefault((measure.unit_locator, measure.measure_role), []).append(
            measure.ordinal
        )
    for (locator, role), values in sorted(
        ordinals.items(), key=lambda item: (item[0][0].sort_key(), item[0][1])
    ):
        expected = list(range(1, len(values) + 1))
        if sorted(values) != expected:
            errors.append(
                f"unit_measures: {role} ordinals for unit {_locator_text(locator)} are "
                f"{sorted(values)}, expected {expected}"
            )


def _validate_context_dimensions(
    data: SemanticProjectionData,
    declared: Counter[ExpandedQName],
    context_locators: Counter[SourceLocator],
    errors: list[str],
) -> None:
    for index, dimension in enumerate(data.context_dimensions):
        label = f"context_dimensions[{index}]"
        _check_locator(
            dimension.context_locator,
            context_locators,
            label=label,
            role="context",
            errors=errors,
        )
        _check_declared(dimension.dimension, declared, label=label, role="dimension", errors=errors)
        if dimension.member is not None:
            _check_declared(dimension.member, declared, label=label, role="member", errors=errors)


def _validate_relationships(
    data: SemanticProjectionData,
    declared: Counter[ExpandedQName],
    errors: list[str],
) -> None:
    for index, relationship in enumerate(data.relationships):
        label = f"relationships[{index}]"
        _check_declared(
            relationship.source_concept, declared, label=label, role="source concept", errors=errors
        )
        _check_declared(
            relationship.target_concept, declared, label=label, role="target concept", errors=errors
        )
        if not relationship.link_role_uri:
            errors.append(f"{label}: link_role_uri is required")
        if not relationship.arcrole_uri:
            errors.append(f"{label}: arcrole_uri is required")


def _validate_resources(
    data: SemanticProjectionData,
    declared: Counter[ExpandedQName],
    errors: list[str],
) -> None:
    for index, label_record in enumerate(data.concept_labels):
        _check_declared(
            label_record.concept,
            declared,
            label=f"concept_labels[{index}]",
            role="concept",
            errors=errors,
        )
    for index, reference in enumerate(data.concept_references):
        _check_declared(
            reference.concept,
            declared,
            label=f"concept_references[{index}]",
            role="concept",
            errors=errors,
        )


def _validate_declaration_uniqueness(declared: Counter[ExpandedQName], errors: list[str]) -> None:
    for concept, count in sorted(declared.items(), key=lambda item: item[0].sort_key()):
        if count > 1:
            errors.append(
                f"concept_declarations: {concept.clark} is declared {count} times "
                "(expected exactly 1 per projection)"
            )


def _validate_declaration_uris(data: SemanticProjectionData, errors: list[str]) -> None:
    seen: set[tuple[str, str]] = set()
    for index, role in enumerate(data.role_declarations):
        key = (role.role_uri, _locator_text(role.source_locator))
        if key in seen:
            errors.append(f"role_declarations[{index}]: duplicate declaration occurrence {key[0]}")
        seen.add(key)
    seen.clear()
    for index, arcrole in enumerate(data.arcrole_declarations):
        key = (arcrole.arcrole_uri, _locator_text(arcrole.source_locator))
        if key in seen:
            errors.append(
                f"arcrole_declarations[{index}]: duplicate declaration occurrence {key[0]}"
            )
        seen.add(key)


def validate_semantic_projection_data(data: SemanticProjectionData) -> tuple[str, ...]:
    """Return every validation failure; an empty tuple means the record set is valid."""
    errors: list[str] = []

    declared: Counter[ExpandedQName] = Counter(
        declaration.concept for declaration in data.concept_declarations
    )
    context_locators: Counter[SourceLocator] = Counter(
        context.source_locator for context in data.contexts
    )
    unit_locators: Counter[SourceLocator] = Counter(unit.source_locator for unit in data.units)
    fact_locators: Counter[SourceLocator] = Counter(fact.source_locator for fact in data.facts)

    _validate_declaration_uniqueness(declared, errors)
    _report_duplicates(context_locators, collection="contexts", errors=errors)
    _report_duplicates(unit_locators, collection="units", errors=errors)
    _report_duplicates(fact_locators, collection="facts", errors=errors)
    _validate_contexts(data, errors)
    _validate_facts(data, declared, context_locators, unit_locators, errors)
    _validate_unit_measures(data, unit_locators, errors)
    _validate_context_dimensions(data, declared, context_locators, errors)
    _validate_relationships(data, declared, errors)
    _validate_resources(data, declared, errors)
    _validate_declaration_uris(data, errors)

    return tuple(errors)


def assert_semantic_projection_data_valid(data: SemanticProjectionData) -> None:
    """Raise :class:`SemanticProjectionDataInvalid` when validation fails."""
    errors = validate_semantic_projection_data(data)
    if errors:
        raise SemanticProjectionDataInvalid(_format_errors(errors))


def _format_errors(errors: Iterable[str]) -> str:
    return "; ".join(errors)
