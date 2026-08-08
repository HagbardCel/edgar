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
    DiagnosticRecord,
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
    SCHEMA_ALIAS,
    SCHEMA_URI,
    make_alias_schema_bundle,
    make_dimensional_default_bundle,
    make_minimal_semantic_bundle,
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


def test_slice0_transformation_not_auto_complete_compatible() -> None:
    diag = DiagnosticRecord(severity="warning", code="ix11.10.1.2:invalidTransformation")
    assert classify_diagnostic(diag) == "completeness_blocking"


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
