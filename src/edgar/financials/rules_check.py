"""Validate Git decision records (edgar rules check)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar.financials.cohort import load_m0_cohort
from edgar.financials.decisions import load_decisions


@dataclass(frozen=True)
class RulesCheckFinding:
    level: str
    message: str


def run_rules_check(registry_dir: Path) -> tuple[RulesCheckFinding, ...]:
    findings: list[RulesCheckFinding] = []
    registry = load_decisions(registry_dir, fatal_stale_accepted=False)
    cohort = load_m0_cohort(registry_dir)
    for metric in cohort.metrics:
        exact = [
            ld
            for ld in registry.decisions
            if not ld.stale_inactive
            and ld.record.status == "accepted"
            and ld.record.relation == "exact"
            and ld.record.metric == metric
        ]
        if not exact:
            findings.append(
                RulesCheckFinding("error", f"m0 metric {metric!r} has no accepted exact decision")
            )
    for ld in registry.decisions:
        if ld.stale_inactive and ld.record.status == "accepted":
            findings.append(
                RulesCheckFinding(
                    "warning",
                    f"stale accepted decision needs review: {ld.record.id}",
                )
            )
        if ld.record.status == "rejected" and ld.stale_inactive:
            findings.append(
                RulesCheckFinding(
                    "warning",
                    f"stale rejected decision inactive history: {ld.record.id}",
                )
            )
    return tuple(findings)
