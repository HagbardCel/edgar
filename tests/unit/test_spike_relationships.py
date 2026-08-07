"""Unit tests for xbrl-relationship-v1 occurrence identities (no network)."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from lxml import etree

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from arelle.ModelValue import QName as ModelQName  # noqa: E402
from spike_lib.relationships import (  # noqa: E402
    CALCULATION_ARCROLE,
    CONCEPT_LABEL_ARCROLE,
    DEFINITION_ARCROLES,
    FOOTNOTE_ARCROLE,
    PRESENTATION_ARCROLE,
    arc_occurrence_hash,
    arc_occurrence_record,
    classify_network,
    collect_relationships,
    endpoint_occurrence_identity,
    relationship_occurrence_hash,
)

LINK_NS = "http://www.xbrl.org/2003/linkbase"
XLINK_NS = "http://www.w3.org/1999/xlink"
EX_NS = "http://example.com/taxonomy"
DOC_URI = "https://www.sec.gov/Archives/edgar/data/1/x/ex-2023_lab.xml"

LINKBASE_XML = f"""<?xml version="1.0"?>
<linkbase xmlns="{LINK_NS}" xmlns:xlink="{XLINK_NS}">
  <labelLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">
    <loc xlink:type="locator" xlink:label="concept1" xlink:href="ex.xsd#ex_Assets"/>
    <loc xlink:type="locator" xlink:label="concept1b" xlink:href="ex.xsd#ex_Assets"/>
    <label xlink:type="resource" xlink:label="label1"
        xlink:role="http://www.xbrl.org/2003/role/label" xml:lang="en">Assets</label>
    <labelArc xlink:type="arc" xlink:arcrole="{CONCEPT_LABEL_ARCROLE}"
        xlink:from="concept1" xlink:to="label1" order="1"/>
    <labelArc xlink:type="arc" xlink:arcrole="{CONCEPT_LABEL_ARCROLE}"
        xlink:from="concept1b" xlink:to="label1" order="1"/>
  </labelLink>
</linkbase>
"""


class FakeElement(etree.ElementBase):
    @property
    def localName(self) -> str:
        return etree.QName(self.tag).localname

    @property
    def namespaceURI(self) -> str:
        return etree.QName(self.tag).namespace


class FakeConcept:
    def __init__(self, namespace: str, local: str) -> None:
        self.qname = ModelQName(None, namespace, local)


def _parse_linkbase() -> etree._Element:
    lookup = etree.ElementDefaultClassLookup(element=FakeElement)
    parser = etree.XMLParser()
    parser.set_element_class_lookup(lookup)
    return etree.fromstring(LINKBASE_XML.encode("utf-8"), parser)


@pytest.fixture()
def model_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arelle.ModelDtsObject.ModelConcept", FakeConcept)
    monkeypatch.setattr("arelle.ModelDtsObject.ModelResource", FakeElement)


@pytest.fixture()
def linkbase() -> dict[str, object]:
    root = _parse_linkbase()
    doc = SimpleNamespace(uri=DOC_URI, filepath=None)
    # lxml element proxies are ephemeral: keep references to the exact proxy
    # objects on which modelDocument is set, or the attribute is lost.
    elements = list(root.iter())
    for element in elements:
        element.modelDocument = doc  # type: ignore[attr-defined]
    locs = [e for e in elements if e.tag == f"{{{LINK_NS}}}loc"]
    labels = [e for e in elements if e.tag == f"{{{LINK_NS}}}label"]
    arcs = [e for e in elements if e.tag == f"{{{LINK_NS}}}labelArc"]
    return {
        "root": root,
        "doc": doc,
        "elements": elements,
        "locs": locs,
        "labels": labels,
        "arcs": arcs,
    }


def _resolver(doc: object) -> str | None:
    return {DOC_URI: DOC_URI}.get(getattr(doc, "uri", ""))


def test_classify_network_registry() -> None:
    assert classify_network(PRESENTATION_ARCROLE, link_clark=None) == "presentation"
    assert classify_network(CALCULATION_ARCROLE, link_clark=None) == "calculation"
    for arcrole in DEFINITION_ARCROLES:
        assert classify_network(arcrole, link_clark=None) == "definition"
    assert classify_network(CONCEPT_LABEL_ARCROLE, link_clark=None) == "resource"
    assert classify_network(FOOTNOTE_ARCROLE, link_clark=None) == "excluded"
    # Custom definition arcrole supported via definition-link topology.
    assert (
        classify_network(
            "http://example.com/arcrole/custom",
            link_clark="{http://www.xbrl.org/2003/linkbase}definitionLink",
        )
        == "definition"
    )
    assert classify_network("http://example.com/arcrole/other", link_clark=None) == "unsupported"


def test_arc_occurrence_identity(model_patches: None, linkbase: dict[str, object]) -> None:
    arcs = linkbase["arcs"]
    rec1 = arc_occurrence_record(arcs[0], canonical_document_uri=DOC_URI)  # type: ignore[index]
    rec2 = arc_occurrence_record(arcs[1], canonical_document_uri=DOC_URI)  # type: ignore[index]
    assert arc_occurrence_hash(rec1) != arc_occurrence_hash(rec2)
    assert rec1["arc_document_uri"] == DOC_URI
    assert rec1["arc_locator"]["kind"] in ("unqualified_id", "expanded_element_path")


def test_locator_backed_concept_endpoint_identity(
    model_patches: None, linkbase: dict[str, object]
) -> None:
    locs = linkbase["locs"]
    concept = FakeConcept(EX_NS, "Assets")
    identity1, resolved1, stable1, fail1 = endpoint_occurrence_identity(
        concept,
        locs[0],
        canonical_doc_uri=_resolver,  # type: ignore[index]
    )
    identity2, resolved2, stable2, fail2 = endpoint_occurrence_identity(
        concept,
        locs[1],
        canonical_doc_uri=_resolver,  # type: ignore[index]
    )
    assert stable1 and stable2
    assert fail1 is None and fail2 is None
    assert identity1 is not None and identity2 is not None
    assert identity1["endpoint_kind"] == "locator"
    assert resolved1 == {
        "kind": "concept",
        "expanded_qname": f"{{{EX_NS}}}Assets",
    }
    assert resolved1 == resolved2
    # Same resolved concept, distinct locator occurrences → distinct traversals.
    assert identity1 != identity2
    # Provenance / resolved semantics are outside occurrence identity.
    assert "resolved_object" not in identity1
    assert "provenance" not in identity1.get("endpoint_occurrence", {})


def test_local_resource_endpoint_identity(model_patches: None, linkbase: dict[str, object]) -> None:
    labels = linkbase["labels"]
    identity, resolved, stable, fail = endpoint_occurrence_identity(
        labels[0],
        None,
        canonical_doc_uri=_resolver,  # type: ignore[index]
    )
    assert stable
    assert fail is None
    assert identity is not None
    assert identity["endpoint_kind"] == "local_resource"
    assert len(identity["endpoint_occurrence_hash"]) == 64
    assert resolved is not None
    assert resolved["kind"] == "resource"


def test_direct_concept_endpoint_is_extraction_incomplete(
    model_patches: None,
) -> None:
    concept = FakeConcept(EX_NS, "Assets")
    identity, resolved, stable, fail = endpoint_occurrence_identity(
        concept,
        None,
        canonical_doc_uri=_resolver,
    )
    assert not stable
    assert identity is None
    assert fail == "DIRECT_ENDPOINT_UNIDENTIFIABLE"
    assert resolved == {"kind": "concept", "expanded_qname": f"{{{EX_NS}}}Assets"}


def test_relationship_occurrence_hash_endpoint_aware(model_patches: None) -> None:
    arc_hash = "a" * 64
    src = "s" * 64
    dst1 = "b" * 64
    dst2 = "c" * 64
    assert relationship_occurrence_hash(arc_hash, src, dst1) != relationship_occurrence_hash(
        arc_hash, src, dst2
    )


def _make_rel(arc, doc, frm, to, from_loc, to_loc, order="1") -> SimpleNamespace:
    return SimpleNamespace(
        arcElement=arc,
        modelDocument=doc,
        fromModelObject=frm,
        toModelObject=to,
        fromLocator=from_loc,
        toLocator=to_loc,
        order=Decimal(order),
        weight=None,
        preferredLabel=None,
        targetRole=None,
        closed=None,
        usable=None,
        contextElement=None,
    )


def test_collect_relationships_exact_base_set_multiplicity(
    model_patches: None, linkbase: dict[str, object]
) -> None:
    locs = linkbase["locs"]
    labels = linkbase["labels"]
    arcs = linkbase["arcs"]
    doc = linkbase["doc"]
    concept = FakeConcept(EX_NS, "Assets")

    rel1 = _make_rel(arcs[0], doc, concept, labels[0], locs[0], None)  # type: ignore[index]
    rel2 = _make_rel(arcs[1], doc, concept, labels[0], locs[1], None)  # type: ignore[index]

    link_qn = ModelQName("link", LINK_NS, "labelLink")
    arc_qn = ModelQName("link", LINK_NS, "labelArc")
    linkrole = "http://www.xbrl.org/2003/role/link"

    class FakeRelSet:
        def __init__(self, rels: list[object]) -> None:
            self.modelRelationships = rels

    class FakeModelXbrl:
        # Aggregate keys present alongside exact keys must not double-count.
        baseSets = {
            (CONCEPT_LABEL_ARCROLE, linkrole, link_qn, arc_qn): ["link"],
            (CONCEPT_LABEL_ARCROLE, linkrole, None, None): ["link"],
            (CONCEPT_LABEL_ARCROLE, None, None, None): ["link"],
        }

        def relationshipSet(
            self, arcrole, linkrole=None, linkqname=None, arcqname=None, includeProhibits=False
        ):  # type: ignore[no-untyped-def]
            if linkqname is link_qn and arcqname is arc_qn:
                return FakeRelSet([rel1, rel2])
            # Aggregate call would double-count; flag if used for enumeration.
            raise AssertionError("aggregate relationshipSet used for enumeration")

    result = collect_relationships(FakeModelXbrl(), canonical_doc_uri=_resolver)
    assert result["resource_relationship_counts"]["concept_label"] == 2
    assert len(result["resource_records"]) == 2
    hashes = {r["relationship_occurrence_hash"] for r in result["resource_records"]}
    assert len(hashes) == 2
    for record in result["resource_records"]:
        assert record["source_concept"] == f"{{{EX_NS}}}Assets"
        assert record["resource_content_hash"] is not None
        assert (
            record["canonical_record"]["resource_content_hash"] == record["resource_content_hash"]
        )
        assert record["target_endpoint_occurrence_identity"]["endpoint_kind"] == "local_resource"
        assert "source_line" not in record["canonical_record"]
    assert result["extraction"]["extraction_complete"] is True


def test_source_line_does_not_affect_occurrence_or_collection_hash(
    model_patches: None, linkbase: dict[str, object]
) -> None:
    from spike_lib.arelle_load import occurrence_collection_hash
    from spike_lib.locators import occurrence_provenance

    arcs = linkbase["arcs"]
    rec = arc_occurrence_record(arcs[0], canonical_document_uri=DOC_URI)  # type: ignore[index]
    h1 = arc_occurrence_hash(rec)
    # Provenance is outside the occurrence record.
    assert "arc_provenance" not in rec
    provenance = occurrence_provenance(arcs[0])  # type: ignore[index]
    assert h1 == arc_occurrence_hash(rec)
    # Collection hash uses canonical_record only.
    canonical = {
        "relationship_occurrence_hash": "a" * 64,
        "network_type": "resource",
        "arcrole_uri": CONCEPT_LABEL_ARCROLE,
        "link_role_uri": None,
        "arc_occurrence_hash": h1,
        "source_endpoint_occurrence_identity": None,
        "target_endpoint_occurrence_identity": None,
        "source_semantic_identity": None,
        "target_semantic_identity": None,
        "order": "1",
        "resource_relationship_kind": "concept_label",
        "source_concept": f"{{{EX_NS}}}Assets",
        "resource_occurrence_hash": "b" * 64,
        "resource_content_hash": "c" * 64,
    }
    records_a = [{"canonical_record": canonical, "diagnostic_provenance": provenance}]
    records_b = [
        {
            "canonical_record": canonical,
            "diagnostic_provenance": {**provenance, "source_line": 99999},
        }
    ]
    assert occurrence_collection_hash(records_a) == occurrence_collection_hash(records_b)


def test_deferred_generic_resource_arcroles() -> None:
    from spike_lib.relationships import DEFERRED_GENERIC_RESOURCE_ARCROLES

    assert (
        frozenset(
            {
                "http://xbrl.org/arcrole/2008/element-label",
                "http://xbrl.org/arcrole/2008/element-reference",
            }
        )
        == DEFERRED_GENERIC_RESOURCE_ARCROLES
    )
    assert (
        classify_network(
            "http://xbrl.org/arcrole/2008/element-label",
            link_clark=None,
        )
        == "deferred"
    )


def test_collect_relationships_unsupported_and_excluded(model_patches: None) -> None:
    link_qn = ModelQName("link", LINK_NS, "labelLink")
    arc_qn = ModelQName("link", LINK_NS, "labelArc")
    linkrole = "http://www.xbrl.org/2003/role/link"
    custom_arcrole = "http://example.com/arcrole/unknown"

    class FakeRelSet:
        def __init__(self, rels: list[object]) -> None:
            self.modelRelationships = rels

    class FakeModelXbrl:
        baseSets = {
            (FOOTNOTE_ARCROLE, linkrole, link_qn, arc_qn): ["link"],
            (custom_arcrole, linkrole, link_qn, arc_qn): ["link"],
        }

        def relationshipSet(
            self, arcrole, linkrole=None, linkqname=None, arcqname=None, includeProhibits=False
        ):  # type: ignore[no-untyped-def]
            return FakeRelSet([object()])

    result = collect_relationships(FakeModelXbrl(), canonical_doc_uri=_resolver)
    inventory = result["unsupported_inventory"]
    assert inventory["excluded_arcrole_counts"] == {FOOTNOTE_ARCROLE: 1}
    assert inventory["unsupported_arcrole_counts"] == {custom_arcrole: 1}
    assert result["extraction"]["extraction_complete"] is False
    assert result["extraction"]["unsupported_failing_relationship_count"] == 1


def test_collect_relationships_definition_custom_arcrole(
    model_patches: None, linkbase: dict[str, object]
) -> None:
    locs = linkbase["locs"]
    arcs = linkbase["arcs"]
    doc = linkbase["doc"]
    concept_a = FakeConcept(EX_NS, "Assets")
    concept_b = FakeConcept(EX_NS, "Liabilities")

    rel = _make_rel(arcs[0], doc, concept_a, concept_b, locs[0], locs[1])  # type: ignore[index]

    link_qn = ModelQName("link", LINK_NS, "definitionLink")
    arc_qn = ModelQName("link", LINK_NS, "definitionArc")
    linkrole = "http://www.xbrl.org/2003/role/link"
    custom_def_arcrole = "http://example.com/arcrole/custom-def"

    class FakeRelSet:
        def __init__(self, rels: list[object]) -> None:
            self.modelRelationships = rels

    class FakeModelXbrl:
        baseSets = {(custom_def_arcrole, linkrole, link_qn, arc_qn): ["link"]}

        def relationshipSet(
            self, arcrole, linkrole=None, linkqname=None, arcqname=None, includeProhibits=False
        ):  # type: ignore[no-untyped-def]
            return FakeRelSet([rel])

    result = collect_relationships(FakeModelXbrl(), canonical_doc_uri=_resolver)
    assert result["relationship_counts"]["definition"] == 1
    record = result["concept_records"][0]
    assert record["arcrole_uri"] == custom_def_arcrole
    assert record["source_concept"] == f"{{{EX_NS}}}Assets"
    assert record["target_concept"] == f"{{{EX_NS}}}Liabilities"
