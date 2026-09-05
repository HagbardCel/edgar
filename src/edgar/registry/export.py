"""Deterministic mapping-report export (JSON, JSONL, Markdown) and JSON Schema."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from edgar.registry.views import MappingAssertionView, MappingReport

SCHEMA_RELATIVE_PATH = Path("registry/schema/mapping-report.schema.json")


def report_to_jsonable(report: MappingReport) -> dict[str, Any]:
    return report.model_dump(mode="json")


def dump_json(reports: Sequence[MappingReport]) -> str:
    payload = {
        "assertions": [report_to_jsonable(report) for report in reports],
        "count": len(reports),
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def dump_jsonl(reports: Sequence[MappingReport]) -> str:
    lines = [
        json.dumps(report_to_jsonable(report), sort_keys=True, ensure_ascii=False)
        for report in reports
    ]
    return ("\n".join(lines) + "\n") if lines else ""


def dump_markdown(reports: Sequence[MappingReport]) -> str:
    lines = [
        "# Mapping assertions",
        "",
        f"Current revisions: {len(reports)}",
        "",
    ]
    for report in reports:
        mapping = report.mapping
        currency = (
            "current" if report.is_current else f"superseded; current={report.current_revision_id}"
        )
        lines.extend(
            [
                f"## {mapping.id} {mapping.source_concept} → {mapping.target_metric_key}",
                "",
                f"- status: `{mapping.status}` ({currency})",
                f"- relation: `{mapping.relation}`",
                f"- scope: `{mapping.scope.kind}`"
                + (f" issuer={mapping.scope.issuer_cik}" if mapping.scope.issuer_cik else ""),
                f"- target_definition_hash: `{mapping.target_definition_hash}`",
                f"- yaml_definition_hash: `{report.yaml_definition_hash}`",
                f"- definition_changed: `{str(report.definition_changed).lower()}`",
                f"- method: `{mapping.method}` created_by={mapping.created_by}",
                f"- affected_facts: {report.affected_fact_summary.count}",
            ]
        )
        if mapping.rationale:
            lines.append(f"- rationale: {mapping.rationale}")
        lines.append("- history:")
        for item in report.history:
            lines.append(_history_line(item))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _history_line(item: MappingAssertionView) -> str:
    return f"  - {item.id} `{item.status}` {item.created_at.isoformat()} {item.created_by}"


def mapping_report_json_schema() -> dict[str, Any]:
    return MappingReport.model_json_schema(mode="serialization")


def mapping_report_schema_text() -> str:
    return json.dumps(mapping_report_json_schema(), indent=2, sort_keys=True) + "\n"
