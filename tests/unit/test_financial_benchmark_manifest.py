"""Static validation for the M0 financial-benchmark manifest."""

from __future__ import annotations

import copy

import pytest

from tests.helpers.financial_cases import (
    CORE_ANNUAL_REPORT_SHAPES,
    CORE_VALUE_ACCESSIONS,
    CORE_VALUE_SLOT_CASE_IDS,
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

NAMED_OFFICIAL_TAXONOMY_CASES = {
    "ebay_fy2022_total_assets_value",
    "ebay_fy2022_operating_cash_flow_value",
    "ebay_fy2023_total_assets_value",
    "ebay_fy2023_operating_cash_flow_value",
    "walmart_fy2024_total_assets_value",
    "walmart_fy2024_operating_cash_flow_value",
    "ebay_fy2023_operating_income_value",
    "ebay_fy2023_rnd_value",
    "ebay_fy2023_cash_ppe_purchases_value",
}


def _value_case(benchmark: dict) -> dict:
    return next(c for c in benchmark["cases"] if c.get("expected", {}).get("state") == "value")


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


def test_current_m0_benchmark_has_all_nine_original_core_value_slots() -> None:
    """Live M0 benchmark currently requires no replacements.

    Replacement behavior is tested separately through mutated fixture copies.
    If M0 is explicitly reopened and a replacement is adopted, this frozen-state
    assertion must change with that reviewed benchmark decision.
    """
    assert len(CORE_VALUE_SLOT_CASE_IDS) == 9
    assert len(set(CORE_VALUE_SLOT_CASE_IDS.values())) == 9
    assert {
        "0001065088-23-000006",
        "0001065088-24-000036",
        "0000104169-24-000056",
    } == CORE_VALUE_ACCESSIONS
    assert frozenset(CORE_VALUE_SLOT_CASE_IDS) == CORE_VALUE_SLOTS
    assert frozenset(CORE_ANNUAL_REPORT_SHAPES) == CORE_VALUE_ACCESSIONS

    benchmark = load_benchmark()
    cases_by_id = {c["case_id"]: c for c in benchmark["cases"]}
    for pair, case_id in CORE_VALUE_SLOT_CASE_IDS.items():
        case = cases_by_id[case_id]
        assert (
            case["contract_ref"]["metric_key"],
            case["report"]["accession"],
        ) == pair
        assert case["expected"]["state"] == "value"
        accession = case["report"]["accession"]
        shape = CORE_ANNUAL_REPORT_SHAPES[accession]
        period = case["slot"]["period"]
        if period["type"] == "duration":
            sig = ("duration", period["start"], period["end"])
        else:
            sig = ("instant", period["instant"])
        assert sig in shape["periods"]
        assert case["slot"]["unit"] == shape["unit"]
        assert case["slot"]["scope"] == shape["scope"]


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


def test_official_taxonomy_evidence_is_m1a_for_named_cases() -> None:
    benchmark = load_benchmark()
    reqs = derive_m1a_requirements(benchmark["cases"])
    ote = {r["requirement"]: r for r in reqs}["official_taxonomy_evidence"]
    assert ote["required_phase"] == "M1A"
    assert set(ote["blocked_cases"]) == NAMED_OFFICIAL_TAXONOMY_CASES


def test_core_value_slots_do_not_gate_publication_evidence_at_m5() -> None:
    benchmark = load_benchmark()
    for case in benchmark["cases"]:
        key = case.get("contract_ref", {}).get("metric_key")
        accession = case.get("report", {}).get("accession")
        if (key, accession) not in CORE_VALUE_SLOTS:
            continue
        for cap in case.get("evidence_capabilities") or []:
            if (
                isinstance(cap, dict)
                and cap.get("capability") == "official_taxonomy_evidence"
                and cap.get("required_phase") == "M5"
            ):
                raise AssertionError(
                    f"{case['case_id']}: CORE_VALUE_SLOT must not gate "
                    "official_taxonomy_evidence at M5"
                )


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


def test_parent_ni_and_walmart_cash_not_false_exact() -> None:
    benchmark = load_benchmark()
    parent = next(
        c for c in benchmark["cases"] if c["case_id"] == "ebay_fy2023_net_income_parent_value"
    )
    assert parent["semantic_expectation"]["relation"] is None
    assert parent["semantic_expectation"]["source_concept"] == (
        "{http://fasb.org/us-gaap/2023}NetIncomeLoss"
    )
    assert parent["expected"]["state"] == "review_required"
    parent_occ = {
        (o.get("locator") or {}).get("value") for o in parent.get("source_occurrences") or []
    }
    assert "f-165" in parent_occ
    parent_pins: set[str] = set()
    for group in (parent.get("review_assessment") or {}).values():
        if not isinstance(group, dict):
            continue
        for pin in group.get("evidence_pins") or []:
            value = (pin.get("locator") or {}).get("value")
            if isinstance(value, str):
                parent_pins.add(value)
    assert "f-497" in parent_pins
    assert parent_pins & {"f-1034", "f-1035"}

    cash = next(
        c
        for c in benchmark["cases"]
        if c["case_id"] == "walmart_fy2024_cash_excluding_restricted_accuracy_review"
    )
    assert cash["semantic_expectation"]["relation"] is None
    assert cash["expected"]["state"] == "review_required"
    assert "reason_code" not in cash["expected"]
    cash_occ = {(o.get("locator") or {}).get("value") for o in cash.get("source_occurrences") or []}
    assert cash_occ >= {"f-171", "f-492"}
    cash_pins: set[str] = set()
    for group in (cash.get("review_assessment") or {}).values():
        if not isinstance(group, dict):
            continue
        for pin in group.get("evidence_pins") or []:
            value = (pin.get("locator") or {}).get("value")
            if isinstance(value, str):
                cash_pins.add(value)
    assert "f-489" in cash_pins


def test_ko_period_is_fiscal_not_calendar_approx() -> None:
    benchmark = load_benchmark()
    ko = next(
        c
        for c in benchmark["cases"]
        if c["case_id"] == "ko_2024q2_segment_revenue_narrower_ytd_counterexample"
    )
    assert ko["slot"]["period"]["start"] == "2024-03-30"
    assert ko["slot"]["period"]["end"] == "2024-06-28"


def test_extension_source_occurrences_exclude_lab_xml() -> None:
    benchmark = load_benchmark()
    ext = next(
        c
        for c in benchmark["cases"]
        if c["case_id"] == "ebay_fy2023_disposal_product_development_rd_extension_narrower"
    )
    paths = [o.get("artifact_path") for o in ext.get("source_occurrences") or []]
    assert paths == ["accession/ebay-20231231.htm"]
    decl = ext["review_assessment"]["declaration_definition"]["evidence_pins"]
    lab_sha = "75d81938377db187698c9db5749e156567f9ac258154f7f9fd50ec23e0e7f341"
    assert any(p.get("artifact_sha256") == lab_sha for p in decl)


def test_available_declaration_uses_distinct_semantic_pin() -> None:
    benchmark = load_benchmark()
    for case in benchmark["cases"]:
        if case.get("semantic_expectation", {}).get("relation") != "exact":
            continue
        dd = case.get("review_assessment", {}).get("declaration_definition") or {}
        if dd.get("capability_state") != "available":
            continue
        measurement = {
            (
                o.get("artifact_sha256"),
                (o.get("locator") or {}).get("scheme"),
                (o.get("locator") or {}).get("value"),
            )
            for o in case.get("source_occurrences") or []
        }
        distinct = False
        for pin in dd.get("evidence_pins") or []:
            ident = (
                pin.get("artifact_sha256"),
                (pin.get("locator") or {}).get("scheme"),
                (pin.get("locator") or {}).get("value"),
            )
            if ident not in measurement:
                distinct = True
                break
        assert distinct, case["case_id"]


def test_no_source_fact_ids_in_occurrences() -> None:
    benchmark = load_benchmark()
    for case in benchmark["cases"]:
        for occ in case.get("source_occurrences") or []:
            assert "id" not in occ
            assert "fact_id" not in occ
            assert "source_fact_id" not in occ
            assert "concept_qname" in occ
        qual = case.get("qualification") or {}
        for occ in qual.get("occurrence_pins") or []:
            assert "id" not in occ
            assert "fact_id" not in occ


@pytest.mark.parametrize("field", ["contract_ref", "report_ref", "bundle_ref"])
def test_qualification_requires_binding_refs(field: str) -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    case = _value_case(mutated)
    del case["qualification"][field]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any(field in e and case["case_id"] in e for e in errors)


def test_occurrence_requires_concept_qname() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    case = _value_case(mutated)
    del case["source_occurrences"][0]["concept_qname"]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("concept_qname" in e and case["case_id"] in e for e in errors)


@pytest.mark.parametrize("pin_list", ["source_occurrences", "qualification.occurrence_pins"])
def test_occurrence_qname_required_on_both_pin_lists(pin_list: str) -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    case = _value_case(mutated)
    if pin_list == "source_occurrences":
        target = case["source_occurrences"][0]
    else:
        target = case["qualification"]["occurrence_pins"][0]
    del target["concept_qname"]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("concept_qname" in e and case["case_id"] in e for e in errors)


def test_unexplained_not_assessed_declaration_requires_capability_gap() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    case = next(
        c
        for c in mutated["cases"]
        if c.get("semantic_expectation", {}).get("relation") == "exact"
        and (c.get("review_assessment") or {})
        .get("declaration_definition", {})
        .get("capability_state")
        == "not_assessed"
        and any(
            isinstance(cap, dict) and cap.get("capability") == "official_taxonomy_evidence"
            for cap in c.get("evidence_capabilities") or []
        )
    )
    case["evidence_capabilities"] = [
        cap
        for cap in case.get("evidence_capabilities") or []
        if not (
            isinstance(cap, dict)
            and cap.get("capability")
            in {
                "official_taxonomy_evidence",
                "taxonomy_declaration_or_definition_disclosure",
            }
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any(
        "declaration_definition" in e and "not_assessed" in e and case["case_id"] in e
        for e in errors
    )


def test_null_relation_rejects_invalid_source_concept_qname() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    case = next(
        c for c in mutated["cases"] if c["case_id"] == "ebay_fy2023_net_income_parent_value"
    )
    case["semantic_expectation"]["source_concept"] = "bad QName"
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("source_concept" in e and case["case_id"] in e for e in errors)


def test_nonexact_review_assessment_rejects_malformed_evidence_pin() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    case = next(
        c for c in mutated["cases"] if c["case_id"] == "ebay_fy2023_net_income_parent_value"
    )
    case["review_assessment"]["contrary_evidence_contract_fit"]["evidence_pins"] = [
        {"artifact_sha256": "not-a-sha", "locator": {"scheme": "unqualified_id", "value": "f-497"}}
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("evidence_pins" in e and case["case_id"] in e for e in errors)


def test_available_declaration_rejects_measurement_only_pin() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    case = next(
        c
        for c in mutated["cases"]
        if c.get("semantic_expectation", {}).get("relation") == "exact"
        and (c.get("review_assessment") or {})
        .get("declaration_definition", {})
        .get("capability_state")
        == "available"
    )
    occ = case["source_occurrences"][0]
    case["review_assessment"]["declaration_definition"]["evidence_pins"] = [
        {
            "artifact_sha256": occ["artifact_sha256"],
            "locator": copy.deepcopy(occ["locator"]),
        }
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("distinct" in e and case["case_id"] in e for e in errors)


def _downgrade_core_slot(benchmark: dict, case_id: str) -> dict:
    case = next(c for c in benchmark["cases"] if c["case_id"] == case_id)
    case["expected"] = {
        "state": "review_required",
        "reason": "mutated fixture: original core slot downgraded for replacement tests",
    }
    case["semantic_expectation"]["relation"] = None
    return case


def _replacement_entry(
    *,
    original_case: dict,
    replacement_case_id: str,
    rationale: str = "Reviewed alternative annual pairing for mutated fixture test.",
) -> dict:
    return {
        "original_metric_key": original_case["contract_ref"]["metric_key"],
        "original_accession": original_case["report"]["accession"],
        "replacement_case_id": replacement_case_id,
        "rationale": rationale,
    }


def test_core_value_slot_replacement_rejects_bogus_replacement() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=original,
            replacement_case_id="does_not_exist_as_a_benchmark_case",
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("does_not_exist_as_a_benchmark_case" in e for e in errors)
    assert any("incomplete even after replacements" in e for e in errors)


def test_core_value_slot_replacement_rejects_non_value_replacement() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=original,
            replacement_case_id="walmart_fy2024_rnd_missing",
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("walmart_fy2024_rnd_missing" in e and "expected.state=value" in e for e in errors)


def test_core_value_slot_replacement_rejects_core_slot_recycling() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=original,
            replacement_case_id="walmart_fy2024_total_assets_value",
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("CORE_VALUE_SLOT" in e and "non-core" in e for e in errors)


def test_core_value_slot_replacement_rejects_non_annual_corpus_case() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    donor = next(
        c for c in mutated["cases"] if c["case_id"] == "ebay_fy2023_operating_income_value"
    )
    jpm = copy.deepcopy(donor)
    jpm["case_id"] = "mutated_jpm_annual_like_value_for_replacement_test"
    jpm["issuer"] = {"cik": "0000019617"}
    jpm["report"]["accession"] = "0000019617-24-000453"
    jpm["report"]["report_key"] = "e9570ef1c7f1cea4f408b099b63e6c7ca08e5cc967e2ce39ad61432b2c07856e"
    jpm["report"]["bundle_ref"] = {
        "opaque_id": "c6d6249a11d3480a840c5f5530a63733",
        "payload_hash": "54aadbdbd93988e8b642c76d7d60c526582c1cdcc9c8a9581967b7346205e10b",
        "relative_bundle_dir": (
            "bundles/0000019617/0000019617-24-000453/c6d6249a11d3480a840c5f5530a63733"
        ),
    }
    jpm["qualification"]["report_ref"]["accession"] = "0000019617-24-000453"
    jpm["qualification"]["report_ref"]["report_key"] = jpm["report"]["report_key"]
    jpm["qualification"]["bundle_ref"] = copy.deepcopy(jpm["report"]["bundle_ref"])
    mutated["cases"].append(jpm)
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=original,
            replacement_case_id=jpm["case_id"],
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("CORE_VALUE_ACCESSIONS" in e or "three M3 annual" in e for e in errors)


def test_core_value_slot_replacement_rejects_non_annual_slot_in_annual_filing() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    donor = next(
        c for c in mutated["cases"] if c["case_id"] == "ebay_fy2023_operating_income_value"
    )
    comparative = copy.deepcopy(donor)
    comparative["case_id"] = "mutated_ebay_fy2023_oi_comparative_period"
    # Keep annual accession, but use a non-target comparative duration.
    comparative["slot"]["period"] = {
        "type": "duration",
        "start": "2022-01-01",
        "end": "2022-12-31",
    }
    mutated["cases"].append(comparative)
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=original,
            replacement_case_id=comparative["case_id"],
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("period" in e and "frozen" in e for e in errors)


def test_core_value_slot_replacement_rejects_reused_replacement_case() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    first = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    second = _downgrade_core_slot(mutated, "ebay_fy2023_revenue_value")
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=first,
            replacement_case_id="ebay_fy2023_operating_income_value",
        ),
        _replacement_entry(
            original_case=second,
            replacement_case_id="ebay_fy2023_operating_income_value",
        ),
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("already used" in e for e in errors)


def test_core_value_slot_replacement_rejects_empty_rationale() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=original,
            replacement_case_id="ebay_fy2023_operating_income_value",
            rationale="   ",
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("rationale" in e for e in errors)


def test_core_value_slot_replacement_accepts_valid_pairing() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=original,
            replacement_case_id="ebay_fy2023_operating_income_value",
            rationale=(
                "Mutated fixture: substitute a reviewed non-core annual operating-income "
                "pairing from an initial annual report after downgrading the original slot."
            ),
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert errors == []


def test_core_value_slot_replacement_rejects_malformed_entry() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    mutated["core_value_slot_replacements"] = ["not-a-mapping"]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("must be a mapping" in e for e in errors)

    mutated["core_value_slot_replacements"] = {"bad": "type"}
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("must be a list" in e for e in errors)


def test_noncanonical_value_case_cannot_satisfy_downgraded_core_slot() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = next(c for c in mutated["cases"] if c["case_id"] == "ebay_fy2023_revenue_value")
    clone = copy.deepcopy(original)
    clone["case_id"] = "mutated_noncanonical_ebay_fy2023_revenue_clone"
    mutated["cases"].append(clone)
    _downgrade_core_slot(mutated, "ebay_fy2023_revenue_value")
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("nine core value slots incomplete" in e for e in errors)
    assert any("revenue@0001065088-24-000036" in e for e in errors)


def test_core_value_slot_replacement_rejects_duplicate_resolved_pairing() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    first = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    second = _downgrade_core_slot(mutated, "ebay_fy2023_revenue_value")
    donor = next(
        c for c in mutated["cases"] if c["case_id"] == "ebay_fy2023_operating_income_value"
    )
    clone_a = copy.deepcopy(donor)
    clone_a["case_id"] = "mutated_oi_donor_a"
    clone_b = copy.deepcopy(donor)
    clone_b["case_id"] = "mutated_oi_donor_b"
    mutated["cases"].extend([clone_a, clone_b])
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(original_case=first, replacement_case_id=clone_a["case_id"]),
        _replacement_entry(original_case=second, replacement_case_id=clone_b["case_id"]),
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("already used" in e and "period" in e for e in errors)


def test_core_value_slot_replacement_cannot_expand_annual_periods_via_extra_core_pair_case() -> (
    None
):
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    # Extra case shares a CORE pair but uses a comparative period — must not
    # widen the annual-period allowlist.
    poison = next(c for c in mutated["cases"] if c["case_id"] == "ebay_fy2023_revenue_value")
    poison_clone = copy.deepcopy(poison)
    poison_clone["case_id"] = "mutated_extra_core_pair_comparative_period"
    poison_clone["expected"] = {
        "state": "review_required",
        "reason": "mutated fixture: comparative period must not expand annual allowlist",
    }
    poison_clone["semantic_expectation"]["relation"] = None
    poison_clone["slot"]["period"] = {
        "type": "duration",
        "start": "2022-01-01",
        "end": "2022-12-31",
    }
    mutated["cases"].append(poison_clone)

    donor = next(
        c for c in mutated["cases"] if c["case_id"] == "ebay_fy2023_operating_income_value"
    )
    comparative_donor = copy.deepcopy(donor)
    comparative_donor["case_id"] = "mutated_oi_using_poisoned_comparative_period"
    comparative_donor["slot"]["period"] = {
        "type": "duration",
        "start": "2022-01-01",
        "end": "2022-12-31",
    }
    mutated["cases"].append(comparative_donor)
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=original,
            replacement_case_id=comparative_donor["case_id"],
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("period" in e and "frozen" in e for e in errors)


def test_core_value_slot_replacement_rejects_unknown_fields() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    entry = _replacement_entry(
        original_case=original,
        replacement_case_id="ebay_fy2023_operating_income_value",
    )
    entry["replacement_metric_key"] = "operating_income"
    entry["replacement_accession"] = "0001065088-24-000036"
    mutated["core_value_slot_replacements"] = [entry]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("unexpected fields" in e for e in errors)
    assert any("replacement_metric_key" in e for e in errors)
    assert any("replacement_accession" in e for e in errors)


def test_core_value_slot_replacement_requires_canonical_original_case() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = next(c for c in mutated["cases"] if c["case_id"] == "ebay_fy2022_revenue_value")
    mutated["cases"] = [c for c in mutated["cases"] if c["case_id"] != "ebay_fy2022_revenue_value"]
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=original,
            replacement_case_id="ebay_fy2023_operating_income_value",
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("canonical original case" in e and "ebay_fy2022_revenue_value" in e for e in errors)


def test_core_value_slot_replacement_rejects_replacement_when_original_is_still_value() -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = next(c for c in mutated["cases"] if c["case_id"] == "ebay_fy2022_revenue_value")
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=original,
            replacement_case_id="ebay_fy2023_operating_income_value",
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any("still state=value" in e and "not applicable" in e for e in errors)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("period", {"type": "duration", "start": "2022-01-01", "end": "2022-12-31"}),
        ("unit", "EUR"),
        ("scope", "some_segment"),
    ],
)
def test_canonical_core_slot_rejects_shape_drift(field: str, value: object) -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    case = next(c for c in mutated["cases"] if c["case_id"] == "ebay_fy2023_revenue_value")
    case["slot"][field] = value
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any(field in e and "frozen" in e for e in errors)
    assert any(
        "nine core value slots incomplete" in e and "revenue@0001065088-24-000036" in e
        for e in errors
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unit", "EUR"),
        ("scope", "some_segment"),
    ],
)
def test_core_value_slot_replacement_rejects_wrong_unit_or_scope(field: str, value: object) -> None:
    benchmark = load_benchmark()
    mutated = copy.deepcopy(benchmark)
    original = _downgrade_core_slot(mutated, "ebay_fy2022_revenue_value")
    donor = next(
        c for c in mutated["cases"] if c["case_id"] == "ebay_fy2023_operating_income_value"
    )
    bad_donor = copy.deepcopy(donor)
    bad_donor["case_id"] = f"mutated_donor_bad_{field}"
    bad_donor["slot"][field] = value
    mutated["cases"].append(bad_donor)
    mutated["core_value_slot_replacements"] = [
        _replacement_entry(
            original_case=original,
            replacement_case_id=bad_donor["case_id"],
        )
    ]
    errors = validate_benchmark_static(
        mutated,
        metrics_keys=load_metrics_keys(),
        review_profile=load_review_profile(),
    )
    assert any(field in e and "frozen" in e for e in errors)
    assert any("incomplete even after replacements" in e for e in errors)
