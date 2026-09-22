"""Same-report integrity checks (M1A-3)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from edgar.xbrl.integrity import ReportIntegrityError, validate_report_extraction
from edgar.xbrl.records import ExpandedQName
from edgar.xbrl.source_records import (
    ConceptDeclarationRecord,
    ConceptRecord,
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
