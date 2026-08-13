"""Unit tests for Git metric registry validation and hashing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from edgar.metrics.registry import (
    RegistryValidationError,
    load_registry,
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
    data["definitions"][0]["constraints"]["aggregation_behavior"] = "invalid"
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
        "registry_schema_version": 1,
        "rules": [
            {
                "rule_schema_version": 1,
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


def test_rule_state_superseded() -> None:
    from edgar.metrics.registry import RulesFile

    rules_file = RulesFile.model_validate(
        json.loads((_REGISTRY_DIR / "mapping-rules.json").read_text(encoding="utf-8"))
    )
    rules_by_key = {r.rule_key: r for r in rules_file.rules}
    assert rule_state("missing", rules_by_key) == "current"
