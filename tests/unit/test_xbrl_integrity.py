"""Same-report integrity checks (M1A-3)."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from edgar.xbrl.integrity import ReportIntegrityError, validate_report_extraction
from edgar.xbrl.records import ExpandedQName
from edgar.xbrl.source_records import (
    ConceptDeclarationRecord,
    ConceptRecord,
    ContextDimensionRecord,
    ContextRecord,
    FactRecord,
    ReportExtraction,
)


def _minimal_report() -> ReportExtraction:
    concept = ExpandedQName(namespace_uri="http://example.com/t", local_name="Assets")
    decl = ConceptDeclarationRecord(concept=concept, period_type="instant")
    ctx = ContextRecord(
        source_context_id="c1",
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier="1",
        period_kind="instant",
        period_instant="2024-12-31",
    )
    fact = FactRecord(
        concept=concept,
        source_context_id="c1",
        source_unit_id=None,
        value_status="valid",
        raw_lexical_value="1",
        is_nil=False,
        source_order=0,
    )
    return ReportExtraction(
        report_key="a" * 64,
        report_input={"kind": "instance", "document_uris": ["https://example.com/a.xml"]},
        extractor_version="source-extract-v5",
        arelle_version="test",
        arelle_item_fact_count=1,
        concepts=(
            ConceptRecord(
                namespace_uri=concept.namespace_uri,
                local_name=concept.local_name,
            ),
        ),
        declarations=(decl,),
        contexts=(ctx,),
        facts=(fact,),
    )


def test_validate_report_extraction_accepts_minimal() -> None:
    validate_report_extraction(_minimal_report())


def test_fact_unknown_context_rejected() -> None:
    report = _minimal_report()
    bad = replace(
        report,
        facts=(
            FactRecord(
                concept=report.facts[0].concept,
                source_context_id="missing",
                source_unit_id=None,
                value_status="valid",
                raw_lexical_value="1",
                is_nil=False,
                source_order=0,
            ),
        ),
    )
    with pytest.raises(ReportIntegrityError, match="unknown context"):
        validate_report_extraction(bad)


def test_typed_member_requires_xml_and_digest() -> None:
    report = _minimal_report()
    concept = ExpandedQName(namespace_uri="http://example.com/t", local_name="Dim")
    member = ExpandedQName(namespace_uri="http://example.com/t", local_name="Member")
    decls = (
        *report.declarations,
        ConceptDeclarationRecord(concept=concept, period_type="instant"),
        ConceptDeclarationRecord(concept=member, period_type="instant"),
    )
    dim = ContextDimensionRecord(
        source_context_id="c1",
        dimension=concept,
        context_element="segment",
        member_kind="typed",
        typed_member={},
    )
    bad = replace(report, declarations=decls, dimensions=(dim,))
    with pytest.raises(ReportIntegrityError, match="typed_member"):
        validate_report_extraction(bad)


def test_typed_member_malformed_xml_rejected() -> None:
    report = _minimal_report()
    concept = ExpandedQName(namespace_uri="http://example.com/t", local_name="Dim")
    decls = (
        *report.declarations,
        ConceptDeclarationRecord(concept=concept, period_type="instant"),
    )
    dim = ContextDimensionRecord(
        source_context_id="c1",
        dimension=concept,
        context_element="segment",
        member_kind="typed",
        typed_member={"xml": "<unclosed", "sha256": "00"},
    )
    bad = replace(report, declarations=decls, dimensions=(dim,))
    with pytest.raises(ReportIntegrityError, match="well-formed"):
        validate_report_extraction(bad)


def _typed_dim_report(xml: str, digest: str) -> ReportExtraction:
    report = _minimal_report()
    concept = ExpandedQName(namespace_uri="http://example.com/t", local_name="Dim")
    decls = (
        *report.declarations,
        ConceptDeclarationRecord(concept=concept, period_type="instant"),
    )
    dim = ContextDimensionRecord(
        source_context_id="c1",
        dimension=concept,
        context_element="segment",
        member_kind="typed",
        typed_member={"xml": xml, "sha256": digest},
    )
    return replace(report, declarations=decls, dimensions=(dim,))


def test_typed_member_namespace_complete_xml_accepted() -> None:
    xml = '<p:member xmlns:p="http://example.com/t"/>'
    digest = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    validate_report_extraction(_typed_dim_report(xml, digest))


def test_typed_member_undeclared_prefix_rejected() -> None:
    xml = "<p:member/>"
    digest = hashlib.sha256(xml.encode("utf-8")).hexdigest()
    with pytest.raises(ReportIntegrityError, match="well-formed"):
        validate_report_extraction(_typed_dim_report(xml, digest))


def test_typed_member_digest_mismatch_rejected() -> None:
    xml = '<p:member xmlns:p="http://example.com/t"/>'
    with pytest.raises(ReportIntegrityError, match="digest mismatch"):
        validate_report_extraction(_typed_dim_report(xml, "0" * 64))
