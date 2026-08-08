"""Deterministic verified-reuse equality ordering tests."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from edgar.db.semantic import semantic_projection_equality_state
from edgar.xbrl.records import (
    ArcroleDeclarationRecord,
    ConceptDeclarationRecord,
    ConceptLabelRecord,
    ConceptReferenceRecord,
    ContextDimensionRecord,
    ContextRecord,
    ExpandedQName,
    FactRecord,
    ReferencePartRecord,
    RelationshipRecord,
    RoleDeclarationRecord,
    SemanticIssueRecord,
    SemanticProjectionData,
    SourceLocator,
    UnitMeasureRecord,
    UnitRecord,
)

_NS = "http://example.com/eq"
_DOC = "https://example.com/a.xml"
_CFG = {"projection_version": "arelle-semantic-v1"}


def _loc(value: str, doc: str = _DOC) -> SourceLocator:
    return SourceLocator(document_uri=doc, scheme="unqualified_id", value=value)


def _q(name: str) -> ExpandedQName:
    return ExpandedQName(namespace_uri=_NS, local_name=name)


def _multi_collection_data() -> SemanticProjectionData:
    """Synthetic projection with ≥2 entries in every equality collection."""
    concepts = (_q("A"), _q("B"))
    decls = tuple(
        ConceptDeclarationRecord(concept=c, source_locator=_loc(f"decl-{c.local_name}"))
        for c in concepts
    )
    labels = tuple(
        ConceptLabelRecord(
            concept=c,
            link_role_uri="http://www.xbrl.org/2003/role/link",
            arcrole_uri="http://www.xbrl.org/2003/arcrole/concept-label",
            text=c.local_name,
            source_locator=_loc(f"lab-{c.local_name}"),
            arc_locator=_loc(f"lab-arc-{c.local_name}"),
            resource_role_uri="http://www.xbrl.org/2003/role/label",
            xml_lang="en",
        )
        for c in concepts
    )
    refs = tuple(
        ConceptReferenceRecord(
            concept=c,
            link_role_uri="http://www.xbrl.org/2003/role/link",
            arcrole_uri="http://www.xbrl.org/2003/arcrole/concept-reference",
            source_locator=_loc(f"ref-{c.local_name}"),
            arc_locator=_loc(f"ref-arc-{c.local_name}"),
            reference_parts=(
                ReferencePartRecord(
                    namespace_uri="http://www.xbrl.org/2006/ref",
                    local_name="Name",
                    text=c.local_name,
                    xml=f'<ref:Name xmlns:ref="http://www.xbrl.org/2006/ref">{c.local_name}</ref:Name>',
                ),
            ),
        )
        for c in concepts
    )
    roles = tuple(
        RoleDeclarationRecord(
            role_uri=f"http://example.com/role/{suffix}",
            source_locator=_loc(f"role-{suffix}"),
            definition=suffix,
        )
        for suffix in ("One", "Two")
    )
    arcroles = tuple(
        ArcroleDeclarationRecord(
            arcrole_uri=f"http://example.com/arcrole/{suffix}",
            source_locator=_loc(f"arcrole-{suffix}"),
            definition=suffix,
            cycles_allowed="any",
        )
        for suffix in ("One", "Two")
    )
    contexts = tuple(
        ContextRecord(
            source_context_id=f"c{i}",
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0000000001",
            period_kind="instant",
            source_locator=_loc(f"c{i}"),
            period_instant="2024-12-31",
        )
        for i in (1, 2)
    )
    dims = tuple(
        ContextDimensionRecord(
            context_locator=contexts[i].source_locator,
            dimension=_q("Axis"),
            context_element="segment",
            member_kind="explicit",
            source_locator=_loc(f"dim{i}"),
            member=_q(f"Member{i}"),
        )
        for i in (0, 1)
    )
    units = tuple(
        UnitRecord(source_unit_id=f"u{i}", source_locator=_loc(f"u{i}"), divide=False)
        for i in (1, 2)
    )
    measures = tuple(
        UnitMeasureRecord(
            unit_locator=units[i].source_locator,
            measure_role="numerator",
            ordinal=1,
            measure=_q(f"USD{i}"),
        )
        for i in (0, 1)
    )
    facts = tuple(
        FactRecord(
            concept_qname=concepts[i],
            context_locator=contexts[i].source_locator,
            source_locator=_loc(f"f{i + 1}"),
            value_status="valid",
            unit_locator=units[i].source_locator,
            raw_lexical_value="1",
            resolved_numeric_value=Decimal("1"),
            resolved_value_kind="numeric",
            resolved_value_type=_q("monetaryItemType"),
        )
        for i in (0, 1)
    )
    rels = tuple(
        RelationshipRecord(
            network_type="presentation",
            link_role_uri="http://example.com/role/One",
            arcrole_uri="http://www.xbrl.org/2003/arcrole/parent-child",
            source_concept=concepts[0],
            target_concept=concepts[1] if i == 0 else concepts[0],
            source_locator=_loc(f"rel{i}"),
            order=Decimal(str(i + 1)),
        )
        for i in (0, 1)
    )
    issues = (
        SemanticIssueRecord(severity="warning", code="W1", message="a", context={"x": 1}),
        SemanticIssueRecord(
            severity="warning", code="W2", message="b", context={"nested": {"k": 2}}
        ),
    )
    return SemanticProjectionData(
        projection_version="arelle-semantic-v1",
        config_fingerprint="a" * 64,
        engine_name="arelle",
        engine_version="2.43.1",
        concept_declarations=decls,
        concept_labels=labels,
        concept_references=refs,
        role_declarations=roles,
        arcrole_declarations=arcroles,
        contexts=contexts,
        context_dimensions=dims,
        units=units,
        unit_measures=measures,
        facts=facts,
        relationships=rels,
        issues=issues,
    )


_COLLECTIONS = (
    "concept_declarations",
    "concept_labels",
    "concept_references",
    "role_declarations",
    "arcrole_declarations",
    "contexts",
    "context_dimensions",
    "units",
    "unit_measures",
    "facts",
    "relationships",
    "issues",
)


@pytest.mark.parametrize("collection", _COLLECTIONS)
def test_equality_state_independent_of_collection_order(collection: str) -> None:
    data = _multi_collection_data()
    original = getattr(data, collection)
    assert len(original) >= 2
    reversed_data = replace(data, **{collection: tuple(reversed(original))})
    a = semantic_projection_equality_state(data, status="complete", semantic_config=_CFG)
    b = semantic_projection_equality_state(reversed_data, status="complete", semantic_config=_CFG)
    assert a == b
    assert a[collection] == b[collection]


def test_equality_state_preserves_duplicate_fact_multiplicity() -> None:
    data = _multi_collection_data()
    twin = data.facts[0]
    with_dup = replace(data, facts=(twin, twin, data.facts[1]))
    state = semantic_projection_equality_state(with_dup, status="complete", semantic_config=_CFG)
    assert len(state["facts"]) == 3
    assert state["facts"].count(twin.to_dict()) == 2


def test_clark_looking_string_stays_text_kind() -> None:
    fact = FactRecord(
        concept_qname=_q("Note"),
        context_locator=_loc("c1"),
        source_locator=_loc("f1"),
        value_status="valid",
        raw_lexical_value="{foo}bar",
        resolved_text_value="{foo}bar",
        resolved_value_kind="text",
    )
    assert fact.resolved_value_kind == "text"
    assert fact.to_dict()["resolved_value_kind"] == "text"
