"""Unit tests for semantic projection records, config, locators, and validation."""

from __future__ import annotations

import lxml.etree as etree

from edgar.xbrl.config import (
    SEMANTIC_PROJECTION_VERSION,
    build_semantic_config,
    semantic_config_fingerprint,
)
from edgar.xbrl.diagnostics import COMPLETE_COMPATIBLE_DIAGNOSTICS, classify_diagnostic
from edgar.xbrl.locators import element_locator
from edgar.xbrl.records import (
    ConceptDeclarationRecord,
    DiagnosticRecord,
    ExpandedQName,
    FactRecord,
    ReferencePartRecord,
    SemanticProjectionData,
    SourceLocator,
)
from edgar.xbrl.validate_records import validate_semantic_projection_data


def test_config_fingerprint_deterministic() -> None:
    a = build_semantic_config()
    b = build_semantic_config()
    assert semantic_config_fingerprint(a) == semantic_config_fingerprint(b)
    assert SEMANTIC_PROJECTION_VERSION == "arelle-semantic-v2"


def test_invalid_transformation_is_complete_compatible() -> None:
    assert "ix11.10.1.2:invalidTransformation" in COMPLETE_COMPATIBLE_DIAGNOSTICS
    assert "ix11.11.1.2:invalidTransformation" in COMPLETE_COMPATIBLE_DIAGNOSTICS
    for code in (
        "ix11.10.1.2:invalidTransformation",
        "ix11.11.1.2:invalidTransformation",
    ):
        diag = DiagnosticRecord(severity="warning", code=code)
        assert classify_diagnostic(diag) == "complete_compatible"
        assert "faithfully" in COMPLETE_COMPATIBLE_DIAGNOSTICS[code].lower() or (
            "invalid" in COMPLETE_COMPATIBLE_DIAGNOSTICS[code].lower()
        )


def test_expanded_qname_prefix_independent() -> None:
    a = ExpandedQName(namespace_uri="http://example.com", local_name="Revenue")
    b = ExpandedQName.from_clark("{http://example.com}Revenue")
    assert a == b
    assert a.clark == "{http://example.com}Revenue"


def test_locator_prefers_unique_xml_id() -> None:
    root = etree.fromstring(
        b"""<x xmlns:xml="http://www.w3.org/XML/1998/namespace">
              <a xml:id="c1"/><b xml:id="c2"/>
            </x>"""
    )
    loc = element_locator(root[0], document_uri="https://example.com/doc.xml")
    assert loc.scheme == "xml_id"
    assert loc.value == "c1"


def test_locator_falls_back_when_id_not_unique() -> None:
    root = etree.fromstring(b"""<x><a id="dup"/><b id="dup"/></x>""")
    loc = element_locator(root[0], document_uri="https://example.com/doc.xml")
    assert loc.scheme == "expanded_element_path"


def test_validate_dangling_context_ref_fails() -> None:
    concept = ExpandedQName(namespace_uri="http://example.com", local_name="Assets")
    decl_loc = SourceLocator(
        document_uri="https://example.com/t.xsd", scheme="unqualified_id", value="Assets"
    )
    fact_loc = SourceLocator(
        document_uri="https://example.com/a.xml", scheme="unqualified_id", value="f1"
    )
    missing_ctx = SourceLocator(
        document_uri="https://example.com/a.xml", scheme="unqualified_id", value="missing"
    )
    data = SemanticProjectionData(
        projection_version="arelle-semantic-v1",
        config_fingerprint="a" * 64,
        engine_name="arelle",
        engine_version="1",
        concept_declarations=(ConceptDeclarationRecord(concept=concept, source_locator=decl_loc),),
        facts=(
            FactRecord(
                concept_qname=concept,
                context_locator=missing_ctx,
                source_locator=fact_loc,
                value_status="valid",
                raw_lexical_value="1",
                resolved_text_value="1",
            ),
        ),
    )
    errors = validate_semantic_projection_data(data)
    assert errors
    assert any("context" in err.lower() for err in errors)


def test_reference_part_preserves_xml() -> None:
    part = ReferencePartRecord(
        namespace_uri="http://www.xbrl.org/2003/ref",
        local_name="Nested",
        text="outer",
        xml='<ref:Nested xmlns:ref="http://www.xbrl.org/2003/ref"><ref:Inner/></ref:Nested>',
    )
    assert part.xml is not None
    assert "<ref:Inner" in part.xml
    round_trip = ReferencePartRecord.from_dict(part.to_dict())
    assert round_trip.xml == part.xml


def test_qname_typed_value_encoding() -> None:
    q = ExpandedQName(namespace_uri="http://fasb.org/us-gaap/2023", local_name="Revenue")
    assert q.clark == "{http://fasb.org/us-gaap/2023}Revenue"
    assert "us-gaap:" not in q.clark


def test_dual_label_provenance_round_trip() -> None:
    from edgar.xbrl.records import ConceptLabelRecord

    concept = ExpandedQName(namespace_uri="http://example.com", local_name="Assets")
    resource = SourceLocator(
        document_uri="https://example.com/lab.xml", scheme="unqualified_id", value="lab1"
    )
    arc = SourceLocator(
        document_uri="https://example.com/lab.xml", scheme="unqualified_id", value="arc1"
    )
    label = ConceptLabelRecord(
        concept=concept,
        link_role_uri="http://www.xbrl.org/2003/role/link",
        arcrole_uri="http://www.xbrl.org/2003/arcrole/concept-label",
        text="Assets",
        source_locator=resource,
        arc_locator=arc,
        resource_role_uri="http://www.xbrl.org/2003/role/label",
        xml_lang="en",
    )
    encoded = label.to_dict()
    assert encoded["source_locator"]["value"] == "lab1"
    assert encoded["arc_locator"]["value"] == "arc1"
    assert ConceptLabelRecord.from_dict(encoded) == label


def test_reference_parts_ordered_list_not_map() -> None:
    from edgar.xbrl.records import ConceptReferenceRecord, ReferencePartRecord

    concept = ExpandedQName(namespace_uri="http://example.com", local_name="Assets")
    parts = (
        ReferencePartRecord(
            namespace_uri="http://www.xbrl.org/2006/ref",
            local_name="Name",
            text="ASC",
            xml='<ref:Name xmlns:ref="http://www.xbrl.org/2006/ref">ASC</ref:Name>',
        ),
        ReferencePartRecord(
            namespace_uri="http://www.xbrl.org/2006/ref",
            local_name="Nested",
            text="outer",
            xml='<ref:Nested xmlns:ref="http://www.xbrl.org/2006/ref"><ref:Inner/></ref:Nested>',
        ),
    )
    ref = ConceptReferenceRecord(
        concept=concept,
        link_role_uri="http://www.xbrl.org/2003/role/link",
        arcrole_uri="http://www.xbrl.org/2003/arcrole/concept-reference",
        source_locator=SourceLocator(
            document_uri="https://example.com/ref.xml", scheme="unqualified_id", value="r1"
        ),
        arc_locator=SourceLocator(
            document_uri="https://example.com/ref.xml", scheme="unqualified_id", value="a1"
        ),
        reference_parts=parts,
    )
    encoded = ref.to_dict()
    assert isinstance(encoded["reference_parts"], list)
    assert [p["local_name"] for p in encoded["reference_parts"]] == ["Name", "Nested"]
    assert "<ref:Inner" in encoded["reference_parts"][1]["xml"]
