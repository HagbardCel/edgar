"""Load P1 m0 cohort definition."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class M0Cohort(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: tuple[str, ...] = Field(min_length=1)
    slots: tuple[str, ...] = Field(min_length=1)


M0_METRICS_ORDER: tuple[str, ...] = (
    "revenue",
    "total_assets",
    "operating_cash_flow",
    "operating_income",
    "research_and_development",
    "net_income_attributable_to_parent",
    "cash_excluding_restricted_cash",
    "cash_purchases_of_ppe",
)


def load_m0_cohort(registry_dir: Path) -> M0Cohort:
    path = registry_dir / "gold" / "cohorts" / "m0.yml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cohort = M0Cohort.model_validate(raw)
    if tuple(cohort.metrics) != M0_METRICS_ORDER:
        raise ValueError("m0 cohort metrics must match frozen P1 order")
    return cohort
