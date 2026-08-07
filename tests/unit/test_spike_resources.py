"""Unit tests for xbrl-resource-v1 content/occurrence records (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib.resources import (  # noqa: E402
    canonical_label_text,
    resource_content_hash,
    resource_occurrence_hash,
    serialize_resource,
)

DOC_URI = "https://www.sec.gov/Archives/edgar/data/1/x/ex-2023_lab.xml"

LABEL_XML = """<?xml version="1.0"?>
<link:linkbase
    xmlns:link="http://www.xbrl.org/2003/linkbase"
    xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:labelLink xlink:role="http://www.xbrl.org/2003/role/link">
    <link:label id="lab_Assets" xlink:label="conceptAssets" xlink:type="resource"
        xlink:role="http://www.xbrl.org/2003/role/label" xml:lang="en-US">Assets</link:label>
    <link:label id="lab_AssetsTerse" xlink:label="conceptAssetsTerse" xlink:type="resource"
        xlink:role="http://www.xbrl.org/2003/role/terseLabel" xml:lang="en-US">Assets</link:label>
  </link:labelLink>
</link:linkbase>
"""

REFERENCE_XML = """<?xml version="1.0"?>
<link:linkbase
    xmlns:link="http://www.xbrl.org/2003/linkbase"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:ref="http://www.xbrl.org/2006/ref">
  <link:referenceLink xlink:role="http://www.xbrl.org/2003/role/link">
    <link:reference xlink:label="conceptAssetsRef" xlink:type="resource"
        xlink:role="http://www.xbrl.org/2003/role/reference">
      <ref:Name>ASC</ref:Name>
      <ref:Number>210</ref:Number>
      <ref:Paragraph>10</ref:Paragraph>
    </link:reference>
  </link:referenceLink>
</link:linkbase>
"""


def _parse(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode("utf-8"))


def test_label_whitespace_preserved() -> None:
    root = _parse('<label xmlns="http://www.xbrl.org/2003/linkbase">  Padded\n Text </label>')
    assert canonical_label_text(root) == "  Padded\n Text "


def test_content_hash_same_text_different_role_differs() -> None:
    root = _parse(LABEL_XML)
    labels = root.findall(".//{http://www.xbrl.org/2003/linkbase}label")
    rec_a = serialize_resource(labels[0], resource_type="label", canonical_document_uri=DOC_URI)
    rec_b = serialize_resource(labels[1], resource_type="label", canonical_document_uri=DOC_URI)
    assert rec_a["resource_content"]["text"] == rec_b["resource_content"]["text"] == "Assets"
    # Roles differ → content fingerprints differ.
    assert rec_a["resource_content_hash"] != rec_b["resource_content_hash"]


def test_occurrence_hash_same_content_different_locator() -> None:
    root = _parse(LABEL_XML)
    labels = root.findall(".//{http://www.xbrl.org/2003/linkbase}label")
    rec_a = serialize_resource(labels[0], resource_type="label", canonical_document_uri=DOC_URI)
    rec_b = serialize_resource(labels[1], resource_type="label", canonical_document_uri=DOC_URI)
    # Same document, distinct occurrences (distinct unqualified id locators).
    assert rec_a["resource_occurrence_hash"] != rec_b["resource_occurrence_hash"]
    assert rec_a["resource_occurrence"]["locator"] == {
        "kind": "unqualified_id",
        "value": "lab_Assets",
    }


def test_occurrence_hash_changes_with_document_uri() -> None:
    root = _parse(LABEL_XML)
    label = root.findall(".//{http://www.xbrl.org/2003/linkbase}label")[0]
    rec_a = serialize_resource(label, resource_type="label", canonical_document_uri=DOC_URI)
    rec_b = serialize_resource(
        label, resource_type="label", canonical_document_uri="https://example.com/other_lab.xml"
    )
    assert rec_a["resource_content_hash"] == rec_b["resource_content_hash"]
    assert rec_a["resource_occurrence_hash"] != rec_b["resource_occurrence_hash"]


def test_duplicate_id_falls_back_to_expanded_path() -> None:
    xml = """<linkbase xmlns="http://www.xbrl.org/2003/linkbase"
        xmlns:xlink="http://www.w3.org/1999/xlink">
      <labelLink xlink:role="r1">
        <label id="dup" xlink:label="a" xlink:type="resource">One</label>
        <label id="dup" xlink:label="b" xlink:type="resource">Two</label>
      </labelLink>
    </linkbase>"""
    root = _parse(xml)
    labels = root.findall(".//{http://www.xbrl.org/2003/linkbase}label")
    rec_a = serialize_resource(labels[0], resource_type="label", canonical_document_uri=DOC_URI)
    rec_b = serialize_resource(labels[1], resource_type="label", canonical_document_uri=DOC_URI)
    assert rec_a["resource_occurrence"]["locator"]["kind"] == "expanded_element_path"
    assert rec_b["resource_occurrence"]["locator"]["kind"] == "expanded_element_path"
    assert rec_a["resource_occurrence_hash"] != rec_b["resource_occurrence_hash"]


def test_reference_parts_ordered_with_c14n() -> None:
    root = _parse(REFERENCE_XML)
    reference = root.findall(".//{http://www.xbrl.org/2003/linkbase}reference")[0]
    rec = serialize_resource(reference, resource_type="reference", canonical_document_uri=DOC_URI)
    parts = rec["resource_content"]["parts"]
    assert [p["part_ordinal"] for p in parts] == [1, 2, 3]
    assert parts[0]["part_qname"] == "{http://www.xbrl.org/2006/ref}Name"
    assert parts[0]["text"] == "ASC"
    assert all(len(p["part_subtree_c14n_sha256"]) == 64 for p in parts)
    assert all(p["has_structured_markup"] is False for p in parts)


def test_reference_structured_markup_detected() -> None:
    xml = """<reference xmlns="http://www.xbrl.org/2003/linkbase"
        xmlns:xlink="http://www.w3.org/1999/xlink"
        xmlns:ref="http://www.xbrl.org/2006/ref">
      <ref:Subparagraph><b>bold</b>text</ref:Subparagraph>
    </reference>"""
    root = _parse(xml)
    rec = serialize_resource(root, resource_type="reference", canonical_document_uri=DOC_URI)
    part = rec["resource_content"]["parts"][0]
    assert part["has_structured_markup"] is True
    assert part["text"] == "boldtext"


def test_content_fingerprint_is_a_fingerprint_not_semantics() -> None:
    # Identical canonical content ⇒ identical fingerprint; anything else is out
    # of scope for the fingerprint contract.
    root1 = _parse(LABEL_XML)
    root2 = _parse(LABEL_XML)
    label1 = root1.findall(".//{http://www.xbrl.org/2003/linkbase}label")[0]
    label2 = root2.findall(".//{http://www.xbrl.org/2003/linkbase}label")[0]
    h1 = resource_content_hash(
        serialize_resource(label1, resource_type="label", canonical_document_uri=DOC_URI)[
            "resource_content"
        ]
    )
    h2 = resource_content_hash(
        serialize_resource(label2, resource_type="label", canonical_document_uri=DOC_URI)[
            "resource_content"
        ]
    )
    assert h1 == h2
    o1 = resource_occurrence_hash(
        serialize_resource(label1, resource_type="label", canonical_document_uri=DOC_URI)[
            "resource_occurrence"
        ]
    )
    o2 = resource_occurrence_hash(
        serialize_resource(label2, resource_type="label", canonical_document_uri=DOC_URI)[
            "resource_occurrence"
        ]
    )
    assert o1 == o2
