"""Unit tests for extraction config, locators, and diagnostics."""

from __future__ import annotations

import time

import lxml.etree as etree

from edgar.xbrl.config import FACT_LEXICAL_VERSION, build_semantic_config
from edgar.xbrl.diagnostics import COMPLETE_COMPATIBLE_DIAGNOSTICS, classify_diagnostic
from edgar.xbrl.locators import element_locator, id_index
from edgar.xbrl.records import DiagnosticRecord, ExpandedQName

_DOC = "https://example.com/doc.xml"
_XML_NS = "http://www.w3.org/XML/1998/namespace"


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
    loc = element_locator(root[0], document_uri=_DOC)
    assert loc.scheme == "expanded_element_path"


def test_locator_index_matches_xpath_without_index() -> None:
    root = etree.fromstring(
        b"""<x xmlns:xml="http://www.w3.org/XML/1998/namespace">
              <a xml:id="c1"/><b id="only"/><c id="dup"/><d id="dup"/>
            </x>"""
    )
    index = id_index(root)
    for child in root:
        without = element_locator(child, document_uri=_DOC)
        with_index = element_locator(child, document_uri=_DOC, index=index)
        assert without == with_index


def test_locator_many_unique_plain_ids() -> None:
    parts = "".join(f'<e id="id{i}"/>' for i in range(200))
    root = etree.fromstring(f"<x>{parts}</x>".encode())
    index = id_index(root)
    for i, child in enumerate(root):
        loc = element_locator(child, document_uri=_DOC, index=index)
        assert loc.scheme == "unqualified_id"
        assert loc.value == f"id{i}"


def test_locator_precedence_table() -> None:
    root = etree.fromstring(
        f"""<doc xmlns:xml="{_XML_NS}">
          <uniqueXml xml:id="ux"/>
          <uniquePlain id="up"/>
          <both xml:id="bx" id="bi"/>
          <emptyPlain id=""/>
          <nested><item/><item id="leaf"/></nested>
        </doc>""".encode()
    )
    dup_xml1 = etree.SubElement(root, "dupXml1")
    dup_xml1.set(f"{{{_XML_NS}}}id", "dx")
    dup_xml1.set("id", "fallback")
    dup_xml2 = etree.SubElement(root, "dupXml2")
    dup_xml2.set(f"{{{_XML_NS}}}id", "dx")
    dup_both1 = etree.SubElement(root, "dupBoth1")
    dup_both1.set(f"{{{_XML_NS}}}id", "db")
    dup_both1.set("id", "same")
    dup_both2 = etree.SubElement(root, "dupBoth2")
    dup_both2.set(f"{{{_XML_NS}}}id", "db")
    dup_both2.set("id", "same")

    index = id_index(root)
    by_local = {etree.QName(child).localname: child for child in root if isinstance(child.tag, str)}

    loc = element_locator(by_local["uniqueXml"], document_uri=_DOC, index=index)
    assert loc.scheme == "xml_id" and loc.value == "ux"

    loc = element_locator(by_local["uniquePlain"], document_uri=_DOC, index=index)
    assert loc.scheme == "unqualified_id" and loc.value == "up"

    loc = element_locator(by_local["both"], document_uri=_DOC, index=index)
    assert loc.scheme == "xml_id" and loc.value == "bx"

    loc = element_locator(dup_xml1, document_uri=_DOC, index=index)
    assert loc.scheme == "unqualified_id" and loc.value == "fallback"

    loc = element_locator(dup_both1, document_uri=_DOC, index=index)
    assert loc.scheme == "expanded_element_path"

    loc = element_locator(by_local["emptyPlain"], document_uri=_DOC, index=index)
    assert loc.scheme == "expanded_element_path"

    loc_root = element_locator(root, document_uri=_DOC, index=index)
    assert loc_root.scheme == "expanded_element_path"

    nested = by_local["nested"]
    nested_items = [c for c in nested if isinstance(c.tag, str)]
    assert len(nested_items) == 2
    loc0 = element_locator(nested_items[0], document_uri=_DOC, index=index)
    loc1 = element_locator(nested_items[1], document_uri=_DOC, index=index)
    assert loc0.scheme == "expanded_element_path"
    assert loc1.scheme == "unqualified_id" and loc1.value == "leaf"


def test_locator_rejects_index_for_wrong_root() -> None:
    root_a = etree.fromstring(b"<a><x id='1'/></a>")
    root_b = etree.fromstring(b"<b><y id='1'/></b>")
    wrong_index = id_index(root_a)
    try:
        element_locator(root_b[0], document_uri=_DOC, index=wrong_index)
    except Exception as exc:
        assert "different document root" in str(exc)
    else:
        raise AssertionError("expected LocatorError for mismatched IdIndex")


def test_locator_index_performance_smoke() -> None:
    parts = "".join(f'<e id="id{i}"/>' for i in range(1000))
    root = etree.fromstring(f"<x>{parts}</x>".encode())
    index = id_index(root)
    start = time.perf_counter()
    for child in root:
        element_locator(child, document_uri=_DOC, index=index)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0
