"""Extractor fail-closed path when a supported base-set QName cannot be converted."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from edgar.domain.bundle import InstanceReportInput
from edgar.xbrl.config import build_semantic_config
from edgar.xbrl.extract import (
    INVALID_BASE_SET_QNAME,
    SemanticExtractionError,
    _DocumentUriResolver,
    _Extraction,
    _relationship_projection,
    extract_report_extraction,
)
from tests.helpers.linkbase_qnames import PRESENTATION_ARC, PRESENTATION_LINK

_ARCROLE = "http://www.xbrl.org/2003/arcrole/parent-child"
_ROLE = "http://example.com/role/Statement"


class _ArelleQName:
    def __init__(self, namespace_uri: str, local_name: str) -> None:
        self.namespaceURI = namespace_uri
        self.localName = local_name


def _good_link() -> _ArelleQName:
    return _ArelleQName(PRESENTATION_LINK.namespace_uri or "", PRESENTATION_LINK.local_name)


def _good_arc() -> _ArelleQName:
    return _ArelleQName(PRESENTATION_ARC.namespace_uri or "", PRESENTATION_ARC.local_name)


def _bad_qname() -> _ArelleQName:
    return _ArelleQName("http://www.xbrl.org/2003/linkbase", "")


def _extraction() -> _Extraction:
    bound = SimpleNamespace(aliases={}, documents={})
    resolver = _DocumentUriResolver(bound, frozenset())
    return _Extraction(config=build_semantic_config(), resolver=resolver)


def _model(
    *,
    link: _ArelleQName,
    arc: _ArelleQName,
    relationship_set: object | None = None,
) -> SimpleNamespace:
    dummy_rel = SimpleNamespace(
        linkrole=_ROLE,
        arcrole=_ARCROLE,
        arcElement=SimpleNamespace(tag=PRESENTATION_ARC.clark),
    )

    def default_set(*_a: object, **_k: object) -> SimpleNamespace:
        return SimpleNamespace(modelRelationships=[dummy_rel])

    return SimpleNamespace(
        qnameConcepts={},
        contexts={},
        units={},
        facts=(),
        undefinedFacts=(),
        baseSets={(_ARCROLE, _ROLE, link, arc): object()},
        relationshipSet=relationship_set if relationship_set is not None else default_set,
        modelManager=None,
        cntlr=None,
    )


def _assert_invalid_base_set(
    extraction: _Extraction,
    *,
    failed_field: str,
    available_clark: str,
) -> None:
    issues = [issue for issue in extraction.issues if issue.code == INVALID_BASE_SET_QNAME]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == "fatal"
    assert issue.context["arcrole_uri"] == _ARCROLE
    assert issue.context["link_role_uri"] == _ROLE
    assert issue.context["failed_fields"] == [failed_field]
    assert issue.context[failed_field] is None
    other = "arc_qname" if failed_field == "link_qname" else "link_qname"
    assert issue.context[other] == available_clark


def test_invalid_link_qname_is_fatal_and_emits_no_records() -> None:
    extraction = _extraction()
    model = _model(link=_bad_qname(), arc=_good_arc())
    projection = _relationship_projection(model, declared=frozenset(), extraction=extraction)
    assert projection.relationships == ()
    assert projection.labels == ()
    assert projection.references == ()
    _assert_invalid_base_set(
        extraction, failed_field="link_qname", available_clark=PRESENTATION_ARC.clark
    )


def test_invalid_arc_qname_is_fatal_and_emits_no_records() -> None:
    extraction = _extraction()
    model = _model(link=_good_link(), arc=_bad_qname())
    projection = _relationship_projection(model, declared=frozenset(), extraction=extraction)
    assert projection.relationships == ()
    _assert_invalid_base_set(
        extraction, failed_field="arc_qname", available_clark=PRESENTATION_LINK.clark
    )


def test_extract_report_extraction_invalid_link_qname_raises() -> None:
    model = _model(link=_bad_qname(), arc=_good_arc())
    bound = SimpleNamespace(aliases={}, documents={})
    with pytest.raises(SemanticExtractionError, match=INVALID_BASE_SET_QNAME) as caught:
        extract_report_extraction(
            model,
            bound_inputs=bound,
            primary_uris=frozenset(),
            uri_bindings=(),
            report_input=InstanceReportInput(document_uris=("https://example.com/a.xml",)),
        )
    issues = [issue for issue in caught.value.issues if issue.code == INVALID_BASE_SET_QNAME]
    assert issues
    assert issues[0].severity == "fatal"
    assert issues[0].context["failed_fields"] == ["link_qname"]
    assert issues[0].context["arc_qname"] == PRESENTATION_ARC.clark
    assert issues[0].context["link_qname"] is None


def test_extract_report_extraction_invalid_arc_qname_raises() -> None:
    model = _model(link=_good_link(), arc=_bad_qname())
    bound = SimpleNamespace(aliases={}, documents={})
    with pytest.raises(SemanticExtractionError, match=INVALID_BASE_SET_QNAME) as caught:
        extract_report_extraction(
            model,
            bound_inputs=bound,
            primary_uris=frozenset(),
            uri_bindings=(),
            report_input=InstanceReportInput(document_uris=("https://example.com/a.xml",)),
        )
    issues = [issue for issue in caught.value.issues if issue.code == INVALID_BASE_SET_QNAME]
    assert issues[0].context["failed_fields"] == ["arc_qname"]
    assert issues[0].context["link_qname"] == PRESENTATION_LINK.clark
    assert issues[0].context["arc_qname"] is None


def test_invalid_supported_qname_does_not_call_relationship_set() -> None:
    extraction = _extraction()
    calls: list[object] = []

    def boom(*_args: object, **_kwargs: object) -> object:
        calls.append((_args, _kwargs))
        raise RuntimeError("relationshipSet must not be called")

    model = _model(link=_bad_qname(), arc=_good_arc(), relationship_set=boom)
    projection = _relationship_projection(model, declared=frozenset(), extraction=extraction)
    assert calls == []
    assert projection.relationships == ()
    assert projection.labels == ()
    assert projection.references == ()
    assert [issue.code for issue in extraction.issues] == [INVALID_BASE_SET_QNAME]
    _assert_invalid_base_set(
        extraction, failed_field="link_qname", available_clark=PRESENTATION_ARC.clark
    )
