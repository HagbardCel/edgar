"""Synthetic metric registry fixtures for unit/integration tests."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from edgar.metrics.registry import LoadedRegistry, load_registry, validate_registry
from edgar.xbrl.arelle_env import arelle_version

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REGISTRY = _REPO_ROOT / "semantic-registry"


def copy_registry_skeleton(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("metric-families.json", "metric-definitions.json", "mapping-rules.json"):
        shutil.copy2(_DEFAULT_REGISTRY / name, dest / name)
    return dest


def build_test_mapping_rules(
    *,
    bundle_fingerprint: str,
    semantic_config_fingerprint: str,
    accession: str = "0000000001-00-000001",
) -> dict[str, object]:
    reviewed_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC).isoformat()
    return {
        "registry_schema_version": 1,
        "rules": [
            {
                "rule_schema_version": 1,
                "rule_key": "map-test-equivalent",
                "source_concept": {
                    "namespace_uri": "http://example.com/test",
                    "local_name": "Assets",
                },
                "target_metric_code": "cash_and_cash_equivalents",
                "target_definition_version": 1,
                "relationship_type": "equivalent",
                "scope_kind": "global",
                "scope": {"kind": "global"},
                "confidence_tier": "high",
                "rationale": "Integration test: synthetic Assets maps to cash metric contract.",
                "evidence_snapshot": {"note": "synthetic integration fixture"},
                "evidence": {
                    "accession_number": accession,
                    "bundle_fingerprint": bundle_fingerprint,
                    "projection_version": "arelle-semantic-v1",
                    "arelle_version": arelle_version(),
                    "semantic_config_fingerprint": semantic_config_fingerprint,
                    "concept": {
                        "namespace_uri": "http://example.com/test",
                        "local_name": "Assets",
                    },
                },
                "reviewed_by": "integration-test",
                "reviewed_at": reviewed_at,
                "supersedes": None,
            },
            {
                "rule_schema_version": 1,
                "rule_key": "map-test-incompatible",
                "source_concept": {
                    "namespace_uri": "http://example.com/test",
                    "local_name": "Assets",
                },
                "target_metric_code": "diluted_eps",
                "target_definition_version": 1,
                "relationship_type": "incompatible",
                "scope_kind": "filing",
                "scope": {"kind": "filing", "accession_number": accession},
                "confidence_tier": "high",
                "rationale": "Instant monetary stock concept is incompatible with EPS.",
                "evidence_snapshot": {"note": "synthetic integration fixture"},
                "evidence": {
                    "accession_number": accession,
                    "bundle_fingerprint": bundle_fingerprint,
                    "projection_version": "arelle-semantic-v1",
                    "arelle_version": arelle_version(),
                    "semantic_config_fingerprint": semantic_config_fingerprint,
                    "concept": {
                        "namespace_uri": "http://example.com/test",
                        "local_name": "Assets",
                    },
                },
                "reviewed_by": "integration-test",
                "reviewed_at": reviewed_at,
                "supersedes": None,
            },
            {
                "rule_schema_version": 1,
                "rule_key": "map-test-issuer-period",
                "source_concept": {
                    "namespace_uri": "http://example.com/test",
                    "local_name": "Assets",
                },
                "target_metric_code": "cash_and_cash_equivalents",
                "target_definition_version": 1,
                "relationship_type": "issuer_equivalent",
                "scope_kind": "issuer_period",
                "scope": {
                    "kind": "issuer_period",
                    "cik": "0000000001",
                    "report_period_from": "2024-01-01",
                    "report_period_through": "2024-12-31",
                },
                "confidence_tier": "medium",
                "rationale": "Issuer-period scoped issuer_equivalent for integration coverage.",
                "evidence_snapshot": {"note": "synthetic integration fixture"},
                "evidence": {
                    "accession_number": accession,
                    "bundle_fingerprint": bundle_fingerprint,
                    "projection_version": "arelle-semantic-v1",
                    "arelle_version": arelle_version(),
                    "semantic_config_fingerprint": semantic_config_fingerprint,
                    "concept": {
                        "namespace_uri": "http://example.com/test",
                        "local_name": "Assets",
                    },
                },
                "reviewed_by": "integration-test",
                "reviewed_at": reviewed_at,
                "supersedes": None,
            },
        ],
    }


def write_test_registry_with_rules(
    dest: Path,
    *,
    bundle_fingerprint: str,
    semantic_config_fingerprint: str,
    accession: str = "0000000001-00-000001",
) -> LoadedRegistry:
    copy_registry_skeleton(dest)
    rules_doc = build_test_mapping_rules(
        bundle_fingerprint=bundle_fingerprint,
        semantic_config_fingerprint=semantic_config_fingerprint,
        accession=accession,
    )
    rules_path = dest / "mapping-rules.json"
    rules_path.write_text(json.dumps(rules_doc, indent=2) + "\n", encoding="utf-8")
    registry = load_registry(dest)
    validate_registry(registry)
    return registry
