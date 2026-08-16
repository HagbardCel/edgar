"""Contract tests for offline Arelle semantic projection."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar.storage.objects import ObjectStore
from edgar.xbrl.diagnostics import classify_diagnostic
from edgar.xbrl.extract import (
    UnattributableSourceDocument,
    canonical_source_document_uri,
    semantic_status,
)
from edgar.xbrl.records import (
    ConceptDeclarationRecord,
    ContextRecord,
    ExpandedQName,
    FactRecord,
    RelationshipRecord,
    SemanticProjectionData,
    SourceLocator,
    UnitRecord,
)
from edgar.xbrl.semantic import run_offline_semantic_projection
from edgar.xbrl.validate_records import validate_semantic_projection_data
from tests.helpers.xbrl_bundles import (
    INLINE_A_URI,
    INLINE_B_URI,
    SCHEMA_ALIAS,
    SCHEMA_URI,
    make_alias_schema_bundle,
    make_decimals_omitted_bundle,
    make_dimensional_default_bundle,
    make_invalid_transform_bundle,
    make_ixds_semantic_bundle,
    make_minimal_semantic_bundle,
    make_non_dimensional_context_bundle,
    make_rich_semantic_bundle,
    make_unit_order_bundle,
)


def test_offline_semantic_projection_period_and_duplicate_facts(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    bundle = make_minimal_semantic_bundle(store)
    result = run_offline_semantic_projection(bundle, store)
    assert result.replay.replay_faithful
    assert result.data.contexts
    instants = {ctx.period_instant for ctx in result.data.contexts}
    assert "2024-12-31" in instants
    assert "2025-01-01" not in instants
    assert len(result.data.facts) >= 2
    assert any(d.concept.local_name == "Assets" for d in result.data.concept_declarations)
    assert semantic_status(result.data) in {"complete", "incomplete"}


def test_filed_decimals_inf_not_omitted(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_semantic_projection(make_minimal_semantic_bundle(store), store)
    assert all(f.reported_decimals == "INF" for f in result.data.facts)
    assert all(f.resolved_numeric_value == Decimal("100") for f in result.data.facts)


def test_alias_schema_ref_uses_primary_uri(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_semantic_projection(make_alias_schema_bundle(store), store)
    assert result.replay.replay_faithful
    decl_uris = {d.source_locator.document_uri for d in result.data.concept_declarations}
    assert SCHEMA_URI in decl_uris
    assert SCHEMA_ALIAS not in decl_uris


def test_ixds_surrogate_never_canonical_source() -> None:
    from arelle.UrlUtil import IXDS_DOC_SEPARATOR, IXDS_SURROGATE

    surrogate = f"{IXDS_SURROGATE.partition(IXDS_DOC_SEPARATOR)[0]}{IXDS_DOC_SEPARATOR}member.htm"
    doc = SimpleNamespace(uri=surrogate)
    obj = SimpleNamespace(modelDocument=doc)
    bound = SimpleNamespace(aliases={}, documents={})
    with pytest.raises(UnattributableSourceDocument, match="IXDS"):
        canonical_source_document_uri(obj, bound)


def test_unit_measure_expanded_qname_order(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_semantic_projection(make_unit_order_bundle(store), store)
    numerators = [m for m in result.data.unit_measures if m.measure_role == "numerator"]
    assert [m.measure.local_name for m in numerators] == ["Alpha", "Zebra"]
    assert numerators[0].measure.namespace_uri == "http://example.com/a"
    assert numerators[1].measure.namespace_uri == "http://example.com/b"


def test_invalid_transformation_facts_are_faithfully_represented(tmp_path: Path) -> None:
    """invalidTransformation is complete-compatible when invalid facts stay invalid."""
    store = ObjectStore(tmp_path)
    result = run_offline_semantic_projection(make_invalid_transform_bundle(store), store)
    assert result.replay.replay_faithful
    assert result.status == "complete"
    assert result.data.projection_version == "arelle-semantic-v2"

    codes = {d.code for d in result.data.diagnostics}
    assert "ix11.10.1.2:invalidTransformation" in codes
    assert "ix11.11.1.2:invalidTransformation" in codes
    for diag in result.data.diagnostics:
        if diag.code.endswith(":invalidTransformation"):
            assert classify_diagnostic(diag) == "complete_compatible"

    by_id = {
        fact.source_locator.value: fact
        for fact in result.data.facts
        if fact.source_locator.scheme == "unqualified_id"
    }
    valid = by_id["fvalid"]
    invalid_nf = by_id["finvalid-nf"]
    invalid = by_id["finvalid"]

    assert valid.value_status == "valid"
    assert valid.resolved_value_kind == "numeric"
    assert valid.resolved_numeric_value == Decimal("1234.56")
    assert valid.resolved_text_value is None

    assert invalid_nf.concept_qname.local_name == "Liabilities"
    assert invalid_nf.context_locator == valid.context_locator
    assert invalid_nf.unit_locator == valid.unit_locator
    assert invalid_nf.raw_lexical_value == "987.65"
    assert invalid_nf.value_status == "invalid"
    assert invalid_nf.resolved_value_kind is None
    assert invalid_nf.resolved_numeric_value is None
    assert invalid_nf.resolved_text_value is None
    assert invalid_nf.source_locator.value == "finvalid-nf"

    assert invalid.value_status == "invalid"
    assert invalid.raw_lexical_value == "January 1, 2024"
    assert invalid.resolved_value_kind is None
    assert invalid.resolved_numeric_value is None
    assert invalid.resolved_text_value is None
    assert invalid.concept_qname.local_name == "Note"
    assert invalid.source_locator.value == "finvalid"


def test_default_dimension_not_materialized(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_semantic_projection(make_dimensional_default_bundle(store), store)
    assert result.replay.replay_faithful
    axis_dims = [d for d in result.data.context_dimensions if d.dimension.local_name == "Axis"]
    assert axis_dims == []
    assert any(r.arcrole_uri.endswith("/dimension-default") for r in result.data.relationships)


def test_relationship_order_weight_are_decimal() -> None:
    rel = RelationshipRecord(
        network_type="calculation",
        link_role_uri="http://example.com/role",
        arcrole_uri="http://www.xbrl.org/2003/arcrole/summation-item",
        source_concept=ExpandedQName(namespace_uri="http://example.com", local_name="A"),
        target_concept=ExpandedQName(namespace_uri="http://example.com", local_name="B"),
        source_locator=SourceLocator(
            document_uri="https://example.com/a.xml",
            scheme="unqualified_id",
            value="arc1",
        ),
        order=Decimal("1.5"),
        weight=Decimal("-1"),
    )
    assert isinstance(rel.order, Decimal)
    assert isinstance(rel.weight, Decimal)
    assert rel.to_dict()["order"] == "1.5"
    assert rel.to_dict()["weight"] == "-1"


def test_validate_dangling_unit_ref_fails_closed() -> None:
    concept = ExpandedQName(namespace_uri="http://example.com", local_name="Assets")
    decl_loc = SourceLocator(
        document_uri="https://example.com/t.xsd", scheme="unqualified_id", value="Assets"
    )
    ctx_loc = SourceLocator(
        document_uri="https://example.com/a.xml", scheme="unqualified_id", value="c1"
    )
    fact_loc = SourceLocator(
        document_uri="https://example.com/a.xml", scheme="unqualified_id", value="f1"
    )
    missing_unit = SourceLocator(
        document_uri="https://example.com/a.xml", scheme="unqualified_id", value="missing"
    )
    data = SemanticProjectionData(
        projection_version="arelle-semantic-v1",
        config_fingerprint="a" * 64,
        engine_name="arelle",
        engine_version="1",
        concept_declarations=(ConceptDeclarationRecord(concept=concept, source_locator=decl_loc),),
        contexts=(
            ContextRecord(
                source_context_id="c1",
                entity_scheme="http://www.sec.gov/CIK",
                entity_identifier="0000000001",
                period_kind="instant",
                source_locator=ctx_loc,
                period_instant="2024-12-31",
            ),
        ),
        units=(
            UnitRecord(
                source_unit_id="u1",
                source_locator=SourceLocator(
                    document_uri="https://example.com/a.xml",
                    scheme="unqualified_id",
                    value="u1",
                ),
                divide=False,
            ),
        ),
        facts=(
            FactRecord(
                concept_qname=concept,
                context_locator=ctx_loc,
                source_locator=fact_loc,
                value_status="valid",
                unit_locator=missing_unit,
                raw_lexical_value="1",
                resolved_numeric_value=Decimal("1"),
            ),
        ),
    )
    errors = validate_semantic_projection_data(data)
    assert errors
    assert any("unit" in err.lower() for err in errors)


def test_rich_semantic_bundle_is_complete(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_semantic_projection(make_rich_semantic_bundle(store), store)
    assert result.replay.replay_faithful
    assert result.status == "complete"
    assert not any(issue.severity == "fatal" for issue in result.data.issues)
    assert not result.data.diagnostics

    assert any(r.network_type == "presentation" for r in result.data.relationships)
    calc = next(r for r in result.data.relationships if r.network_type == "calculation")
    assert isinstance(calc.order, Decimal)
    assert isinstance(calc.weight, Decimal)
    liab = next(
        r
        for r in result.data.relationships
        if r.network_type == "calculation" and r.target_concept.local_name == "Liabilities"
    )
    assert liab.weight == Decimal("-1")
    assert liab.order == Decimal("2.0")
    assert any(
        r.network_type == "definition" and r.arcrole_uri.endswith("/general-special")
        for r in result.data.relationships
    )

    labels = [lab for lab in result.data.concept_labels if lab.concept.local_name == "Assets"]
    assert len(labels) == 3
    for lab in labels:
        assert lab.link_role_uri
        assert lab.arcrole_uri.endswith("/concept-label")
        assert lab.resource_role_uri
        assert lab.xml_lang == "en"
        assert lab.text
        assert lab.source_locator.document_uri
        assert lab.arc_locator.document_uri
    assert {lab.resource_role_uri for lab in labels} >= {
        "http://www.xbrl.org/2003/role/label",
        "http://www.xbrl.org/2003/role/terseLabel",
        "http://www.xbrl.org/2003/role/documentation",
    }

    refs = [ref for ref in result.data.concept_references if ref.concept.local_name == "Assets"]
    assert len(refs) == 3
    primary = next(
        ref for ref in refs if ref.resource_role_uri == "http://www.xbrl.org/2003/role/reference"
    )
    assert primary.link_role_uri
    assert primary.arcrole_uri.endswith("/concept-reference")
    assert len(primary.reference_parts) >= 3
    assert any("<" in part.xml and "custom" in part.xml for part in primary.reference_parts)

    role = next(
        rd for rd in result.data.role_declarations if rd.role_uri.endswith("/role/Statement")
    )
    assert role.definition == "Statement"
    assert role.used_on
    assert role.source_locator.document_uri
    custom = next(
        a for a in result.data.arcrole_declarations if a.arcrole_uri.endswith("/arcrole/custom")
    )
    assert custom.definition == "Custom arcrole"
    assert custom.cycles_allowed == "undirected"
    assert custom.used_on
    assert custom.source_locator.document_uri

    explicit = [
        d for d in result.data.context_dimensions if d.dimension.local_name == "ExplicitAxis"
    ]
    assert len(explicit) == 1
    assert explicit[0].member_kind == "explicit"
    assert explicit[0].member is not None
    typed = [d for d in result.data.context_dimensions if d.dimension.local_name == "TypedAxis"]
    assert len(typed) == 1
    assert typed[0].member_kind == "typed"
    assert typed[0].typed_member_xml is not None
    assert "TypedDomain" in typed[0].typed_member_xml
    assert "http://example.com/rich" in typed[0].typed_member_xml

    duration = next(c for c in result.data.contexts if c.source_context_id == "cDur")
    assert duration.period_kind == "duration"
    assert duration.period_start == "2024-01-01"
    assert duration.period_end == "2024-12-31"

    by_name = {f.concept_qname.local_name: f for f in result.data.facts}
    assert by_name["TextNote"].resolved_value_kind == "text"
    assert by_name["TextNote"].resolved_text_value == "{foo}bar"
    assert by_name["Flag"].resolved_value_kind == "boolean"
    assert by_name["AsOfDate"].resolved_value_kind == "date"
    assert by_name["AsOfDateTime"].resolved_value_kind == "datetime"
    assert by_name["AsOfTime"].resolved_value_kind == "time"
    assert by_name["RelatedConcept"].resolved_value_kind == "qname"
    assert by_name["RelatedConcept"].resolved_text_value == "{http://example.com/rich}Assets"
    assert by_name["NilNote"].value_status == "nil"
    assert by_name["NilNote"].resolved_text_value is None
    assert by_name["NilNote"].resolved_numeric_value is None
    assets = next(
        f
        for f in result.data.facts
        if f.concept_qname.local_name == "Assets" and f.source_locator.value == "fAssets"
    )
    assert assets.resolved_value_kind == "numeric"
    assert assets.resolved_numeric_value == Decimal("100")
    assert assets.reported_decimals is None


def test_ixds_semantic_bundle_is_complete(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_semantic_projection(make_ixds_semantic_bundle(store), store)
    assert result.replay.replay_faithful
    assert result.status == "complete"
    assert len(result.data.facts) >= 2
    member_uris = {INLINE_A_URI, INLINE_B_URI}
    fact_uris = {f.source_locator.document_uri for f in result.data.facts}
    assert fact_uris <= member_uris
    assert INLINE_A_URI in fact_uris
    assert INLINE_B_URI in fact_uris
    for fact in result.data.facts:
        assert "_IXDS" not in fact.source_locator.document_uri


def test_non_dimensional_context_is_incomplete(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_semantic_projection(make_non_dimensional_context_bundle(store), store)
    assert result.replay.replay_faithful
    assert result.status == "incomplete"
    assert any(
        issue.code == "UNSUPPORTED_NON_DIMENSIONAL_CONTEXT_CONTENT" for issue in result.data.issues
    )


def test_omitted_decimals_not_filled_from_arelle_convenience(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_semantic_projection(make_decimals_omitted_bundle(store), store)
    assert result.status == "complete"
    assert len(result.data.facts) == 1
    fact = result.data.facts[0]
    assert fact.reported_decimals is None
    assert fact.reported_precision is None
    assert fact.resolved_numeric_value == Decimal("100")
