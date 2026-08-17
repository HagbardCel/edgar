"""Audit report rendering for mapping rules (derived; Git-authoritative source)."""

from __future__ import annotations

import json
from typing import Any

from edgar.metrics.registry import MappingRuleRecord, RuleState, predecessor_chain, rule_state


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
        "scope": rule.scope.model_dump(mode="json"),
        "scope_kind": rule.scope_kind,
        "confidence_tier": rule.confidence_tier,
        "rationale": rule.rationale,
        "reviewed_by": rule.reviewed_by,
        "reviewed_at": rule.reviewed_at.isoformat(),
        "evidence_snapshot": dict(rule.evidence_snapshot.root),
        "evidence": rule.evidence.model_dump(mode="json"),
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
        f"**Registry hash:** `{payload['registry_hash']}`",
        "",
        "## Relationship",
        "",
        f"- Type: `{payload['relationship_type']}`",
        f"- Confidence: `{payload['confidence_tier']}`",
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
        f"Scope kind: `{payload['scope_kind']}`",
        "",
        "```json",
        json.dumps(payload["scope"], indent=2, sort_keys=True),
        "```",
        "",
        "## Review",
        "",
        f"- Reviewed by: {payload['reviewed_by']}",
        f"- Reviewed at: {payload['reviewed_at']}",
        "",
        "## Rationale",
        "",
        str(payload["rationale"]),
        "",
        "## Evidence snapshot",
        "",
        "```json",
        json.dumps(payload["evidence_snapshot"], indent=2, sort_keys=True),
        "```",
        "",
        "## Pinned source evidence",
        "",
        "```json",
        json.dumps(payload["evidence"], indent=2, sort_keys=True),
        "```",
        "",
    ]
    if payload.get("supersedes") is not None:
        lines.extend(
            [
                "## Supersedes",
                "",
                f"Predecessor rule: `{payload['supersedes']['rule_key']}`",
                "",
            ]
        )
    if payload.get("supersession_chain"):
        lines.extend(
            [
                "## Predecessor chain",
                "",
                ", ".join(f"`{key}`" for key in payload["supersession_chain"]),
                "",
            ]
        )
    if "pinned_evidence_enrichment" in payload:
        enrichment = payload["pinned_evidence_enrichment"]
        reports = enrichment.get("reports") or []
        total_facts = sum(len(r.get("fact_occurrences") or []) for r in reports)
        lines.extend(
            [
                "## Pinned evidence enrichment",
                "",
                f"Reports matching pin: {len(reports)}",
                f"Total fact occurrences across reports: {total_facts}",
                "",
                "```json",
                json.dumps(enrichment, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def export_registry_audit(
    *,
    registry_hash: str,
    rules: tuple[MappingRuleRecord, ...],
) -> dict[str, Any]:
    rules_by_key = {rule.rule_key: rule for rule in rules}
    reports: list[dict[str, Any]] = []
    for rule in sorted(rules, key=lambda r: r.rule_key):
        chain = predecessor_chain(rule.rule_key, rules_by_key)
        reports.append(
            mapping_rule_audit_payload(
                rule,
                state=rule_state(rule.rule_key, rules_by_key),
                supersession_chain=chain,
                registry_hash=registry_hash,
            )
        )
    return {
        "registry_hash": registry_hash,
        "reports": reports,
        "count": len(reports),
    }


def export_registry_audit_markdown(
    *,
    registry_hash: str,
    rules: tuple[MappingRuleRecord, ...],
) -> str:
    envelope = export_registry_audit(registry_hash=registry_hash, rules=rules)
    header = [
        "# Mapping audit ledger",
        "",
        f"Registry hash: `{envelope['registry_hash']}`",
        f"Rules: {envelope['count']}",
        "",
    ]
    bodies = [mapping_rule_markdown(report) for report in envelope["reports"]]
    if not bodies:
        return "\n".join(header)
    return "\n".join(header) + "\n" + "\n".join(bodies)
