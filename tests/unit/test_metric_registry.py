"""Unit tests for Git metric registry validation and hashing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from edgar.metrics.registry import (
    EXPECTED_V1_METRICS,
    PENDING_REVIEW_SENTINEL,
    FilingScope,
    IssuerPeriodScope,
    IssuerScope,
    RegistryValidationError,
    fingerprint_registry_content,
    load_registry,
    predecessor_chain,
    rule_state,
    scope_cik,
    validate_registry,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_DIR = _REPO_ROOT / "semantic-registry"


def _copy_default_registry(tmp_path: Path) -> Path:
    for name in ("metric-families.json", "metric-definitions.json", "mapping-rules.json"):
        (tmp_path / name).write_text(
            (_REGISTRY_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    return tmp_path


def test_load_default_registry() -> None:
    registry = load_registry(_REGISTRY_DIR)
    validate_registry(registry)
    assert len(registry.families) == 11
    assert len(registry.definitions) == 20
    codes = {d.metric_code for d in registry.definitions}
    assert codes == EXPECTED_V1_METRICS
    assert all(d.definition_version == 1 for d in registry.definitions)
    assert registry.registry_hash
    assert len(registry.registry_hash) == 64


def test_authoritative_registry_has_no_pending_reviewers() -> None:
    registry = load_registry(_REGISTRY_DIR)
    assert all(rule.reviewed_by != PENDING_REVIEW_SENTINEL for rule in registry.rules)


def test_registry_hash_stable() -> None:
    first = load_registry(_REGISTRY_DIR).registry_hash
    second = load_registry(_REGISTRY_DIR).registry_hash
    assert first == second


def test_registry_hash_insensitive_to_record_order(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    registry = load_registry(tmp_path)
    families = list(reversed(registry.families))
    definitions = list(reversed(registry.definitions))
    assert (
        fingerprint_registry_content(
            families=families, definitions=definitions, rules=registry.rules
        )
        == registry.registry_hash
    )


def test_registry_hash_insensitive_to_constraint_list_order(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    data = json.loads((tmp_path / "metric-definitions.json").read_text(encoding="utf-8"))
    first = data["definitions"][0]
    first["constraints"]["inclusion_rules"] = list(
        reversed(first["constraints"]["inclusion_rules"])
    )
    first["constraints"]["exclusion_rules"] = list(
        reversed(first["constraints"]["exclusion_rules"])
    )
    (tmp_path / "metric-definitions.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    assert load_registry(tmp_path).registry_hash == load_registry(_REGISTRY_DIR).registry_hash


def test_registry_hash_sensitive_to_economic_definition(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    baseline = load_registry(tmp_path).registry_hash
    data = json.loads((tmp_path / "metric-definitions.json").read_text(encoding="utf-8"))
    data["definitions"][0]["economic_definition"] = "Changed economic definition."
    (tmp_path / "metric-definitions.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    assert load_registry(tmp_path).registry_hash != baseline


def _sample_rule(*, snapshot: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "rule_key": "map-hash-probe",
        "source_concept": {
            "namespace_uri": "http://example.com/x",
            "local_name": "Revenue",
        },
        "target_metric_code": "operating_company_revenue",
        "target_definition_version": 1,
        "relationship_type": "equivalent",
        "scope_kind": "global",
        "scope": {"kind": "global"},
        "confidence_tier": "high",
        "rationale": "hash probe",
        "evidence_snapshot": snapshot
        if snapshot is not None
        else {"observations": ["first", "second"]},
        "evidence": {
            "accession_number": "0001065088-24-000036",
            "concept": {
                "namespace_uri": "http://example.com/x",
                "local_name": "Revenue",
            },
        },
        "reviewed_by": "Fabian",
        "reviewed_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "supersedes": None,
    }


def test_registry_hash_sensitive_to_ordered_evidence_snapshot_array(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    (tmp_path / "mapping-rules.json").write_text(
        json.dumps({"rules": [_sample_rule()]}, indent=2) + "\n", encoding="utf-8"
    )
    first = load_registry(tmp_path).registry_hash
    (tmp_path / "mapping-rules.json").write_text(
        json.dumps(
            {
                "rules": [
                    _sample_rule(snapshot={"observations": ["second", "first"]}),
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert load_registry(tmp_path).registry_hash != first


def test_duplicate_constraint_entries_rejected(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    data = json.loads((tmp_path / "metric-definitions.json").read_text(encoding="utf-8"))
    data["definitions"][0]["constraints"]["inclusion_rules"].append(
        data["definitions"][0]["constraints"]["inclusion_rules"][0]
    )
    (tmp_path / "metric-definitions.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="duplicate"):
        load_registry(tmp_path)


def test_whitespace_only_rationale_rejected(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    rule = _sample_rule()
    rule["rationale"] = "   "
    (tmp_path / "mapping-rules.json").write_text(
        json.dumps({"rules": [rule]}, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="non-empty"):
        load_registry(tmp_path)


def test_namespace_uri_required(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    rule = _sample_rule()
    rule["source_concept"]["namespace_uri"] = None  # type: ignore[index]
    rule["evidence"]["concept"]["namespace_uri"] = None  # type: ignore[index]
    (tmp_path / "mapping-rules.json").write_text(
        json.dumps({"rules": [rule]}, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError):
        load_registry(tmp_path)


def test_scope_evidence_accession_mismatch_rejected(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    rule = _sample_rule()
    rule["relationship_type"] = "incompatible"
    rule["scope_kind"] = "filing"
    rule["scope"] = {"kind": "filing", "accession_number": "0000320193-24-000001"}
    (tmp_path / "mapping-rules.json").write_text(
        json.dumps({"rules": [rule]}, indent=2) + "\n", encoding="utf-8"
    )
    registry = load_registry(tmp_path)
    with pytest.raises(RegistryValidationError, match="filing scope accession"):
        validate_registry(registry)


def test_scope_evidence_cik_mismatch_rejected(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    rule = _sample_rule()
    rule["relationship_type"] = "issuer_equivalent"
    rule["scope_kind"] = "issuer_period"
    rule["scope"] = {
        "kind": "issuer_period",
        "cik": "0000320193",
        "report_period_from": "2024-01-01",
        "report_period_through": "2024-12-31",
    }
    (tmp_path / "mapping-rules.json").write_text(
        json.dumps({"rules": [rule]}, indent=2) + "\n", encoding="utf-8"
    )
    registry = load_registry(tmp_path)
    with pytest.raises(RegistryValidationError, match="scope.cik"):
        validate_registry(registry)


def test_aggregation_behavior_enforced(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    data = json.loads((tmp_path / "metric-definitions.json").read_text(encoding="utf-8"))
    data["definitions"][0]["constraints"]["aggregation_behavior"] = "point_in_time_balance"
    (tmp_path / "metric-definitions.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    broken = load_registry(tmp_path)
    with pytest.raises(RegistryValidationError, match="aggregation_behavior"):
        validate_registry(broken)


def test_issuer_equivalent_rejects_global_scope(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    rule = _sample_rule()
    rule["relationship_type"] = "issuer_equivalent"
    (tmp_path / "mapping-rules.json").write_text(
        json.dumps({"rules": [rule]}, indent=2) + "\n", encoding="utf-8"
    )
    registry = load_registry(tmp_path)
    with pytest.raises(RegistryValidationError, match="issuer_equivalent"):
        validate_registry(registry)


def test_derived_equivalent_rejected_in_v1(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    rule = _sample_rule()
    rule["relationship_type"] = "derived_equivalent"
    (tmp_path / "mapping-rules.json").write_text(
        json.dumps({"rules": [rule]}, indent=2) + "\n", encoding="utf-8"
    )
    registry = load_registry(tmp_path)
    with pytest.raises(RegistryValidationError, match="derived_equivalent"):
        validate_registry(registry)


def test_predecessor_chain_order(tmp_path: Path) -> None:
    _copy_default_registry(tmp_path)
    reviewed_at = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    concept = {"namespace_uri": "http://example.com/x", "local_name": "Revenue"}
    evidence = {
        "accession_number": "0001065088-24-000036",
        "concept": concept,
    }

    def rule(key: str, supersedes: str | None) -> dict[str, object]:
        return {
            "rule_key": key,
            "source_concept": concept,
            "target_metric_code": "operating_company_revenue",
            "target_definition_version": 1,
            "relationship_type": "equivalent",
            "scope_kind": "global",
            "scope": {"kind": "global"},
            "confidence_tier": "high",
            "rationale": key,
            "evidence_snapshot": {"note": key},
            "evidence": evidence,
            "reviewed_by": "Fabian",
            "reviewed_at": reviewed_at,
            "supersedes": None if supersedes is None else {"rule_key": supersedes},
        }

    rules_doc = {"rules": [rule("map-a", None), rule("map-b", "map-a"), rule("map-c", "map-b")]}
    (tmp_path / "mapping-rules.json").write_text(json.dumps(rules_doc, indent=2) + "\n")
    registry = load_registry(tmp_path)
    validate_registry(registry)
    rules_by_key = {r.rule_key: r for r in registry.rules}
    assert [r.rule_key for r in predecessor_chain("map-c", rules_by_key)] == [
        "map-a",
        "map-b",
        "map-c",
    ]
    assert rule_state("map-a", rules_by_key) == "superseded"
    assert rule_state("map-c", rules_by_key) == "current"


def test_rule_state_unknown_key_raises() -> None:
    registry = load_registry(_REGISTRY_DIR)
    rules_by_key = {r.rule_key: r for r in registry.rules}
    with pytest.raises(KeyError, match="unknown mapping rule"):
        rule_state("missing", rules_by_key)


def test_scope_cik_from_filing_scope() -> None:
    scope = FilingScope(kind="filing", accession_number="0001065088-24-000036")
    assert scope_cik(scope) == "0001065088"
    assert scope_cik(IssuerScope(kind="issuer", cik="0001065088")) == "0001065088"
    assert (
        scope_cik(
            IssuerPeriodScope(
                kind="issuer_period",
                cik="0001065088",
                report_period_from=datetime(2024, 1, 1, tzinfo=UTC).date(),
                report_period_through=datetime(2024, 12, 31, tzinfo=UTC).date(),
            )
        )
        == "0001065088"
    )


def test_cash_and_cash_equivalents_excludes_restricted_totals() -> None:
    registry = load_registry(_REGISTRY_DIR)
    cash = next(d for d in registry.definitions if d.metric_code == "cash_and_cash_equivalents")
    assert any(
        "excluding separately defined restricted cash" in r
        for r in cash.constraints.inclusion_rules
    )
    assert any("restricted cash" in r.lower() for r in cash.constraints.exclusion_rules)
