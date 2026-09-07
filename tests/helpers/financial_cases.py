"""M0 financial-benchmark fixture helpers (no production selector).

Validates ``fixtures/analysis/financial-benchmark.yml`` statically and derives
benchmark-triggered M1A evidence needs from case-local evidence capabilities.

``derive_m1a_requirements()`` answers which parts/readers of the authoritative
M1A scope in ``docs/architecture/migration-plan.md`` are concretely exercised or
blocked by these cases. It is not an M1A implementation plan and is not
authoritative over that document.

Metric-v2 hashing is implemented here for fixture validation only. Production
``edgar.registry.hashing`` remains metric-v1 until M2.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_PATH = _REPO_ROOT / "fixtures" / "analysis" / "financial-benchmark.yml"
REVIEW_PROFILE_PATH = _REPO_ROOT / "registry" / "review-profile.yml"
METRICS_YML_PATH = _REPO_ROOT / "registry" / "metrics.yml"
CORPUS_TOML_PATH = _REPO_ROOT / "fixtures" / "corpus.toml"

REPORT_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CIK_RE = re.compile(r"^\d{10}$")
ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
QNAME_RE = re.compile(r"^\{[^}]+\}[^/\s]+$")


def load_corpus_accessions(path: Path = CORPUS_TOML_PATH) -> frozenset[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    filings = data.get("filings")
    if not isinstance(filings, list):
        raise ValueError(f"corpus.toml missing filings list: {path}")
    accessions: set[str] = set()
    for row in filings:
        if isinstance(row, Mapping) and isinstance(row.get("accession"), str):
            accessions.add(row["accession"])
    if len(accessions) != 6:
        raise ValueError(f"expected 6 corpus accessions, got {len(accessions)}")
    return frozenset(accessions)


CORPUS_ACCESSIONS: frozenset[str] = load_corpus_accessions()

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
EXTENSION_NAMESPACE_TOKENS: tuple[str, ...] = (
    "ebay.com",
    "walmart.com",
    "thecocacolacompany",
)

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

MISSING_ASSESSMENT_FIELDS: tuple[str, ...] = (
    "inspected_scope",
    "method",
    "evidence_pins",
    "limits",
    "conclusion",
    "reviewer",
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
    """Aggregate case-local evidence_capabilities into benchmark-triggered M1A needs.

    Returns the finite set of M1A evidence needs exercised or blocked by these
    cases within the authoritative M1A scope (extraction receipts; supported
    network identity; integrity/completeness; bounded inspector). This is a
    case-driven delta, not an M1A implementation plan and not authoritative over
    ``docs/architecture/migration-plan.md``.
    """
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


def _is_issuer_extension_qname(qname: str) -> bool:
    lowered = qname.lower()
    if "us-gaap" in lowered or "fasb.org" in lowered or "dei:" in lowered:
        return False
    return any(tok in lowered for tok in EXTENSION_NAMESPACE_TOKENS)


def _contract_ref_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return (
        left.get("metric_key") == right.get("metric_key")
        and left.get("definition_hash_scheme") == right.get("definition_hash_scheme")
        and left.get("definition_hash") == right.get("definition_hash")
    )


def _bundle_ref_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    keys = ("opaque_id", "payload_hash", "relative_bundle_dir")
    return all(left.get(k) == right.get(k) for k in keys)


def _portable_pin_identity(pin: Mapping[str, Any]) -> tuple[str, str, str] | None:
    sha = pin.get("artifact_sha256")
    locator = pin.get("locator")
    if not isinstance(sha, str) or not isinstance(locator, Mapping):
        return None
    scheme = locator.get("scheme")
    value = locator.get("value")
    if not isinstance(scheme, str) or not isinstance(value, str):
        return None
    return (sha, scheme, value)


def _measurement_occurrence_identities(case: Mapping[str, Any]) -> set[tuple[str, str, str]]:
    identities: set[tuple[str, str, str]] = set()
    for occ in case.get("source_occurrences") or []:
        if isinstance(occ, Mapping):
            ident = _portable_pin_identity(occ)
            if ident is not None:
                identities.add(ident)
    assessment = case.get("review_assessment")
    if isinstance(assessment, Mapping):
        fact_usage = assessment.get("fact_usage")
        if isinstance(fact_usage, Mapping):
            for pin in fact_usage.get("evidence_pins") or []:
                if isinstance(pin, Mapping):
                    ident = _portable_pin_identity(pin)
                    if ident is not None:
                        identities.add(ident)
    return identities


def _validate_locator_struct(locator: Any, *, label: str, errors: list[str]) -> None:
    if not isinstance(locator, Mapping):
        errors.append(f"{label}: locator must be a mapping")
        return
    scheme = locator.get("scheme")
    value = locator.get("value")
    if scheme not in {"unqualified_id", "xpath", "byte_range"}:
        errors.append(f"{label}: locator.scheme invalid ({scheme!r})")
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}: locator.value must be a nonempty string")


def _validate_occurrence_struct(occ: Any, *, label: str, errors: list[str]) -> None:
    if not isinstance(occ, Mapping):
        errors.append(f"{label} must be a mapping")
        return
    if "id" in occ or "fact_id" in occ or "source_fact_id" in occ:
        errors.append(f"{label}: must not use source.fact.id fields")
    sha = occ.get("artifact_sha256")
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        errors.append(f"{label}: artifact_sha256 must be 64 lowercase hex")
    path = occ.get("artifact_path")
    if not isinstance(path, str) or not path or path.startswith("/"):
        errors.append(f"{label}: artifact_path must be nonempty and bundle-relative")
    locator = occ.get("locator")
    if locator is None:
        errors.append(f"{label}: locator must be non-null")
    else:
        _validate_locator_struct(locator, label=f"{label}.locator", errors=errors)
    qname = occ.get("concept_qname")
    if not isinstance(qname, str) or not QNAME_RE.match(qname):
        errors.append(f"{label}: concept_qname Clark QName is required")


def _validate_evidence_pin_struct(pin: Any, *, label: str, errors: list[str]) -> None:
    if not isinstance(pin, Mapping):
        errors.append(f"{label} must be a mapping")
        return
    sha = pin.get("artifact_sha256")
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        errors.append(f"{label}: artifact_sha256 must be 64 lowercase hex")
    locator = pin.get("locator")
    if locator is None:
        errors.append(f"{label}: locator must be non-null")
    else:
        _validate_locator_struct(locator, label=f"{label}.locator", errors=errors)


def _validate_present_review_assessment_pins(
    case_id: str,
    assessment: Any,
    *,
    errors: list[str],
) -> None:
    """Structurally validate evidence_pins on any present review_assessment group.

    Does not require the full exact-review profile; exact cases add that separately.
    """
    if assessment is None:
        return
    if not isinstance(assessment, Mapping):
        errors.append(f"{case_id}: review_assessment must be a mapping when present")
        return
    for gid, group in assessment.items():
        if not isinstance(group, Mapping):
            errors.append(f"{case_id}: review_assessment.{gid} must be a mapping")
            continue
        pins = group.get("evidence_pins")
        if pins is None:
            continue
        if not isinstance(pins, list):
            errors.append(f"{case_id}: review_assessment.{gid}.evidence_pins must be a list")
            continue
        for j, pin in enumerate(pins):
            _validate_evidence_pin_struct(
                pin, label=f"{case_id}.review_assessment.{gid}.evidence_pins[{j}]", errors=errors
            )


def _validate_exact_review_assessment(
    case_id: str,
    assessment: Any,
    *,
    profile_groups: set[Any],
    per_check_fields: Sequence[str],
    errors: list[str],
) -> None:
    if not isinstance(assessment, Mapping):
        errors.append(f"{case_id}: exact cases require review_assessment")
        return
    for gid in profile_groups:
        group = assessment.get(gid)
        if not isinstance(group, Mapping):
            errors.append(f"{case_id}: review_assessment missing group {gid!r}")
            continue
        for field in per_check_fields:
            if field not in group:
                errors.append(
                    f"{case_id}: review_assessment.{gid} missing required field {field!r}"
                )
        pins = group.get("evidence_pins")
        if pins is None:
            continue
        if not isinstance(pins, list):
            errors.append(f"{case_id}: review_assessment.{gid}.evidence_pins must be a list")
            continue
        for j, pin in enumerate(pins):
            _validate_evidence_pin_struct(
                pin, label=f"{case_id}.review_assessment.{gid}.evidence_pins[{j}]", errors=errors
            )


def validate_benchmark_static(
    benchmark: Mapping[str, Any],
    *,
    metrics_keys: set[str] | None = None,
    review_profile: Mapping[str, Any] | None = None,
    corpus_accessions: frozenset[str] | None = None,
) -> list[str]:
    """Return a list of validation error strings (empty if ok).

    Static fixture validity is not runtime evidence resolution and is not
    M2 exact-acceptance certification.
    """
    errors: list[str] = []
    metrics_keys = metrics_keys if metrics_keys is not None else load_metrics_keys()
    review_profile = review_profile if review_profile is not None else load_review_profile()
    corpus_accessions = corpus_accessions if corpus_accessions is not None else CORPUS_ACCESSIONS
    profile_id = review_profile.get("profile_id")
    profile_groups = {
        g.get("id") for g in (review_profile.get("check_groups") or []) if isinstance(g, Mapping)
    }
    per_check_fields = [
        f for f in (review_profile.get("per_check_fields") or []) if isinstance(f, str)
    ]

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
    has_reviewed_extension = False
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
            if not _contract_ref_equal(cref, frozen):
                errors.append(
                    f"{case_id}: contract_ref (key/scheme/digest) does not match frozen contract"
                )

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
            if accession not in corpus_accessions:
                errors.append(f"{case_id}: accession not in corpus.toml six-filing set")
        bundle_ref = report.get("bundle_ref")
        if not isinstance(bundle_ref, Mapping):
            errors.append(f"{case_id}: report.bundle_ref is required")
        report_key = report.get("report_key")
        if not isinstance(report_key, str) or not REPORT_KEY_RE.match(report_key):
            errors.append(f"{case_id}: report.report_key must be 64 lowercase hex")

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

        src = semantic.get("source_concept")
        if src is not None and (not isinstance(src, str) or not QNAME_RE.match(src)):
            errors.append(f"{case_id}: source_concept must be a valid Clark QName when non-null")
        if relation is not None:
            if src is None:
                errors.append(
                    f"{case_id}: source_concept Clark QName required when relation is not null"
                )
            if not semantic.get("source_meaning") or not semantic.get("contract_fit"):
                errors.append(
                    f"{case_id}: non-null relation requires source_meaning and contract_fit"
                )

        _validate_present_review_assessment_pins(
            case_id, case.get("review_assessment"), errors=errors
        )

        if relation == "exact":
            _validate_exact_review_assessment(
                case_id,
                case.get("review_assessment"),
                profile_groups=profile_groups,
                per_check_fields=per_check_fields,
                errors=errors,
            )
            assessment = case.get("review_assessment")
            if isinstance(assessment, Mapping):
                dd = assessment.get("declaration_definition")
                if isinstance(dd, Mapping):
                    dd_state = dd.get("capability_state")
                    if dd_state == "available":
                        pins = dd.get("evidence_pins") or []
                        if not isinstance(pins, list) or not pins:
                            errors.append(
                                f"{case_id}: available declaration_definition requires "
                                "nonempty evidence_pins"
                            )
                        else:
                            measurement_ids = _measurement_occurrence_identities(case)
                            has_distinct = False
                            for pin in pins:
                                if not isinstance(pin, Mapping):
                                    continue
                                ident = _portable_pin_identity(pin)
                                if ident is not None and ident not in measurement_ids:
                                    has_distinct = True
                                    break
                            if not has_distinct:
                                errors.append(
                                    f"{case_id}: available declaration_definition requires ≥1 "
                                    "semantic-evidence pin distinct from representative "
                                    "measurement occurrences "
                                    "(artifact_sha256, locator.scheme, locator.value)"
                                )
                    elif dd_state in {"not_assessed", "unsupported"}:
                        caps = case.get("evidence_capabilities") or []
                        if not any(
                            isinstance(c, Mapping)
                            and c.get("capability")
                            in {
                                "official_taxonomy_evidence",
                                "taxonomy_declaration_or_definition_disclosure",
                            }
                            for c in caps
                        ):
                            errors.append(
                                f"{case_id}: exact declaration_definition "
                                f"{dd_state} requires an explicit case-local "
                                "evidence_capabilities gap explaining why"
                            )

        if relation in {"broader", "related", "narrower"}:
            has_negative_nonexact = True

        if (
            isinstance(src, str)
            and _is_issuer_extension_qname(src)
            and relation in RELATION_VALUES
            and semantic.get("source_meaning")
            and semantic.get("contract_fit")
        ):
            portable_pins = list(case.get("source_occurrences") or [])
            qual = case.get("qualification") or {}
            if isinstance(qual, Mapping):
                portable_pins.extend(qual.get("occurrence_pins") or [])
            assessment = case.get("review_assessment") or {}
            if isinstance(assessment, Mapping):
                for group in assessment.values():
                    if isinstance(group, Mapping):
                        portable_pins.extend(group.get("evidence_pins") or [])
            if any(isinstance(p, Mapping) for p in portable_pins):
                has_reviewed_extension = True
            else:
                errors.append(
                    f"{case_id}: reviewed issuer-extension case requires ≥1 portable evidence pin"
                )

        expected = _require_mapping(case.get("expected"), label=f"{case_id}.expected")
        state = expected.get("state")
        if state not in EXPECTED_STATES:
            errors.append(f"{case_id}: invalid expected.state {state!r}")

        occs = case.get("source_occurrences") or []
        if isinstance(occs, list):
            for j, occ in enumerate(occs):
                _validate_occurrence_struct(
                    occ, label=f"{case_id}.source_occurrences[{j}]", errors=errors
                )

        if state == "value":
            if relation != "exact":
                errors.append(
                    f"{case_id}: expected.state=value requires semantic_expectation.relation=exact"
                )
            if expected.get("value") in (None, ""):
                errors.append(f"{case_id}: value state requires expected.value")
            if not case.get("rendered_evidence"):
                errors.append(f"{case_id}: value state requires rendered_evidence")
            if not isinstance(occs, list) or len(occs) < 1:
                errors.append(f"{case_id}: value state requires ≥1 source_occurrence")
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
            assessment = expected.get("assessment")
            if not isinstance(assessment, Mapping):
                errors.append(
                    f"{case_id}: missing state requires expected.assessment "
                    "(benchmark-local negative-search record)"
                )
            else:
                for field in MISSING_ASSESSMENT_FIELDS:
                    if field not in assessment:
                        errors.append(f"{case_id}: expected.assessment missing field {field!r}")
                pins = assessment.get("evidence_pins")
                if not isinstance(pins, list) or not pins:
                    errors.append(
                        f"{case_id}: expected.assessment.evidence_pins must be a nonempty list"
                    )
                else:
                    for j, pin in enumerate(pins):
                        _validate_evidence_pin_struct(
                            pin,
                            label=f"{case_id}.expected.assessment.evidence_pins[{j}]",
                            errors=errors,
                        )
        elif state == "unsupported":
            if not expected.get("reason"):
                errors.append(f"{case_id}: unsupported state requires reason")
        elif state == "review_required":
            if not expected.get("reason"):
                errors.append(f"{case_id}: review_required state requires reason")

        for cap in case.get("evidence_capabilities") or []:
            if not isinstance(cap, Mapping):
                continue
            if (
                cap.get("capability") == "dimension_selection_policy"
                and cap.get("required_phase") == "M1A"
            ):
                errors.append(
                    f"{case_id}: dimension_selection_policy must not be an M1A capability"
                )

        qual = case.get("qualification")
        if state == "value":
            if not isinstance(qual, Mapping):
                errors.append(f"{case_id}: expected.state=value requires qualification")
            else:
                for conclusion_name in (
                    "accounting_basis",
                    "entity_basis",
                    "sign_interpretation",
                ):
                    conclusion = qual.get(conclusion_name)
                    if not isinstance(conclusion, Mapping):
                        errors.append(f"{case_id}: value requires qualification.{conclusion_name}")
                        continue
                    if conclusion.get("state") != "confirmed":
                        errors.append(
                            f"{case_id}: value requires {conclusion_name}.state=confirmed "
                            f"(got {conclusion.get('state')!r})"
                        )
                    if not conclusion.get("evidence_pins"):
                        errors.append(
                            f"{case_id}: confirmed {conclusion_name} requires evidence_pins"
                        )

        if isinstance(qual, Mapping):
            if qual.get("extraction_receipt") is not None:
                errors.append(f"{case_id}: M0 qualification.extraction_receipt must be null")
            q_cref = qual.get("contract_ref")
            if not isinstance(q_cref, Mapping):
                errors.append(f"{case_id}: qualification.contract_ref is required")
            elif not _contract_ref_equal(q_cref, cref):
                errors.append(f"{case_id}: qualification.contract_ref != case.contract_ref")
            q_report = qual.get("report_ref")
            if not isinstance(q_report, Mapping):
                errors.append(f"{case_id}: qualification.report_ref is required")
            elif q_report.get("accession") != accession or q_report.get("report_key") != report_key:
                errors.append(
                    f"{case_id}: qualification.report_ref must equal enclosing case report"
                )
            q_bundle = qual.get("bundle_ref")
            if not isinstance(q_bundle, Mapping):
                errors.append(f"{case_id}: qualification.bundle_ref is required")
            elif isinstance(bundle_ref, Mapping) and not _bundle_ref_equal(q_bundle, bundle_ref):
                errors.append(
                    f"{case_id}: qualification.bundle_ref must equal enclosing case bundle_ref"
                )
            pins = qual.get("occurrence_pins")
            if not isinstance(pins, list):
                errors.append(f"{case_id}: qualification.occurrence_pins must be a list")
            else:
                for j, occ in enumerate(pins):
                    _validate_occurrence_struct(
                        occ, label=f"{case_id}.qualification.occurrence_pins[{j}]", errors=errors
                    )
            for conclusion_name in ("accounting_basis", "entity_basis", "sign_interpretation"):
                conclusion = qual.get(conclusion_name)
                if (
                    isinstance(conclusion, Mapping)
                    and conclusion.get("state") == "confirmed"
                    and not conclusion.get("evidence_pins")
                ):
                    errors.append(f"{case_id}: confirmed {conclusion_name} requires evidence_pins")
                if isinstance(conclusion, Mapping):
                    for j, pin in enumerate(conclusion.get("evidence_pins") or []):
                        _validate_evidence_pin_struct(
                            pin,
                            label=f"{case_id}.qualification.{conclusion_name}.evidence_pins[{j}]",
                            errors=errors,
                        )
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

    extras = accessions_seen - corpus_accessions
    if extras:
        errors.append(f"cases reference non-corpus accessions: {sorted(extras)}")
    if not has_amendment:
        errors.append("missing eBay amendment case (0001065088-24-000094)")
    if not has_jpm:
        errors.append("missing JPMorgan counterexample case")
    if not has_ko:
        errors.append("missing Coca-Cola counterexample case")
    if not has_negative_nonexact:
        errors.append("missing reviewed negative/non-exact benchmark case")
    if not has_reviewed_extension:
        errors.append(
            "missing reviewed issuer-extension case "
            "(extension QName + relation + source_meaning + contract_fit + portable pin)"
        )

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
                effective_core.add((orig_key, orig_acc))
    missing_core = CORE_VALUE_SLOTS - effective_core
    if missing_core and not replacements:
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

    return errors


__all__ = [
    "BENCHMARK_PATH",
    "CORPUS_ACCESSIONS",
    "CORE_VALUE_SLOTS",
    "EIGHT_QUANTITY_KEYS",
    "REVIEW_PROFILE_PATH",
    "derive_m1a_requirements",
    "load_benchmark",
    "load_corpus_accessions",
    "load_metrics_keys",
    "load_review_profile",
    "metric_v2_definition_hash",
    "validate_benchmark_static",
]
