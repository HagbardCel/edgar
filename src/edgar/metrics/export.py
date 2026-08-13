"""Audit report rendering for mapping rules (derived; Git-authoritative source)."""

from __future__ import annotations

import json
from typing import Any

from edgar.metrics.registry import MappingRuleRecord, RuleState, rule_state


def mapping_rule_audit_payload(
    rule: MappingRuleRecord,
    *,
    state: RuleState,
    supersession_chain: tuple[MappingRuleRecord, ...],
    registry_hash: str,
    pinned_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rule_key": rule.rule_key,
        "state": state,
        "registry_hash": registry_hash,
        "source_concept": rule.source_concept.model_dump(),
        "target_metric": {
            "metric_code": rule.target_metric_code,
            "definition_version": rule.target_definition_version,
        },
        "relationship_type": rule.relationship_type,
        "scope": rule.scope.model_dump(),
        "scope_kind": rule.scope_kind,
        "confidence_tier": rule.confidence_tier,
        "rationale": rule.rationale,
        "reviewed_by": rule.reviewed_by,
        "reviewed_at": rule.reviewed_at.isoformat(),
        "evidence_snapshot": dict(rule.evidence_snapshot.root),
        "evidence": rule.evidence.model_dump(),
        "supersedes": None if rule.supersedes is None else rule.supersedes.model_dump(),
        "supersession_chain": [r.rule_key for r in supersession_chain],
    }
    if pinned_evidence is not None:
        payload["pinned_evidence_enrichment"] = pinned_evidence
    return payload


def mapping_rule_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload['rule_key']}",
        "",
        f"**State:** {payload['state']}",
        "",
        "## Source",
        "",
        f"QName: `{payload['source_concept']['namespace_uri']}`"
        f"`{payload['source_concept']['local_name']}`",
        "",
        "## Target",
        "",
        f"{payload['target_metric']['metric_code']}@"
        f"{payload['target_metric']['definition_version']}",
        "",
        "## Scope (metadata only; applicability is Phase 2B)",
        "",
        "```json",
        json.dumps(payload["scope"], indent=2, sort_keys=True),
        "```",
        "",
        "## Rationale",
        "",
        str(payload["rationale"]),
        "",
    ]
    if "pinned_evidence_enrichment" in payload:
        enrichment = payload["pinned_evidence_enrichment"]
        lines.extend(
            [
                "## Pinned projection evidence",
                "",
                f"Facts in pinned projection: {len(enrichment.get('fact_occurrences', []))}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def export_registry_audit(
    *,
    registry_hash: str,
    rules: tuple[MappingRuleRecord, ...],
) -> list[dict[str, Any]]:
    rules_by_key = {rule.rule_key: rule for rule in rules}
    reports: list[dict[str, Any]] = []
    for rule in sorted(rules, key=lambda r: r.rule_key):
        chain: list[MappingRuleRecord] = []
        current_key = rule.rule_key
        while True:
            chain.append(rules_by_key[current_key])
            predecessors = [
                r
                for r in rules
                if r.supersedes is not None and r.supersedes.rule_key == current_key
            ]
            if not predecessors:
                break
            current_key = predecessors[0].rule_key
        reports.append(
            mapping_rule_audit_payload(
                rule,
                state=rule_state(rule.rule_key, rules_by_key),
                supersession_chain=tuple(reversed(chain)),
                registry_hash=registry_hash,
            )
        )
    return reports
