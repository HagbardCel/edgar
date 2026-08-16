"""Contract tests for offline Arelle → native ReportExtraction."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar.storage.objects import ObjectStore
from edgar.xbrl.extract import UnattributableSourceDocument, canonical_source_document_uri
from edgar.xbrl.semantic import SourceExtractWorkerError, run_offline_extract
from tests.helpers.xbrl_bundles import (
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


def test_offline_extract_period_and_duplicate_facts(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    bundle = make_minimal_semantic_bundle(store)
    result = run_offline_extract(bundle, store)
    assert result.replay.replay_faithful
    assert result.report.contexts
    instants = {ctx.period_instant for ctx in result.report.contexts}
    assert "2024-12-31" in instants
    assert "2025-01-01" not in instants
    assert result.report.arelle_item_fact_count == len(result.report.facts)
    assert result.report.arelle_item_fact_count >= 2
    assert any(d.concept.local_name == "Assets" for d in result.report.declarations)


def test_filed_decimals_inf_not_omitted(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_extract(make_minimal_semantic_bundle(store), store)
    assert all(f.decimals == "INF" for f in result.report.facts)
    assert all(f.resolved_numeric == Decimal("100") for f in result.report.facts)


def test_alias_schema_ref_uses_logical_path(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_extract(make_alias_schema_bundle(store), store)
    assert result.replay.replay_faithful
    paths = {
        d.source_document_relative_path
        for d in result.report.declarations
        if d.source_document_relative_path
    }
    assert paths
    # Primary schema binding path is used; alias URI is not a relative path.
    assert all("alias" not in (p or "") for p in paths)


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
    result = run_offline_extract(make_unit_order_bundle(store), store)
    numerators = [m for m in result.report.measures if m.side == "numerator"]
    assert [m.measure.local_name for m in numerators] == ["Alpha", "Zebra"]
    assert numerators[0].measure.namespace_uri == "http://example.com/a"
    assert numerators[1].measure.namespace_uri == "http://example.com/b"


def test_invalid_transformation_facts_are_faithfully_represented(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_extract(make_invalid_transform_bundle(store), store)
    assert result.replay.replay_faithful
    assert result.report.arelle_item_fact_count == len(result.report.facts)

    by_id = {f.source_xml_id: f for f in result.report.facts}
    valid = by_id["fvalid"]
    invalid_nf = by_id["finvalid-nf"]
    invalid = by_id["finvalid"]

    assert valid.value_status == "valid"
    assert valid.resolved_numeric == Decimal("1234.56")
    assert invalid_nf.value_status == "invalid"
    assert invalid.value_status == "invalid"


def test_dimensional_defaults_not_invented(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_extract(make_dimensional_default_bundle(store), store)
    assert result.report.dimensions == () or all(
        d.member_kind in ("explicit", "typed") for d in result.report.dimensions
    )


def test_rich_semantic_bundle_nil_and_text(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_extract(make_rich_semantic_bundle(store), store)
    assert result.report.arelle_item_fact_count == len(result.report.facts)
    by_name = {f.concept.local_name: f for f in result.report.facts}
    assert by_name["NilNote"].is_nil
    assert by_name["Assets"].resolved_numeric is not None


def test_ixds_multi_document_facts(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_extract(make_ixds_semantic_bundle(store), store)
    assert result.replay.replay_faithful
    assert result.report.arelle_item_fact_count == len(result.report.facts)
    assert result.report.arelle_item_fact_count >= 2
    paths = {f.source_document_relative_path for f in result.report.facts}
    assert len(paths) >= 1


def test_non_dimensional_context_fails(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    with pytest.raises(SourceExtractWorkerError) as exc_info:
        run_offline_extract(make_non_dimensional_context_bundle(store), store)
    assert any(
        issue.code == "UNSUPPORTED_NON_DIMENSIONAL_CONTEXT_CONTENT"
        for issue in exc_info.value.issues
    )


def test_omitted_decimals_not_filled_from_arelle_convenience(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    result = run_offline_extract(make_decimals_omitted_bundle(store), store)
    assert len(result.report.facts) == 1
    fact = result.report.facts[0]
    assert fact.decimals is None
    assert fact.precision is None
    assert fact.resolved_numeric == Decimal("100")


def test_fact_source_order_matches_iterator_not_locator_sort(tmp_path: Path) -> None:
    """Duplicate Assets facts keep iterator ordinals contiguous from zero."""
    store = ObjectStore(tmp_path)
    result = run_offline_extract(make_minimal_semantic_bundle(store), store)
    orders = [f.source_order for f in result.report.facts]
    assert orders == list(range(len(orders)))
    # Minimal fixture has Cash between two Assets in document order; Assets
    # are not contiguous after locator sort would reorder by id.
    assets = [f for f in result.report.facts if f.concept.local_name == "Assets"]
    assert len(assets) >= 2
    assert assets[0].source_order < assets[1].source_order
