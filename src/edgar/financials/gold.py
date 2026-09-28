"""Gold assertion loading and comparison."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from edgar.financials.models import Observation

GoldStatus = Literal["value", "missing", "unsupported"]


class GoldPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["duration", "instant"]
    start: str | None = None
    end: str


class GoldAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    accession: str
    metric: str
    period: GoldPeriod
    status: GoldStatus
    numeric: str | None = None
    reason: str | None = None

    @field_validator("numeric", mode="before")
    @classmethod
    def _numeric_str(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)


class GoldFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assertions: tuple[GoldAssertion, ...]


FORBIDDEN_GOLD_KEYS = frozenset(
    {"capability_state", "metric-v2", "definition_hash_scheme", "review_profile"}
)


def load_gold(path: Path) -> GoldFile:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    _reject_forbidden_keys(raw)
    return GoldFile.model_validate(raw)


def _reject_forbidden_keys(raw: Any) -> None:
    if isinstance(raw, dict):
        for key in raw:
            if key in FORBIDDEN_GOLD_KEYS:
                raise ValueError(f"forbidden gold field: {key}")
        for value in raw.values():
            _reject_forbidden_keys(value)
    elif isinstance(raw, list):
        for item in raw:
            _reject_forbidden_keys(item)


def observation_period_matches(assertion: GoldAssertion, obs: Observation) -> bool:
    if assertion.period.kind == "duration":
        return obs.period_start == assertion.period.start and obs.period_end == assertion.period.end
    return obs.period_end == assertion.period.end and obs.period_start is None


def compare_gold(assertion: GoldAssertion, obs: Observation) -> str | None:
    if obs.accession != assertion.accession or obs.metric != assertion.metric:
        return "accession/metric mismatch"
    if obs.status != assertion.status:
        return f"status {obs.status!r} != {assertion.status!r}"
    if assertion.status == "value":
        if not observation_period_matches(assertion, obs):
            return "period mismatch"
        expected = Decimal(assertion.numeric) if assertion.numeric is not None else None
        if obs.numeric != expected:
            return f"numeric {obs.numeric!r} != {expected!r}"
        return None
    if assertion.status == "missing":
        if not observation_period_matches(assertion, obs):
            return "period mismatch"
        if obs.numeric is not None:
            return "numeric must be null for missing"
        if (obs.reason or None) != (assertion.reason or None):
            return f"reason {obs.reason!r} != {assertion.reason!r}"
        return None
    if assertion.status == "unsupported":
        if assertion.reason == "wrong_form":
            if (obs.reason or None) != assertion.reason:
                return f"reason {obs.reason!r} != {assertion.reason!r}"
            return None
        if not observation_period_matches(assertion, obs):
            return "period mismatch"
        if obs.numeric is not None:
            return "numeric must be null"
        if (obs.reason or None) != (assertion.reason or None):
            return f"reason {obs.reason!r} != {assertion.reason!r}"
        return None
    return "unknown gold status"
