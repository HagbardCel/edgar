"""Worker outcome sequencing before upstream pairing (M1A-3)."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from edgar.domain.bundle import InstanceReportInput
from edgar.domain.payload import compute_payload_hash
from edgar.domain.report_key import report_key as compute_report_key
from edgar.storage.objects import ObjectStore
from edgar.xbrl.config import build_semantic_config
from edgar.xbrl.records import ExpandedQName
from edgar.xbrl.replay_normalize import NormalizedReplayView
from edgar.xbrl.report_set import ReportSetError
from edgar.xbrl.semantic import OfflineExtractResult
from edgar.xbrl.source_extract import extract_filing_with_outcomes
from edgar.xbrl.source_records import (
    ConceptDeclarationRecord,
    ConceptRecord,
    ContextRecord,
    FactRecord,
    ReportExtraction,
)
from edgar.xbrl.upstream_inventory import UpstreamInventory
from tests.helpers.xbrl_bundles import INSTANCE_URI, make_minimal_semantic_bundle
from tests.unit.test_xbrl_integrity import _minimal_report


def _dual_report_bundle(store: ObjectStore):
    base = make_minimal_semantic_bundle(store)
    uri_b = "https://example.com/b.xml"
    path_b = "accession/b.xml"
    from edgar.domain.bundle import BundleArtifact, ContentObject, UriBinding

    inst_bytes = store.open_bytes(base.artifacts[0].content.sha256)
    obj = store.put_bytes(inst_bytes)
    artifacts = (
        *base.artifacts,
        BundleArtifact(
            logical_path=path_b,
            content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
            artifact_kind="attachment",
            required=True,
        ),
    )
    bindings = (
        *base.uri_bindings,
        UriBinding(uri_b, path_b, obj.sha256),
    )
    from edgar.domain.bundle import FilingBundle

    return FilingBundle(
        filing=base.filing,
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(
            InstanceReportInput(document_uris=(INSTANCE_URI,)),
            InstanceReportInput(document_uris=(uri_b,)),
        ),
        uri_bindings=bindings,
    )


def _report_for_key(report_key: str, *, fact_count: int) -> ReportExtraction:
    concept = ExpandedQName(namespace_uri="http://example.com/t", local_name="Assets")
    decl = ConceptDeclarationRecord(concept=concept, period_type="instant")
    ctx = ContextRecord(
        source_context_id="c1",
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier="1",
        period_kind="instant",
        period_instant="2024-12-31",
    )
    facts = tuple(
        FactRecord(
            concept=concept,
            source_context_id="c1",
            source_unit_id=None,
            value_status="valid",
            raw_lexical_value=str(i),
            is_nil=False,
            source_order=i,
        )
        for i in range(fact_count)
    )
    return ReportExtraction(
        report_key=report_key,
        report_input={"kind": "instance", "document_uris": ["https://example.com/a.xml"]},
        extractor_version="source-extract-v5",
        arelle_version="test",
        arelle_item_fact_count=fact_count,
        concepts=(
            ConceptRecord(
                namespace_uri=concept.namespace_uri,
                local_name=concept.local_name,
            ),
        ),
        declarations=(decl,),
        contexts=(ctx,),
        facts=facts,
    )


def _empty_replay() -> NormalizedReplayView:
    return NormalizedReplayView(
        load_completed=True,
        network_attempts=(),
        unresolved_documents=(),
        loaded_source_documents=(),
        resolved_documents=(),
        expected_binding_documents=(),
        diagnostics=(),
        errors=(),
        closure_equal=True,
    )


def _worker_result(report: ReportExtraction) -> OfflineExtractResult:
    return OfflineExtractResult(
        report=report,
        replay=_empty_replay(),
        arelle_version="test",
        raw_result={},
        effective_semantic_config={},
    )


def test_swapped_worker_keys_reassociate_inventories(tmp_path) -> None:
    store = ObjectStore(tmp_path)
    bundle = _dual_report_bundle(store)
    key_a = compute_report_key(bundle.report_inputs[0])
    key_b = compute_report_key(bundle.report_inputs[1])
    inv_a = UpstreamInventory(selected_target_item_count=1)
    inv_b = UpstreamInventory(selected_target_item_count=2)
    report_a = _report_for_key(key_a, fact_count=1)
    report_b = _report_for_key(key_b, fact_count=2)

    def fake_workers(*_args, **_kwargs):
        inp = _kwargs.get("report_input") or _args[2]
        uri = inp.document_uris[0] if hasattr(inp, "document_uris") else inp["document_uris"][0]
        if uri == INSTANCE_URI:
            return _worker_result(report_b)
        return _worker_result(report_a)

    with (
        patch(
            "edgar.xbrl.source_extract._inventory_map_for_bundle",
            return_value={key_a: inv_a, key_b: inv_b},
        ),
        patch("edgar.xbrl.source_extract.run_offline_extract", side_effect=fake_workers),
        patch("edgar.xbrl.source_extract.extract_documents_for_filing", return_value=([], [], [])),
    ):
        outcome = extract_filing_with_outcomes(
            bundle,
            store,
            semantic_config=build_semantic_config(),
        )

    assert [o.report.report_key for o in outcome.report_outcomes] == [key_a, key_b]
    assert outcome.report_outcomes[0].upstream_inventory is inv_a
    assert outcome.report_outcomes[1].upstream_inventory is inv_b
    assert outcome.report_outcomes[0].report.arelle_item_fact_count == 1
    assert outcome.report_outcomes[1].report.arelle_item_fact_count == 2


@pytest.mark.parametrize(
    "worker_keys",
    [
        ("dup", "dup"),
        ("a", "unknown"),
    ],
)
def test_worker_set_errors_skip_finalize(tmp_path, worker_keys: tuple[str, ...]) -> None:
    store = ObjectStore(tmp_path)
    bundle = _dual_report_bundle(store)
    key_a = compute_report_key(bundle.report_inputs[0])
    key_b = compute_report_key(bundle.report_inputs[1])
    inv = UpstreamInventory(selected_target_item_count=1)
    base = _minimal_report()
    unknown = "c" * 64
    reports = {
        "a": _worker_result(replace(base, report_key=key_a)),
        "dup": _worker_result(replace(base, report_key=key_a)),
        "unknown": _worker_result(replace(base, report_key=unknown)),
    }

    call_idx = {"n": 0}

    def fake_workers(*_args, **_kwargs):
        k = worker_keys[call_idx["n"]]
        call_idx["n"] += 1
        return reports[k]

    with (
        patch(
            "edgar.xbrl.source_extract._inventory_map_for_bundle",
            return_value={key_a: inv, key_b: inv},
        ),
        patch("edgar.xbrl.source_extract.run_offline_extract", side_effect=fake_workers),
        patch("edgar.xbrl.source_extract.extract_documents_for_filing", return_value=([], [], [])),
        patch("edgar.xbrl.source_extract._finalize_report_outcome") as finalize,
    ):
        with pytest.raises(ReportSetError):
            extract_filing_with_outcomes(
                bundle,
                store,
                semantic_config=build_semantic_config(),
            )
        finalize.assert_not_called()
