"""Unit tests for Git metric registry validation and hashing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from edgar.metrics.registry import (
    RegistryValidationError,
    load_registry,
    predecessor_chain,
    rule_state,
    validate_registry,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_DIR = _REPO_ROOT / "semantic-registry"


def test_load_default_registry() -> None:
    registry = load_registry(_REGISTRY_DIR)
    validate_registry(registry)
    assert len(registry.families) == 11
    assert len(registry.definitions) == 20
    assert len(registry.rules) == 0
    assert registry.registry_hash
    assert len(registry.registry_hash) == 64


def test_registry_hash_stable() -> None:
    first = load_registry(_REGISTRY_DIR).registry_hash
    second = load_registry(_REGISTRY_DIR).registry_hash
    assert first == second


def test_aggregation_behavior_enforced(tmp_path: Path) -> None:
    definitions_path = tmp_path / "metric-definitions.json"
    definitions_path.write_text(
        (_REGISTRY_DIR / "metric-definitions.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    data = json.loads(definitions_path.read_text(encoding="utf-8"))
    data["definitions"][0]["constraints"]["aggregation_behavior"] = "point_in_time_balance"
    definitions_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    for name in ("metric-families.json", "mapping-rules.json"):
        (tmp_path / name).write_text(
            (_REGISTRY_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    broken = load_registry(tmp_path)
    with pytest.raises(RegistryValidationError, match="aggregation_behavior"):
        validate_registry(broken)


def test_issuer_equivalent_rejects_global_scope(tmp_path: Path) -> None:
    for name in ("metric-families.json", "metric-definitions.json"):
        (tmp_path / name).write_text(
            (_REGISTRY_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    rules = {
        "rules": [
            {
                "rule_key": "bad-issuer-equiv",
                "source_concept": {"namespace_uri": "http://example.com/x", "local_name": "A"},
                "target_metric_code": "operating_company_revenue",
                "target_definition_version": 1,
                "relationship_type": "issuer_equivalent",
                "scope_kind": "global",
                "scope": {"kind": "global"},
                "confidence_tier": "high",
                "rationale": "invalid",
                "evidence_snapshot": {"note": "test"},
                "evidence": {
                    "accession_number": "0001065088-24-000036",
                    "bundle_fingerprint": "a" * 64,
                    "projection_version": "arelle-semantic-v1",
                    "arelle_version": "2.43.1",
                    "semantic_config_fingerprint": "b" * 64,
                    "concept": {"namespace_uri": "http://example.com/x", "local_name": "A"},
                },
                "reviewed_by": "test",
                "reviewed_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                "supersedes": None,
            }
        ],
    }
    rules_path = tmp_path / "mapping-rules.json"
    rules_path.write_text(json.dumps(rules, indent=2) + "\n", encoding="utf-8")
    registry = load_registry(tmp_path)
    with pytest.raises(RegistryValidationError, match="issuer_equivalent"):
        validate_registry(registry)


def test_derived_equivalent_rejected_in_v1(tmp_path: Path) -> None:
    for name in ("metric-families.json", "metric-definitions.json"):
        (tmp_path / name).write_text(
            (_REGISTRY_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    rules = {
        "rules": [
            {
                "rule_key": "bad-derived",
                "source_concept": {"namespace_uri": "http://example.com/x", "local_name": "A"},
                "target_metric_code": "operating_company_revenue",
                "target_definition_version": 1,
                "relationship_type": "derived_equivalent",
                "scope_kind": "global",
                "scope": {"kind": "global"},
                "confidence_tier": "high",
                "rationale": "invalid",
                "evidence_snapshot": {"note": "test"},
                "evidence": {
                    "accession_number": "0001065088-24-000036",
                    "bundle_fingerprint": "a" * 64,
                    "projection_version": "arelle-semantic-v1",
                    "arelle_version": "2.43.1",
                    "semantic_config_fingerprint": "b" * 64,
                    "concept": {"namespace_uri": "http://example.com/x", "local_name": "A"},
                },
                "reviewed_by": "test",
                "reviewed_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                "supersedes": None,
            }
        ],
    }
    (tmp_path / "mapping-rules.json").write_text(json.dumps(rules, indent=2) + "\n")
    registry = load_registry(tmp_path)
    with pytest.raises(RegistryValidationError, match="derived_equivalent"):
        validate_registry(registry)


def test_predecessor_chain_order(tmp_path: Path) -> None:
    for name in ("metric-families.json", "metric-definitions.json"):
        (tmp_path / name).write_text(
            (_REGISTRY_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    reviewed_at = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    concept = {"namespace_uri": "http://example.com/x", "local_name": "Revenue"}
    evidence = {
        "accession_number": "0001065088-24-000036",
        "bundle_fingerprint": "a" * 64,
        "projection_version": "arelle-semantic-v1",
        "arelle_version": "2.43.1",
        "semantic_config_fingerprint": "b" * 64,
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
            "reviewed_by": "test",
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


def test_rule_state_superseded() -> None:
    registry = load_registry(_REGISTRY_DIR)
    rules_by_key = {r.rule_key: r for r in registry.rules}
    assert rule_state("missing", rules_by_key) == "current"
