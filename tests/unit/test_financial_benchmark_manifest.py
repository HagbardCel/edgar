"""Static validation for the M0 financial-benchmark manifest."""

from __future__ import annotations

from tests.helpers.financial_cases import (
    CORE_VALUE_SLOTS,
    CORPUS_ACCESSIONS,
    EIGHT_QUANTITY_KEYS,
    derive_m1a_requirements,
    load_benchmark,
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


def test_derive_m1a_requirements_includes_extraction_receipt() -> None:
    benchmark = load_benchmark()
    reqs = derive_m1a_requirements(benchmark["cases"])
    by_name = {r["requirement"]: r for r in reqs}
    assert "extraction_receipt" in by_name
    assert by_name["extraction_receipt"]["required_phase"] == "M1A"
    assert "persisted_link_arc_qnames" in by_name
    assert "m1a_requirements" not in benchmark


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
