"""Unit tests for Phase 2A metric registry validation and hashing."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from edgar.metrics.registry import (
    ConceptDeclarationCitation,
    EvidenceSnapshot,
    ExpandedQNameRecord,
    GlobalScope,
    IssuerScope,
    MappingRuleRecord,
    RegistryValidationError,
    SourceLocatorRecord,
    SupersedesRef,
    fingerprint_definition,
    fingerprint_family,
    load_registry,
    rule_state,
    validate_registry,
)

_REPO_REGISTRY = Path(__file__).resolve().parents[2] / "semantic-registry"
_BUNDLE_OPAQUE = uuid.uuid4().hex
_FINGERPRINT = "b" * 64


def test_load_and_validate_production_registry() -> None:
    registry = load_registry(_REPO_REGISTRY)
    validate_registry(registry)
    assert len(registry.families) == 11
    assert len(registry.definitions) == 20
    assert len(registry.rules) == 17
    assert len(registry.registry_hash) == 64


def test_family_hash_includes_envelope_version() -> None:
    registry = load_registry(_REPO_REGISTRY)
    family = registry.families[0]
    h1 = fingerprint_family(1, family)
    h2 = fingerprint_family(2, family)
    assert h1 != h2


def test_definition_hash_key_order_independent() -> None:
    registry = load_registry(_REPO_REGISTRY)
    defn = registry.definitions[0]
    h1 = fingerprint_definition(defn)
    payload = json.loads(json.dumps(defn.model_dump(mode="json")))
    reordered = {k: payload[k] for k in reversed(list(payload))}
    defn2 = type(defn).model_validate(reordered)
    assert fingerprint_definition(defn2) == h1


def test_set_reorder_does_not_change_definition_hash() -> None:
    registry = load_registry(_REPO_REGISTRY)
    defn = registry.definitions[0]
    h1 = fingerprint_definition(defn)
    swapped = defn.model_copy(
        update={
            "constraints": defn.constraints.model_copy(
                update={
                    "inclusion_rules": tuple(reversed(defn.constraints.inclusion_rules)),
                }
            )
        }
    )
    assert fingerprint_definition(swapped) == h1


def test_duplicate_inclusion_rules_rejected() -> None:
    registry = load_registry(_REPO_REGISTRY)
    defn = registry.definitions[0]
    dup_rules = defn.constraints.inclusion_rules + (defn.constraints.inclusion_rules[0],)
    bad = defn.model_copy(
        update={
            "constraints": defn.constraints.model_copy(update={"inclusion_rules": dup_rules})
        }
    )
    registry = registry.model_copy(update={"definitions": (bad,) + registry.definitions[1:]})
    with pytest.raises(RegistryValidationError, match="duplicate"):
        validate_registry(registry)


def test_derived_equivalent_rejected_in_registry_data() -> None:
    registry = load_registry(_REPO_REGISTRY)
    rule = _sample_rule(relationship_type="derived_equivalent")
    registry = registry.model_copy(update={"rules": registry.rules + (rule,)})
    with pytest.raises(RegistryValidationError, match="derived_equivalent"):
        validate_registry(registry)


def test_issuer_equivalent_requires_period_or_filing_scope() -> None:
    registry = load_registry(_REPO_REGISTRY)
    rule = _sample_rule(
        relationship_type="issuer_equivalent",
        scope=IssuerScope(cik="0001065088"),
    )
    registry = registry.model_copy(update={"rules": registry.rules + (rule,)})
    with pytest.raises(RegistryValidationError, match="issuer_equivalent"):
        validate_registry(registry)


def test_supersession_cycle_rejected() -> None:
    registry = load_registry(_REPO_REGISTRY)
    a = _sample_rule(rule_key="map-a", supersedes="map-c")
    b = _sample_rule(rule_key="map-b", supersedes="map-a")
    c = _sample_rule(rule_key="map-c", supersedes="map-b")
    registry = registry.model_copy(update={"rules": (a, b, c)})
    with pytest.raises(RegistryValidationError, match="cycle"):
        validate_registry(registry)


def test_rule_state_current_and_superseded() -> None:
    a = _sample_rule(rule_key="map-a")
    b = _sample_rule(rule_key="map-b", supersedes="map-a")
    rules_by_key = {r.rule_key: r for r in (a, b)}
    assert rule_state("map-a", rules_by_key) == "superseded"
    assert rule_state("map-b", rules_by_key) == "current"


def _sample_rule(
    *,
    rule_key: str = "map-test-001",
    relationship_type: str = "equivalent",
    scope: GlobalScope | None = None,
    supersedes: str | None = None,
) -> MappingRuleRecord:
    ns = "http://fasb.org/us-gaap/2023"
    citation = ConceptDeclarationCitation(
        accession_number="0001065088-24-000036",
        filing_bundle_opaque_id=_BUNDLE_OPAQUE,
        xbrl_report_input_ordinal=0,
        projection_version="semantic-v1",
        arelle_version="2.43.1",
        semantic_config_fingerprint=_FINGERPRINT,
        concept=ExpandedQNameRecord(namespace_uri=ns, local_name="Revenues"),
        source_locator=SourceLocatorRecord(
            document_uri="https://example.com/xbrl.htm",
            scheme="xml_id",
            value="f1",
        ),
    )
    scope_obj = scope or GlobalScope()
    return MappingRuleRecord(
        rule_schema_version=1,
        rule_key=rule_key,
        source_concept=ExpandedQNameRecord(namespace_uri=ns, local_name="Revenues"),
        target_metric_code="operating_company_revenue",
        target_definition_version=1,
        relationship_type=relationship_type,  # type: ignore[arg-type]
        scope_kind=scope_obj.kind,
        scope=scope_obj,
        confidence_tier="high",
        rationale="test rationale with sufficient detail",
        evidence_snapshot=EvidenceSnapshot({"labels": ["Revenues"]}),
        evidence_citations=(citation,),
        reviewed_by="human-reviewer",
        reviewed_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
        supersedes=SupersedesRef(rule_key=supersedes) if supersedes else None,
    )
