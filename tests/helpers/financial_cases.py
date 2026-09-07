"""M0 financial-benchmark fixture helpers (no production selector).

Validates ``fixtures/analysis/financial-benchmark.yml`` statically and derives
the finite M1A requirements table from case-local evidence capabilities.

Metric-v2 hashing is implemented here for fixture validation only. Production
``edgar.registry.hashing`` remains metric-v1 until M2.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_PATH = _REPO_ROOT / "fixtures" / "analysis" / "financial-benchmark.yml"
REVIEW_PROFILE_PATH = _REPO_ROOT / "registry" / "review-profile.yml"
METRICS_YML_PATH = _REPO_ROOT / "registry" / "metrics.yml"
CORPUS_TOML_PATH = _REPO_ROOT / "fixtures" / "corpus.toml"

CORPUS_ACCESSIONS: frozenset[str] = frozenset(
    {
        "0001065088-23-000006",
        "0001065088-24-000036",
        "0001065088-24-000094",
        "0000104169-24-000056",
        "0000019617-24-000453",
        "0000021344-24-000044",
    }
)

CORE_VALUE_SLOTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("revenue", "0001065088-23-000006"),
        ("revenue", "0001065088-24-000036"),
        ("revenue", "0000104169-24-000056"),
        ("total_assets", "0001065088-23-000006"),
        ("total_assets", "0001065088-24-000036"),
        ("total_assets", "0000104169-24-000056"),
        ("operating_cash_flow", "0001065088-23-000006"),
        ("operating_cash_flow", "0001065088-24-000036"),
        ("operating_cash_flow", "0000104169-24-000056"),
    }
)

EIGHT_QUANTITY_KEYS: tuple[str, ...] = (
    "revenue",
    "operating_income",
    "research_and_development",
    "net_income_attributable_to_parent",
    "total_assets",
    "cash_excluding_restricted_cash",
    "operating_cash_flow",
    "cash_purchases_of_ppe",
)

RELATION_VALUES: frozenset[str] = frozenset({"exact", "narrower", "broader", "related"})
EXPECTED_STATES: frozenset[str] = frozenset(
    {"value", "missing", "conflict", "unsupported", "review_required"}
)
CIK_RE = re.compile(r"^\d{10}$")
ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")

DEFINITION_HASH_FIELDS: tuple[str, ...] = (
    "key",
    "kind",
    "statement",
    "period_type",
    "value_kind",
    "unit_dimension",
    "definition",
    "includes",
    "excludes",
    "accounting_basis",
    "sign_convention",
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def metric_v2_definition_hash(definition: Mapping[str, Any]) -> str:
    """SHA-256 of the documented metric-v2 canonical JSON payload.

    Payload shape::

        {
          "definition_hash_scheme": "metric-v2",
          "definition": <semantic fields including accounting_basis/sign_convention>
        }

    ``includes`` / ``excludes`` are sorted. Display name is excluded.
    """
    missing = [f for f in DEFINITION_HASH_FIELDS if f not in definition]
    if missing:
        raise ValueError(f"definition missing fields for metric-v2 hash: {missing}")
    canonical_definition = {
        "key": definition["key"],
        "kind": definition["kind"],
        "statement": definition["statement"],
        "period_type": definition["period_type"],
        "value_kind": definition["value_kind"],
        "unit_dimension": definition["unit_dimension"],
        "definition": definition["definition"],
        "includes": sorted(definition["includes"]),
        "excludes": sorted(definition["excludes"]),
        "accounting_basis": definition["accounting_basis"],
        "sign_convention": definition["sign_convention"],
    }
    payload = {
        "definition_hash_scheme": "metric-v2",
        "definition": canonical_definition,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_benchmark(path: Path = BENCHMARK_PATH) -> dict[str, Any]:
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"benchmark root must be a mapping: {path}")
    return data


def load_review_profile(path: Path = REVIEW_PROFILE_PATH) -> dict[str, Any]:
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"review profile root must be a mapping: {path}")
    return data


def load_metrics_keys(path: Path = METRICS_YML_PATH) -> set[str]:
    data = load_yaml(path)
    metrics = data.get("metrics") if isinstance(data, dict) else None
    if not isinstance(metrics, list):
        raise ValueError("registry/metrics.yml missing metrics list")
    return {m["key"] for m in metrics if isinstance(m, dict) and "key" in m}


def derive_m1a_requirements(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate case-local evidence_capabilities into a finite M1A table."""
    by_req: dict[str, dict[str, Any]] = {}
    for case in cases:
        case_id = case.get("case_id")
        for cap in case.get("evidence_capabilities") or []:
            if not isinstance(cap, Mapping):
                continue
            if cap.get("required_phase") != "M1A":
                continue
            name = cap.get("capability")
            if not isinstance(name, str):
                continue
            entry = by_req.setdefault(
                name,
                {
                    "requirement": name,
                    "required_phase": "M1A",
                    "blocked_cases": [],
                    "capability_states": set(),
                },
            )
            if case_id is not None:
                entry["blocked_cases"].append(case_id)
            state = cap.get("capability_state")
            if state is not None:
                entry["capability_states"].add(state)
    out: list[dict[str, Any]] = []
    for name in sorted(by_req):
        entry = by_req[name]
        out.append(
            {
                "requirement": entry["requirement"],
                "required_phase": "M1A",
                "blocked_cases": sorted(set(entry["blocked_cases"])),
                "capability_states": sorted(entry["capability_states"]),
            }
        )
    return out


def _require_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssertionError(f"{label} must be a mapping")
    return value


def validate_benchmark_static(
    benchmark: Mapping[str, Any],
    *,
    metrics_keys: set[str] | None = None,
    review_profile: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return a list of validation error strings (empty if ok)."""
    errors: list[str] = []
    metrics_keys = metrics_keys if metrics_keys is not None else load_metrics_keys()
    review_profile = review_profile if review_profile is not None else load_review_profile()
    profile_id = review_profile.get("profile_id")
    profile_groups = {
        g.get("id") for g in (review_profile.get("check_groups") or []) if isinstance(g, Mapping)
    }

    if benchmark.get("benchmark_version") != 1:
        errors.append("benchmark_version must be 1")

    if "m1a_requirements" in benchmark:
        errors.append(
            "m1a_requirements must not be persisted; derive via derive_m1a_requirements()"
        )

    contracts = benchmark.get("contracts")
    if not isinstance(contracts, list) or len(contracts) != 8:
        errors.append("contracts must be a list of exactly 8 entries")
        return errors

    contract_by_key: dict[str, dict[str, Any]] = {}
    for i, raw in enumerate(contracts):
        c = _require_mapping(raw, label=f"contracts[{i}]")
        cref = _require_mapping(c.get("contract_ref"), label=f"contracts[{i}].contract_ref")
        definition = _require_mapping(c.get("definition"), label=f"contracts[{i}].definition")
        review = _require_mapping(c.get("m0_review"), label=f"contracts[{i}].m0_review")
        key = definition.get("key")
        if key != cref.get("metric_key"):
            errors.append(f"contracts[{i}]: definition.key != contract_ref.metric_key")
        if cref.get("definition_hash_scheme") != "metric-v2":
            errors.append(f"contracts[{i}]: definition_hash_scheme must be metric-v2")
        try:
            expected = metric_v2_definition_hash(definition)
        except ValueError as exc:
            errors.append(f"contracts[{i}]: {exc}")
            continue
        if cref.get("definition_hash") != expected:
            errors.append(
                f"contracts[{i}] ({key}): definition_hash mismatch "
                f"(got {cref.get('definition_hash')}, expected {expected})"
            )
        state = review.get("registry_state")
        if state == "existing_key_revision":
            if key not in metrics_keys:
                errors.append(
                    f"contracts[{i}]: existing_key_revision key {key!r} missing from metrics.yml"
                )
        elif state == "proposed_new_key":
            pass
        else:
            errors.append(f"contracts[{i}]: invalid registry_state {state!r}")
        if definition.get("accounting_basis") != "us_gaap":
            errors.append(f"contracts[{i}]: accounting_basis must be us_gaap")
        if definition.get("sign_convention") != "reported":
            errors.append(f"contracts[{i}]: sign_convention must be reported")
        if isinstance(key, str):
            contract_by_key[key] = c

    for expected_key in EIGHT_QUANTITY_KEYS:
        if expected_key not in contract_by_key:
            errors.append(f"missing contract for economic quantity {expected_key!r}")

    cases = benchmark.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty list")
        return errors

    case_ids: set[str] = set()
    accessions_seen: set[str] = set()
    core_hits: set[tuple[str, str]] = set()
    has_extension_exact = False
    has_negative_nonexact = False
    has_amendment = False
    has_jpm = False
    has_ko = False

    for i, raw in enumerate(cases):
        case = _require_mapping(raw, label=f"cases[{i}]")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"cases[{i}]: missing case_id")
            continue
        if case_id in case_ids:
            errors.append(f"duplicate case_id {case_id!r}")
        case_ids.add(case_id)

        cref = _require_mapping(case.get("contract_ref"), label=f"{case_id}.contract_ref")
        metric_key = cref.get("metric_key")
        if metric_key not in contract_by_key:
            errors.append(f"{case_id}: contract_ref.metric_key {metric_key!r} not in contracts")
        else:
            frozen = contract_by_key[metric_key]["contract_ref"]
            if cref.get("definition_hash") != frozen.get("definition_hash"):
                errors.append(f"{case_id}: contract_ref digest does not match frozen contract")

        if case.get("review_profile") != profile_id:
            errors.append(f"{case_id}: review_profile must be {profile_id!r}")

        issuer = _require_mapping(case.get("issuer"), label=f"{case_id}.issuer")
        cik = issuer.get("cik")
        if not isinstance(cik, str) or not CIK_RE.match(cik):
            errors.append(f"{case_id}: invalid issuer.cik")

        report = _require_mapping(case.get("report"), label=f"{case_id}.report")
        accession = report.get("accession")
        if not isinstance(accession, str) or not ACCESSION_RE.match(accession):
            errors.append(f"{case_id}: invalid report.accession")
        else:
            accessions_seen.add(accession)
            if accession not in CORPUS_ACCESSIONS:
                errors.append(f"{case_id}: accession not in corpus.toml six-filing set")
        if not report.get("bundle_ref"):
            errors.append(f"{case_id}: report.bundle_ref is required")
        if not report.get("report_key"):
            errors.append(f"{case_id}: report.report_key is required")

        if accession == "0001065088-24-000094":
            has_amendment = True
        if accession == "0000019617-24-000453":
            has_jpm = True
        if accession == "0000021344-24-000044":
            has_ko = True

        slot = _require_mapping(case.get("slot"), label=f"{case_id}.slot")
        period = _require_mapping(slot.get("period"), label=f"{case_id}.slot.period")
        period_type = period.get("type")
        contract_entry = contract_by_key.get(metric_key) if isinstance(metric_key, str) else None
        contract_def = (
            contract_entry.get("definition") if isinstance(contract_entry, Mapping) else None
        )
        contract_period = (
            contract_def.get("period_type") if isinstance(contract_def, Mapping) else None
        )
        if contract_period and period_type != contract_period:
            errors.append(
                f"{case_id}: slot.period.type {period_type!r} != "
                f"contract period_type {contract_period!r}"
            )
        if period_type == "duration":
            if not period.get("start") or not period.get("end"):
                errors.append(f"{case_id}: duration period requires start and end")
        elif period_type == "instant":
            if not period.get("instant"):
                errors.append(f"{case_id}: instant period requires instant")
        else:
            errors.append(f"{case_id}: period.type must be duration or instant")

        semantic = _require_mapping(
            case.get("semantic_expectation"), label=f"{case_id}.semantic_expectation"
        )
        relation = semantic.get("relation")
        if relation is not None and relation not in RELATION_VALUES:
            errors.append(
                f"{case_id}: relation must be null or one of exact|narrower|broader|related "
                f"(got {relation!r})"
            )
        if relation == "exact":
            if not semantic.get("source_meaning") or not semantic.get("contract_fit"):
                errors.append(f"{case_id}: exact cases require source_meaning and contract_fit")
            assessment = case.get("review_assessment")
            if not isinstance(assessment, Mapping):
                errors.append(f"{case_id}: exact cases require review_assessment")
            else:
                for gid in profile_groups:
                    if gid not in assessment:
                        errors.append(f"{case_id}: review_assessment missing group {gid!r}")
            src = semantic.get("source_concept")
            if case.get("benchmark_role") == "issuer_extension_exact":
                has_extension_exact = True
            elif isinstance(src, str) and "us-gaap" not in src and "fasb" not in src:
                lowered = src.lower()
                if any(tok in lowered for tok in ("ebay.com", "walmart.com", "thecocacolacompany")):
                    has_extension_exact = True

        if relation in {"broader", "related", "narrower"}:
            has_negative_nonexact = True

        expected = _require_mapping(case.get("expected"), label=f"{case_id}.expected")
        state = expected.get("state")
        if state not in EXPECTED_STATES:
            errors.append(f"{case_id}: invalid expected.state {state!r}")

        if state == "value":
            if relation != "exact":
                errors.append(
                    f"{case_id}: expected.state=value requires semantic_expectation.relation=exact"
                )
            if expected.get("value") in (None, ""):
                errors.append(f"{case_id}: value state requires expected.value")
            if not case.get("rendered_evidence"):
                errors.append(f"{case_id}: value state requires rendered_evidence")
            occs = case.get("source_occurrences") or []
            if not isinstance(occs, list) or len(occs) < 1:
                errors.append(f"{case_id}: value state requires ≥1 source_occurrence")
            else:
                for j, occ in enumerate(occs):
                    if not isinstance(occ, Mapping):
                        errors.append(f"{case_id}: source_occurrences[{j}] must be mapping")
                        continue
                    if "id" in occ or "fact_id" in occ or "source_fact_id" in occ:
                        errors.append(f"{case_id}: source_occurrences must not use source.fact.id")
                    path = occ.get("artifact_path")
                    if isinstance(path, str) and path.startswith("/"):
                        errors.append(
                            f"{case_id}: artifact_path must be bundle-relative, not absolute"
                        )
            if (
                isinstance(metric_key, str)
                and isinstance(accession, str)
                and (metric_key, accession) in CORE_VALUE_SLOTS
            ):
                core_hits.add((metric_key, accession))
        elif state == "conflict":
            if not case.get("source_occurrences"):
                errors.append(f"{case_id}: conflict state requires occurrence pins")
            if not expected.get("reason"):
                errors.append(f"{case_id}: conflict state requires reason")
        elif state == "missing":
            if not expected.get("reason"):
                errors.append(f"{case_id}: missing state requires reason")
        elif state == "unsupported":
            if not expected.get("reason"):
                errors.append(f"{case_id}: unsupported state requires reason")
            caps = case.get("evidence_capabilities") or []
            if not any(
                isinstance(c, Mapping) and c.get("capability_state") == "unsupported" for c in caps
            ):
                # allow semantic unsupported without capability gap
                pass
        elif state == "review_required":
            if not expected.get("reason"):
                errors.append(f"{case_id}: review_required state requires reason")

        qual = case.get("qualification")
        if isinstance(qual, Mapping):
            if qual.get("extraction_receipt") is not None:
                errors.append(f"{case_id}: M0 qualification.extraction_receipt must be null")
            pins = qual.get("occurrence_pins")
            if not isinstance(pins, list):
                errors.append(f"{case_id}: qualification.occurrence_pins must be a list")
            for conclusion_name in ("accounting_basis", "entity_basis", "sign_interpretation"):
                conclusion = qual.get(conclusion_name)
                if (
                    isinstance(conclusion, Mapping)
                    and conclusion.get("state") == "confirmed"
                    and not conclusion.get("evidence_pins")
                ):
                    errors.append(f"{case_id}: confirmed {conclusion_name} requires evidence_pins")
            # extraction_receipt gap pairing
            caps = case.get("evidence_capabilities") or []
            has_receipt_gap = any(
                isinstance(c, Mapping)
                and c.get("capability") == "extraction_receipt"
                and c.get("required_phase") == "M1A"
                for c in caps
            )
            if not has_receipt_gap:
                errors.append(
                    f"{case_id}: qualification requires extraction_receipt M1A capability gap"
                )

    extras = accessions_seen - CORPUS_ACCESSIONS
    if extras:
        errors.append(f"cases reference non-corpus accessions: {sorted(extras)}")
    # not all six must appear if review is bounded, but plan requires JPM, KO, amendment covered
    if not has_amendment:
        errors.append("missing eBay amendment case (0001065088-24-000094)")
    if not has_jpm:
        errors.append("missing JPMorgan counterexample case")
    if not has_ko:
        errors.append("missing Coca-Cola counterexample case")
    if not has_negative_nonexact:
        errors.append("missing reviewed negative/non-exact benchmark case")

    replacements = benchmark.get("core_value_slot_replacements") or []
    effective_core = set(core_hits)
    if isinstance(replacements, list):
        for rep in replacements:
            if not isinstance(rep, Mapping):
                continue
            orig_key = rep.get("original_metric_key")
            orig_acc = rep.get("original_accession")
            new_key = rep.get("replacement_metric_key")
            new_acc = rep.get("replacement_accession")
            if (
                isinstance(orig_key, str)
                and isinstance(orig_acc, str)
                and (orig_key, orig_acc) in CORE_VALUE_SLOTS
                and isinstance(new_key, str)
                and isinstance(new_acc, str)
            ):
                effective_core.add((orig_key, orig_acc))  # count as addressed
    missing_core = CORE_VALUE_SLOTS - effective_core
    if missing_core and not replacements:
        # allow explicit documentation of replacements only
        errors.append(
            "nine core value slots incomplete: "
            + ", ".join(f"{m}@{a}" for m, a in sorted(missing_core))
        )
    elif missing_core:
        still = CORE_VALUE_SLOTS - effective_core
        if still:
            errors.append(
                "nine core value slots incomplete even after replacements: "
                + ", ".join(f"{m}@{a}" for m, a in sorted(still))
            )

    # extension exact is soft-checked; if none found, error
    # Look explicitly for tags
    for raw in cases:
        if not isinstance(raw, Mapping):
            continue
        sem = raw.get("semantic_expectation") or {}
        if (
            isinstance(sem, Mapping)
            and sem.get("relation") == "exact"
            and raw.get("benchmark_role") == "issuer_extension_exact"
        ):
            has_extension_exact = True
    if not has_extension_exact:
        errors.append("missing issuer-extension exact benchmark case")

    return errors


__all__ = [
    "BENCHMARK_PATH",
    "CORPUS_ACCESSIONS",
    "CORE_VALUE_SLOTS",
    "EIGHT_QUANTITY_KEYS",
    "REVIEW_PROFILE_PATH",
    "derive_m1a_requirements",
    "load_benchmark",
    "load_metrics_keys",
    "load_review_profile",
    "metric_v2_definition_hash",
    "validate_benchmark_static",
]
