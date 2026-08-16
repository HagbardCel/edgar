"""Unit/contract tests for Phase 2B source extraction adapt + extract_filing."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    InstanceReportInput,
    UriBinding,
)
from edgar.domain.payload import compute_payload_hash
from edgar.domain.report_key import report_key
from edgar.storage.objects import ObjectStore
from edgar.xbrl.records import (
    ConceptDeclarationRecord as Phase1Declaration,
)
from edgar.xbrl.records import (
    ConceptReferenceRecord as Phase1Reference,
)
from edgar.xbrl.records import (
    ContextRecord as Phase1Context,
)
from edgar.xbrl.records import (
    ExpandedQName,
    SemanticProjectionData,
    SourceLocator,
)
from edgar.xbrl.records import (
    FactRecord as Phase1Fact,
)
from edgar.xbrl.records import (
    ReferencePartRecord as Phase1ReferencePart,
)
from edgar.xbrl.records import (
    UnitRecord as Phase1Unit,
)
from edgar.xbrl.source_adapt import SourceAdaptError, adapt_report_extraction
from edgar.xbrl.source_extract import extract_filing
from edgar.xbrl.source_records import EXTRACTOR_VERSION, FilingExtraction
from tests.helpers.xbrl_bundles import (
    INSTANCE,
    INSTANCE_URI,
    make_invalid_transform_bundle,
    make_minimal_semantic_bundle,
    make_rich_semantic_bundle,
)


def _loc(document_uri: str, value: str) -> SourceLocator:
    return SourceLocator(document_uri=document_uri, scheme="unqualified_id", value=value)


def _synthetic_projection() -> SemanticProjectionData:
    concept = ExpandedQName(namespace_uri="http://example.com/test", local_name="Assets")
    other = ExpandedQName(namespace_uri="http://example.com/test", local_name="Note")
    inst = "https://example.com/a.xml"
    schema = "https://example.com/t.xsd"
    ctx_loc = _loc(inst, "c1")
    unit_loc = _loc(inst, "u1")
    return SemanticProjectionData(
        projection_version="arelle-semantic-v2",
        config_fingerprint="a" * 64,
        engine_name="arelle",
        engine_version="9.9.9",
        concept_declarations=(
            Phase1Declaration(concept=concept, source_locator=_loc(schema, "Assets")),
            Phase1Declaration(concept=other, source_locator=_loc(schema, "Note")),
        ),
        concept_references=(
            Phase1Reference(
                concept=concept,
                link_role_uri="http://example.com/role",
                arcrole_uri="http://www.xbrl.org/2003/arcrole/concept-reference",
                source_locator=_loc(schema, "ref1"),
                arc_locator=_loc(schema, "arc1"),
                resource_role_uri="http://www.xbrl.org/2003/role/reference",
                reference_parts=(
                    Phase1ReferencePart(
                        namespace_uri="http://www.xbrl.org/2003/ref",
                        local_name="Publisher",
                        text="FASB",
                        xml="<ref:Publisher xmlns:ref='http://www.xbrl.org/2003/ref'>FASB</ref:Publisher>",
                    ),
                ),
            ),
        ),
        contexts=(
            Phase1Context(
                source_context_id="c1",
                entity_scheme="http://www.sec.gov/CIK",
                entity_identifier="0000000001",
                period_kind="instant",
                source_locator=ctx_loc,
                period_instant="2024-12-31",
            ),
        ),
        units=(Phase1Unit(source_unit_id="u1", source_locator=unit_loc, divide=False),),
        facts=(
            Phase1Fact(
                concept_qname=concept,
                context_locator=ctx_loc,
                source_locator=_loc(inst, "f1"),
                value_status="valid",
                unit_locator=unit_loc,
                raw_lexical_value="100.50",
                resolved_numeric_value=Decimal("100.50"),
                resolved_value_kind="numeric",
                reported_decimals="INF",
            ),
            Phase1Fact(
                concept_qname=concept,
                context_locator=ctx_loc,
                source_locator=_loc(inst, "f2"),
                value_status="valid",
                unit_locator=unit_loc,
                raw_lexical_value="100.50",
                resolved_numeric_value=Decimal("100.50"),
                resolved_value_kind="numeric",
                reported_decimals="INF",
            ),
            Phase1Fact(
                concept_qname=other,
                context_locator=ctx_loc,
                source_locator=_loc(inst, "fnil"),
                value_status="nil",
                is_nil=True,
            ),
            Phase1Fact(
                concept_qname=other,
                context_locator=ctx_loc,
                source_locator=_loc(inst, "finvalid"),
                value_status="invalid",
                raw_lexical_value="not-a-number",
            ),
        ),
    )


def _bindings_for_synthetic() -> tuple[UriBinding, ...]:
    return (
        UriBinding(
            document_uri="https://example.com/a.xml",
            artifact_path="accession/a.xml",
            content_sha256="a" * 64,
        ),
        UriBinding(
            document_uri="https://example.com/t.xsd",
            artifact_path="external/schema.xsd",
            content_sha256="b" * 64,
        ),
    )


def test_adapt_preserves_concept_qname_and_decimal() -> None:
    report_input = InstanceReportInput(document_uris=("https://example.com/a.xml",))
    report = adapt_report_extraction(
        _synthetic_projection(),
        report_input,
        uri_bindings=_bindings_for_synthetic(),
    )
    assert report.extractor_version == EXTRACTOR_VERSION
    assert report.report_key == report_key(report_input)
    assets = next(c for c in report.concepts if c.local_name == "Assets")
    assert assets.namespace_uri == "http://example.com/test"
    numeric = next(f for f in report.facts if f.source_xml_id == "f1")
    assert numeric.resolved_numeric == Decimal("100.50")
    assert isinstance(numeric.resolved_numeric, Decimal)
    assert numeric.source_document_relative_path == "accession/a.xml"
    assert numeric.source_context_id == "c1"
    assert numeric.source_unit_id == "u1"


def test_adapt_retains_nil_invalid_and_duplicate_occurrences() -> None:
    report = adapt_report_extraction(
        _synthetic_projection(),
        InstanceReportInput(document_uris=("https://example.com/a.xml",)),
        uri_bindings=_bindings_for_synthetic(),
    )
    assert report.arelle_item_fact_count == len(report.facts) == 4
    assert [f.source_order for f in report.facts] == [0, 1, 2, 3]
    assets_facts = [f for f in report.facts if f.concept.local_name == "Assets"]
    assert len(assets_facts) == 2
    nil_fact = next(f for f in report.facts if f.source_xml_id == "fnil")
    assert nil_fact.value_status == "nil"
    assert nil_fact.is_nil
    assert nil_fact.resolved_numeric is None
    invalid = next(f for f in report.facts if f.source_xml_id == "finvalid")
    assert invalid.value_status == "invalid"
    assert invalid.raw_lexical_value == "not-a-number"


def test_adapt_reference_parts_are_ordered_qname_value_array() -> None:
    report = adapt_report_extraction(
        _synthetic_projection(),
        InstanceReportInput(document_uris=("https://example.com/a.xml",)),
        uri_bindings=_bindings_for_synthetic(),
    )
    assert len(report.references) == 1
    parts = [p.to_dict() for p in report.references[0].reference_parts]
    assert parts == [{"qname": "{http://www.xbrl.org/2003/ref}Publisher", "value": "FASB"}]


def test_adapt_raises_when_fact_uri_unresolvable() -> None:
    data = _synthetic_projection()
    with pytest.raises(SourceAdaptError, match="logical_path"):
        adapt_report_extraction(
            data,
            InstanceReportInput(document_uris=("https://example.com/a.xml",)),
            uri_bindings=(
                UriBinding(
                    document_uri="https://example.com/t.xsd",
                    artifact_path="external/schema.xsd",
                    content_sha256="b" * 64,
                ),
            ),
        )


def test_extract_filing_minimal_duplicates_and_count(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    bundle = make_minimal_semantic_bundle(store)
    filing = extract_filing(bundle, store)
    assert len(filing.reports) == 1
    assert filing.document_blocks == ()
    assert filing.filing_sections == ()
    report = filing.reports[0]
    assert report.arelle_item_fact_count == len(report.facts)
    assert report.arelle_item_fact_count >= 2
    assets = [f for f in report.facts if f.concept.local_name == "Assets"]
    assert len(assets) >= 2
    assert all(f.resolved_numeric == Decimal("100") for f in assets)
    assert all(f.source_document_relative_path == "accession/a.xml" for f in report.facts)


def test_extract_filing_rich_nil_and_qnames(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    filing = extract_filing(make_rich_semantic_bundle(store), store)
    report = filing.reports[0]
    assert report.arelle_item_fact_count == len(report.facts)
    by_name = {f.concept.local_name: f for f in report.facts}
    assert by_name["NilNote"].value_status == "nil"
    assert by_name["NilNote"].is_nil
    assert by_name["Assets"].concept.namespace_uri == "http://example.com/rich"
    assert by_name["Assets"].resolved_numeric is not None
    assert isinstance(by_name["Assets"].resolved_numeric, Decimal)
    assert any(c.local_name == "Assets" for c in report.concepts)
    assert any(d.concept.local_name == "Assets" for d in report.declarations)


def test_extract_filing_invalid_transform_facts_counted(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    filing = extract_filing(make_invalid_transform_bundle(store), store)
    report = filing.reports[0]
    assert report.arelle_item_fact_count == len(report.facts)
    by_id = {f.source_xml_id: f for f in report.facts}
    assert by_id["fvalid"].value_status == "valid"
    assert by_id["fvalid"].resolved_numeric == Decimal("1234.56")
    assert by_id["finvalid"].value_status == "invalid"
    assert by_id["finvalid-nf"].value_status == "invalid"


def test_multi_report_filing_extraction(tmp_path: Path) -> None:
    """Two ReportExtraction rows in one FilingExtraction (synthetic multi-report)."""
    store = ObjectStore(tmp_path)
    bundle_a = make_minimal_semantic_bundle(store)
    uri_b = "https://www.sec.gov/Archives/edgar/data/1/0000000001000010/b.xml"
    path_b = "accession/b.xml"
    inst_b = store.put_bytes(INSTANCE)
    artifacts_b = tuple(
        (
            BundleArtifact(
                logical_path=path_b,
                content=ContentObject(sha256=inst_b.sha256, byte_size=inst_b.byte_size),
                artifact_kind="primary_document",
                required=True,
            )
            if a.logical_path == "accession/a.xml"
            else a
        )
        for a in bundle_a.artifacts
    )
    bindings_b = tuple(
        UriBinding(uri_b, path_b, inst_b.sha256) if b.document_uri == INSTANCE_URI else b
        for b in bundle_a.uri_bindings
    )
    bundle_b = FilingBundle(
        filing=bundle_a.filing,
        payload_hash=compute_payload_hash(artifacts_b),
        artifacts=artifacts_b,
        report_inputs=(InstanceReportInput(document_uris=(uri_b,)),),
        uri_bindings=bindings_b,
    )
    report_a = extract_filing(bundle_a, store).reports[0]
    report_b = extract_filing(bundle_b, store).reports[0]
    filing = FilingExtraction(reports=(report_a, report_b))
    assert len(filing.reports) == 2
    assert report_a.report_key != report_b.report_key
    for report in filing.reports:
        assert report.arelle_item_fact_count == len(report.facts)
        assert report.arelle_item_fact_count >= 2
    paths = {f.source_document_relative_path for r in filing.reports for f in r.facts}
    assert paths == {"accession/a.xml", path_b}
