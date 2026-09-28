"""Regression tests for source-extract-v6 declaration keep-set grain."""

from __future__ import annotations

from types import SimpleNamespace

import lxml.etree as etree

from edgar.xbrl.config import build_semantic_config
from edgar.xbrl.extract import (
    INCOHERENT_CONCEPT_DECLARATION,
    _compute_base_concepts,
    _concept_declarations,
    _DocumentUriResolver,
    _Extraction,
    _issuer_extension_concepts,
    _scan_dts_concept_identities,
)
from edgar.xbrl.records import ExpandedQName, FactRecord, SourceLocator
from edgar.xbrl.source_records import ContextDimensionRecord

_DOC = "https://example.com/taxonomy.xsd"
_US_GAAP = "http://fasb.org/us-gaap/2023"
_ISSUER = "http://issuer.example.com/2024"
_XBRL_US_2009 = "http://xbrl.us/us-gaap/2009-01-31"
_CYD = "http://xbrl.sec.gov/cyd/2026"


class _ArelleQName:
    def __init__(self, namespace_uri: str, local_name: str) -> None:
        self.namespaceURI = namespace_uri
        self.localName = local_name


def _qname(ns: str, local: str) -> ExpandedQName:
    return ExpandedQName(namespace_uri=ns, local_name=local)


def _extraction() -> _Extraction:
    bound = SimpleNamespace(
        aliases={},
        documents={_DOC: object()},
    )
    resolver = _DocumentUriResolver(bound, frozenset({_DOC}))
    return _Extraction(config=build_semantic_config(), resolver=resolver)


class _ModelConcept:
    """Minimal Arelle-like concept wrapper around an lxml element."""

    def __init__(self, element: etree._Element, identity: ExpandedQName) -> None:
        self._element = element
        self.qname = _ArelleQName(identity.namespace_uri, identity.local_name)
        self.modelDocument = SimpleNamespace(uri=_DOC)
        self.periodType = "instant"
        self.typeQname = None
        self.substitutionGroupQname = None
        self.isAbstract = False
        self.isNillable = True

    def getroottree(self) -> etree._ElementTree:
        return self._element.getroottree()

    def get(self, key: str, default: object | None = None) -> object | None:
        return self._element.get(key, default)


def _concept_element(element_id: str, identity: ExpandedQName) -> _ModelConcept:
    root = etree.fromstring(
        (
            f'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
            f'<xs:element id="{element_id}"/>'
            f"</xs:schema>"
        ).encode()
    )
    return _ModelConcept(root[0], identity)


def _grain_model() -> SimpleNamespace:
    used_standard = _qname(_US_GAAP, "UsedStandard")
    unused_standard = _qname(_US_GAAP, "UnusedStandard")
    unused_issuer = _qname(_ISSUER, "UnusedExtension")
    unused_2009 = _qname(_XBRL_US_2009, "UnusedLegacyStandard")
    unused_cyd = _qname(_CYD, "UnusedCyd")
    dim_axis = _qname(_US_GAAP, "ProductAxis")
    dim_member = _qname(_US_GAAP, "ProductMember")

    concepts = {
        used_standard: _concept_element("used", used_standard),
        unused_standard: _concept_element("unused_std", unused_standard),
        unused_issuer: _concept_element("unused_iss", unused_issuer),
        unused_2009: _concept_element("unused_2009", unused_2009),
        unused_cyd: _concept_element("unused_cyd", unused_cyd),
        dim_axis: _concept_element("dim_axis", dim_axis),
        dim_member: _concept_element("dim_member", dim_member),
    }
    return SimpleNamespace(qnameConcepts={key: value for key, value in concepts.items()})


def test_v6_declaration_keep_set() -> None:
    model = _grain_model()
    extraction = _extraction()
    _scan_dts_concept_identities(model, extraction)

    used_standard = _qname(_US_GAAP, "UsedStandard")
    dim_axis = _qname(_US_GAAP, "ProductAxis")
    dim_member = _qname(_US_GAAP, "ProductMember")
    locator = SourceLocator(document_uri=_DOC, scheme="unqualified_id", value="ctx")
    fact = FactRecord(
        concept_qname=used_standard,
        context_locator=locator,
        source_locator=locator,
        value_status="valid",
        resolved_text_value="1",
    )
    dimensions = (
        ContextDimensionRecord(
            source_context_id="c1",
            dimension=dim_axis,
            context_element="segment",
            member_kind="explicit",
            member=dim_member,
        ),
    )
    issuer_extensions = _issuer_extension_concepts(model)
    base = _compute_base_concepts(
        ordered_facts=((0, fact),),
        relationships=(),
        dimensions=dimensions,
        issuer_extensions=issuer_extensions,
    )
    declarations = _concept_declarations(model, extraction, keep=base)
    retained = {record.concept.clark for record in declarations}

    assert f"{{{_US_GAAP}}}UsedStandard" in retained
    assert f"{{{_US_GAAP}}}ProductAxis" in retained
    assert f"{{{_US_GAAP}}}ProductMember" in retained
    assert f"{{{_ISSUER}}}UnusedExtension" in retained
    assert f"{{{_US_GAAP}}}UnusedStandard" not in retained
    assert f"{{{_XBRL_US_2009}}}UnusedLegacyStandard" not in retained
    assert f"{{{_CYD}}}UnusedCyd" not in retained


def test_incoherent_concept_declaration_reported_once() -> None:
    model = SimpleNamespace(qnameConcepts={"bad-key": SimpleNamespace(qname=None)})
    extraction = _extraction()
    _scan_dts_concept_identities(model, extraction)
    _concept_declarations(model, extraction, keep=frozenset())
    fatal = [
        issue
        for issue in extraction.issues
        if issue.code == INCOHERENT_CONCEPT_DECLARATION and issue.severity == "fatal"
    ]
    assert len(fatal) == 1
