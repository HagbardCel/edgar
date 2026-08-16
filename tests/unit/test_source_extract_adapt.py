"""Unit/contract tests for Phase 2B native source extraction + wire codec."""

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
from edgar.storage.objects import ObjectStore
from edgar.xbrl.records import ExpandedQName
from edgar.xbrl.semantic import SourceExtractWorkerError, run_offline_extract
from edgar.xbrl.source_extract import extract_filing
from edgar.xbrl.source_records import (
    EXTRACTOR_VERSION,
    ConceptDeclarationRecord,
    ConceptRecord,
    ConceptReferenceRecord,
    ContextDimensionRecord,
    ContextRecord,
    ElementLocator,
    FactRecord,
    FilingExtraction,
    ReferencePartRecord,
    RelationshipRecord,
    ReportExtraction,
    UnitMeasureRecord,
    UnitRecord,
)
from edgar.xbrl.source_wire import report_extraction_from_dict, report_extraction_to_dict
from tests.helpers.xbrl_bundles import (
    INSTANCE,
    INSTANCE_URI,
    make_invalid_transform_bundle,
    make_minimal_semantic_bundle,
    make_non_dimensional_context_bundle,
    make_rich_semantic_bundle,
)


def _rich_report_for_wire() -> ReportExtraction:
    concept = ExpandedQName(namespace_uri="http://example.com/test", local_name="Assets")
    other = ExpandedQName(namespace_uri="http://example.com/test", local_name="Note")
    return ReportExtraction(
        report_input={"kind": "instance", "document_uris": ["https://example.com/a.xml"]},
        report_key="a" * 64,
        extractor_version=EXTRACTOR_VERSION,
        arelle_version="2.43.1",
        arelle_item_fact_count=3,
        concepts=(
            ConceptRecord(namespace_uri="http://example.com/test", local_name="Assets"),
            ConceptRecord(namespace_uri="http://example.com/test", local_name="Note"),
        ),
        declarations=(
            ConceptDeclarationRecord(concept=concept, period_type="instant"),
            ConceptDeclarationRecord(concept=other, period_type="duration"),
        ),
        references=(
            ConceptReferenceRecord(
                concept=concept,
                role_uri="http://example.com/role",
                source_order=0,
                reference_parts=(
                    ReferencePartRecord(
                        qname="{http://www.xbrl.org/2003/ref}Publisher", value="FASB"
                    ),
                    ReferencePartRecord(qname="{http://www.xbrl.org/2003/ref}Name", value="Topic"),
                ),
            ),
        ),
        contexts=(
            ContextRecord(
                source_context_id="c1",
                entity_scheme="http://www.sec.gov/CIK",
                entity_identifier="0000000001",
                period_kind="instant",
                period_instant="2024-12-31",
                source_document_relative_path="accession/a.xml",
                source_locator=ElementLocator(scheme="unqualified_id", value="c1"),
            ),
        ),
        dimensions=(
            ContextDimensionRecord(
                source_context_id="c1",
                dimension=ExpandedQName(namespace_uri="http://example.com/test", local_name="Axis"),
                context_element="segment",
                member_kind="typed",
                typed_member={
                    "xml": "<t:Member xmlns:t='http://example.com/test'/>",
                    "sha256": "b" * 64,
                },
            ),
        ),
        units=(UnitRecord(source_unit_id="u1", divide=False),),
        measures=(
            UnitMeasureRecord(
                source_unit_id="u1",
                side="numerator",
                ordinal=1,
                measure=ExpandedQName(
                    namespace_uri="http://www.xbrl.org/2003/iso4217", local_name="USD"
                ),
            ),
        ),
        facts=(
            FactRecord(
                source_order=0,
                concept=concept,
                source_context_id="c1",
                value_status="valid",
                source_unit_id="u1",
                raw_lexical_value="100.10",
                resolved_value_kind="numeric",
                resolved_numeric=Decimal("100.10"),
                decimals="INF",
                source_document_relative_path="accession/a.xml",
                source_locator=ElementLocator(scheme="unqualified_id", value="f1"),
                continuation_provenance=(
                    {
                        "source_document_relative_path": "accession/a.xml",
                        "scheme": "unqualified_id",
                        "value": "cont1",
                    },
                ),
            ),
            FactRecord(
                source_order=1,
                concept=other,
                source_context_id="c1",
                value_status="nil",
                is_nil=True,
                source_document_relative_path="accession/a.xml",
                source_locator=ElementLocator(scheme="unqualified_id", value="f2"),
            ),
            FactRecord(
                source_order=2,
                concept=concept,
                source_context_id="c1",
                value_status="invalid",
                source_unit_id="u1",
                raw_lexical_value="bad",
                source_document_relative_path="accession/a.xml",
                source_locator=ElementLocator(scheme="unqualified_id", value="f3"),
            ),
        ),
        relationships=(
            RelationshipRecord(
                source_order=0,
                network_type="calculation",
                link_role_uri="http://example.com/role/Calc",
                arcrole_uri="http://www.xbrl.org/2003/arcrole/summation-item",
                source_concept=concept,
                target_concept=other,
                order_value=Decimal("1.0"),
                weight=Decimal("-1.0"),
                target_role="http://example.com/role/Target",
            ),
        ),
    )


def test_report_extraction_wire_round_trip() -> None:
    original = _rich_report_for_wire()
    payload = report_extraction_to_dict(original)
    restored = report_extraction_from_dict(payload)
    assert restored == original
    assert restored.facts[0].resolved_numeric == Decimal("100.10")
    assert restored.facts[0].continuation_provenance[0]["value"] == "cont1"
    assert restored.references[0].reference_parts[1].value == "Topic"
    assert restored.relationships[0].weight == Decimal("-1.0")
    assert [f.source_order for f in restored.facts] == [0, 1, 2]


def test_extract_filing_minimal_duplicates_and_count(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    bundle = make_minimal_semantic_bundle(store)
    filing = extract_filing(bundle, store)
    assert len(filing.reports) == 1
    report = filing.reports[0]
    assert report.extractor_version == EXTRACTOR_VERSION
    assert report.arelle_item_fact_count == len(report.facts)
    assert report.arelle_item_fact_count >= 2
    assets = [f for f in report.facts if f.concept.local_name == "Assets"]
    assert len(assets) >= 2
    assert all(f.resolved_numeric == Decimal("100") for f in assets)
    assert all(f.source_document_relative_path == "accession/a.xml" for f in report.facts)
    orders = [f.source_order for f in report.facts]
    assert orders == list(range(len(orders)))


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


def test_non_dimensional_context_fails_extraction(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    with pytest.raises(SourceExtractWorkerError):
        run_offline_extract(make_non_dimensional_context_bundle(store), store)


def test_multi_report_filing_extraction(tmp_path: Path) -> None:
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


def test_report2_fatal_aborts_entire_filing_extraction(tmp_path: Path) -> None:
    """Report 1 would succeed; report 2 is fatal → no FilingExtraction returned."""
    from tests.helpers.xbrl_bundles import INSTANCE_NON_DIM, INSTANCE_URI, SCHEMA_URI

    store = ObjectStore(tmp_path)
    good = make_minimal_semantic_bundle(store)
    uri_bad = "https://www.sec.gov/Archives/edgar/data/1/0000000001000011/bad.xml"
    path_bad = "accession/bad.xml"
    bad_obj = store.put_bytes(INSTANCE_NON_DIM)
    artifacts = (
        *good.artifacts,
        BundleArtifact(
            logical_path=path_bad,
            content=ContentObject(sha256=bad_obj.sha256, byte_size=bad_obj.byte_size),
            artifact_kind="attachment",
            required=True,
        ),
    )
    bindings = (
        *good.uri_bindings,
        UriBinding(uri_bad, path_bad, bad_obj.sha256),
    )
    dual = FilingBundle(
        filing=good.filing,
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(
            InstanceReportInput(document_uris=(INSTANCE_URI,)),
            InstanceReportInput(document_uris=(uri_bad,)),
        ),
        uri_bindings=bindings,
    )
    assert dual.report_inputs[0].document_uris[0] != uri_bad
    # SCHEMA_URI must already be bound via the good bundle.
    assert any(b.document_uri == SCHEMA_URI for b in dual.uri_bindings)
    with pytest.raises(SourceExtractWorkerError):
        extract_filing(dual, store)
