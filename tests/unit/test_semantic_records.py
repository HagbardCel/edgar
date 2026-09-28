"""Unit tests for extraction config, locators, and diagnostics."""

from __future__ import annotations

import lxml.etree as etree

from edgar.xbrl.config import FACT_LEXICAL_VERSION, build_semantic_config
from edgar.xbrl.diagnostics import COMPLETE_COMPATIBLE_DIAGNOSTICS, classify_diagnostic
from edgar.xbrl.locators import element_locator
from edgar.xbrl.records import DiagnosticRecord, ExpandedQName


def test_config_policy_knobs_stable() -> None:
    a = build_semantic_config()
    b = build_semantic_config()
    assert a.to_dict() == b.to_dict()
    assert a.fact_lexical_version == FACT_LEXICAL_VERSION
    assert not hasattr(a, "projection_version")


def test_invalid_transformation_is_complete_compatible() -> None:
    assert "ix11.10.1.2:invalidTransformation" in COMPLETE_COMPATIBLE_DIAGNOSTICS
    assert "ix11.11.1.2:invalidTransformation" in COMPLETE_COMPATIBLE_DIAGNOSTICS
    for code in (
        "ix11.10.1.2:invalidTransformation",
        "ix11.11.1.2:invalidTransformation",
    ):
        diag = DiagnosticRecord(severity="warning", code=code)
        assert classify_diagnostic(diag) == "complete_compatible"


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
