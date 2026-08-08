"""Supported concept-network reconstruction failures are incoherent."""

from __future__ import annotations

from types import SimpleNamespace

from edgar.xbrl.config import build_semantic_config
from edgar.xbrl.extract import (
    ENDPOINT_FAMILY_MISMATCH,
    UNAVAILABLE_ARC_OCCURRENCE,
    _concept_relationship_record,
    _DocumentUriResolver,
    _Extraction,
)
from edgar.xbrl.records import ExpandedQName, SourceLocator


def _extraction() -> _Extraction:
    bound = SimpleNamespace(aliases={}, documents={"https://example.com/a.xml": object()})
    resolver = _DocumentUriResolver(bound, frozenset({"https://example.com/a.xml"}))
    return _Extraction(config=build_semantic_config(), resolver=resolver)


def test_missing_arc_element_is_incoherent_for_concept_network() -> None:
    extraction = _extraction()
    declared = frozenset({ExpandedQName(namespace_uri="http://example.com", local_name="Assets")})
    relationship = SimpleNamespace(arcElement=None)
    assert (
        _concept_relationship_record(
            relationship,
            network_type="presentation",
            arcrole_uri="http://www.xbrl.org/2003/arcrole/parent-child",
            link_role_uri="http://example.com/role",
            declared=declared,
            extraction=extraction,
        )
        is None
    )
    assert extraction.errors
    assert extraction.errors[0].code == UNAVAILABLE_ARC_OCCURRENCE


def test_endpoint_family_mismatch_is_incoherent(monkeypatch) -> None:  # noqa: ANN001
    extraction = _extraction()
    declared = frozenset({ExpandedQName(namespace_uri="http://example.com", local_name="Assets")})
    relationship = SimpleNamespace(
        arcElement=SimpleNamespace(tag="{http://www.xbrl.org/2003/linkbase}presentationArc"),
        fromModelObject=SimpleNamespace(
            qname=ExpandedQName(namespace_uri="http://example.com", local_name="Missing")
        ),
        toModelObject=SimpleNamespace(
            qname=ExpandedQName(namespace_uri="http://example.com", local_name="AlsoMissing")
        ),
        get=lambda *_a, **_k: None,
        orderDecimal=None,
        weightDecimal=None,
    )

    def fake_locator(_model_object, what="element"):  # noqa: ANN001
        return SourceLocator(
            document_uri="https://example.com/a.xml",
            scheme="unqualified_id",
            value="arc1",
        )

    monkeypatch.setattr(extraction, "locator", fake_locator)
    assert (
        _concept_relationship_record(
            relationship,
            network_type="presentation",
            arcrole_uri="http://www.xbrl.org/2003/arcrole/parent-child",
            link_role_uri="http://example.com/role",
            declared=declared,
            extraction=extraction,
        )
        is None
    )
    assert any(issue.code == ENDPOINT_FAMILY_MISMATCH for issue in extraction.errors)
