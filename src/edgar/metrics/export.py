"""Audit report rendering for mapping rules (derived output; not authoritative)."""

from __future__ import annotations

import json
from typing import Any

from edgar.db.metrics import MappingRuleRow, SourceFactOccurrence
from edgar.metrics.registry import MappingRuleRecord


def mapping_rule_audit_payload(
    row: MappingRuleRow,
    *,
    supersession_chain: tuple[MappingRuleRecord, ...],
    source_occurrences: tuple[SourceFactOccurrence, ...],
) -> dict[str, Any]:
    rule = row.rule
    return {
        "rule_key": rule.rule_key,
        "state": row.state,
        "source_concept": rule.source_concept.model_dump(),
        "target_metric": {
            "metric_code": rule.target_metric_code,
            "definition_version": rule.target_definition_version,
        },
        "relationship_type": rule.relationship_type,
        "scope": rule.scope.model_dump(),
        "confidence_tier": rule.confidence_tier,
        "rationale": rule.rationale,
        "reviewed_by": rule.reviewed_by,
        "reviewed_at": rule.reviewed_at.isoformat(),
        "evidence_snapshot": dict(rule.evidence_snapshot.root),
        "evidence_citations": [c.model_dump() for c in rule.evidence_citations],
        "supersession_chain": [r.rule_key for r in supersession_chain],
        "source_fact_occurrences": {
            "label": (
                "source fact occurrences covered by the concept/rule scope "
                "(not canonical observations)"
            ),
            "count": len(source_occurrences),
            "sample": [
                {
                    "fact_id": occ.fact_id,
                    "semantic_projection_id": occ.semantic_projection_id,
                    "value_status": occ.value_status,
                    "raw_lexical_value": occ.raw_lexical_value,
                    "source_document_uri": occ.source_document_uri,
                    "source_locator_scheme": occ.source_locator_scheme,
                    "source_locator_value": occ.source_locator_value,
                }
                for occ in source_occurrences
            ],
        },
    }


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
        "## Decision",
        "",
        str(payload["relationship_type"]),
        "",
        "## Scope",
        "",
        "```json",
        json.dumps(payload["scope"], indent=2, sort_keys=True),
        "```",
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
        "## Source occurrences",
        "",
        f"_{payload['source_fact_occurrences']['label']}_",
        "",
        f"Count: {payload['source_fact_occurrences']['count']}",
        "",
    ]
    for occ in payload["source_fact_occurrences"]["sample"]:
        lines.append(
            f"- fact_id={occ['fact_id']} value={occ['raw_lexical_value']!r} "
            f"status={occ['value_status']}"
        )
    return "\n".join(lines) + "\n"
