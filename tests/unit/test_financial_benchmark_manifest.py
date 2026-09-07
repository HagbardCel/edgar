"""Static validation for the M0 financial-benchmark manifest."""

from __future__ import annotations

from tests.helpers.financial_cases import (
    CORE_VALUE_SLOTS,
    CORPUS_ACCESSIONS,
    EIGHT_QUANTITY_KEYS,
    derive_m1a_requirements,
    load_benchmark,
    load_corpus_accessions,
    load_metrics_keys,
    load_review_profile,
    metric_v2_definition_hash,
    validate_benchmark_static,
)


def test_review_profile_four_groups() -> None:
    profile = load_review_profile()
    assert profile["profile_id"] == "reported-financial-exact-v1"
    groups = {g["id"] for g in profile["check_groups"]}
    assert groups == {
        "declaration_definition",
        "fact_usage",
        "network_resources",
        "contrary_evidence_contract_fit",
    }


def test_metric_v2_hash_is_stable_for_revenue_contract() -> None:
    benchmark = load_benchmark()
    revenue = next(c for c in benchmark["contracts"] if c["definition"]["key"] == "revenue")
    assert revenue["contract_ref"]["definition_hash_scheme"] == "metric-v2"
    assert revenue["contract_ref"]["definition_hash"] == metric_v2_definition_hash(
        revenue["definition"]
    )


def test_corpus_accessions_loaded_from_toml() -> None:
    assert load_corpus_accessions() == CORPUS_ACCESSIONS
    assert len(CORPUS_ACCESSIONS) == 6


def test_financial_benchmark_static_validation() -> None:
    benchmark = load_benchmark()
    errors = validate_benchmark_static(
        benchmark,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert errors == []


def test_eight_contracts_and_quantities() -> None:
    benchmark = load_benchmark()
    keys = {c["definition"]["key"] for c in benchmark["contracts"]}
    assert keys == set(EIGHT_QUANTITY_KEYS)
    assert len(benchmark["contracts"]) == 8


def test_cases_cover_corpus_roles() -> None:
    benchmark = load_benchmark()
    accessions = {c["report"]["accession"] for c in benchmark["cases"]}
    assert accessions == CORPUS_ACCESSIONS


def test_nine_core_value_slots_present() -> None:
    benchmark = load_benchmark()
    hits: set[tuple[str, str]] = set()
    for case in benchmark["cases"]:
        if case.get("expected", {}).get("state") != "value":
            continue
        key = case["contract_ref"]["metric_key"]
        accession = case["report"]["accession"]
        if (key, accession) in CORE_VALUE_SLOTS:
            hits.add((key, accession))
    assert hits == CORE_VALUE_SLOTS


def test_value_cases_have_confirmed_economic_qualifications() -> None:
    benchmark = load_benchmark()
    for case in benchmark["cases"]:
        if case.get("expected", {}).get("state") != "value":
            continue
        qual = case["qualification"]
        for name in ("accounting_basis", "entity_basis", "sign_interpretation"):
            assert qual[name]["state"] == "confirmed", case["case_id"]
        assert qual["extraction_receipt"] is None


def test_report_keys_are_64_hex_not_bundle_payload() -> None:
    benchmark = load_benchmark()
    for case in benchmark["cases"]:
        rk = case["report"]["report_key"]
        assert len(rk) == 64
        assert all(c in "0123456789abcdef" for c in rk)
        assert not rk.startswith("bundle-payload")


def test_no_dimension_selection_policy_in_m1a_delta() -> None:
    benchmark = load_benchmark()
    for case in benchmark["cases"]:
        for cap in case.get("evidence_capabilities") or []:
            assert cap.get("capability") != "dimension_selection_policy"
    reqs = derive_m1a_requirements(benchmark["cases"])
    assert "dimension_selection_policy" not in {r["requirement"] for r in reqs}


def test_derive_m1a_requirements_is_benchmark_triggered_delta() -> None:
    benchmark = load_benchmark()
    reqs = derive_m1a_requirements(benchmark["cases"])
    by_name = {r["requirement"]: r for r in reqs}
    assert "extraction_receipt" in by_name
    assert by_name["extraction_receipt"]["required_phase"] == "M1A"
    assert "persisted_link_arc_qnames" in by_name
    assert "m1a_requirements" not in benchmark


def test_reviewed_issuer_extension_case_present() -> None:
    benchmark = load_benchmark()
    found = False
    for case in benchmark["cases"]:
        sem = case.get("semantic_expectation") or {}
        src = sem.get("source_concept")
        if not isinstance(src, str):
            continue
        if "ebay.com" not in src and "walmart.com" not in src and "thecocacolacompany" not in src:
            continue
        if "us-gaap" in src or "fasb.org" in src:
            continue
        if sem.get("relation") not in {"exact", "narrower", "broader", "related"}:
            continue
        if not sem.get("source_meaning") or not sem.get("contract_fit"):
            continue
        if case.get("source_occurrences") or case.get("review_assessment"):
            found = True
            break
    assert found


def test_walmart_rnd_missing_has_assessment() -> None:
    benchmark = load_benchmark()
    case = next(c for c in benchmark["cases"] if c["case_id"] == "walmart_fy2024_rnd_missing")
    assert case["expected"]["state"] == "missing"
    assessment = case["expected"]["assessment"]
    for field in (
        "inspected_scope",
        "method",
        "evidence_pins",
        "limits",
        "conclusion",
        "reviewer",
    ):
        assert field in assessment


def test_no_source_fact_ids_in_occurrences() -> None:
    benchmark = load_benchmark()
    for case in benchmark["cases"]:
        for occ in case.get("source_occurrences") or []:
            assert "id" not in occ
            assert "fact_id" not in occ
            assert "source_fact_id" not in occ
        qual = case.get("qualification") or {}
        for occ in qual.get("occurrence_pins") or []:
            assert "id" not in occ
            assert "fact_id" not in occ
