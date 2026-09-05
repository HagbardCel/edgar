"""Pydantic contract for Git-authoritative canonical metrics (Phase 2C)."""

from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

MetricKind = Literal["reported"]
Statement = Literal[
    "income_statement",
    "balance_sheet",
    "cash_flow",
    "per_share",
    "shares",
]
PeriodType = Literal["instant", "duration"]
ValueKind = Literal["numeric"]
UnitDimension = Literal["monetary", "shares", "monetary_per_share"]

METRIC_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

_STATEMENT_MATRIX: dict[Statement, tuple[frozenset[PeriodType], UnitDimension]] = {
    "income_statement": (frozenset({"duration"}), "monetary"),
    "balance_sheet": (frozenset({"instant"}), "monetary"),
    "cash_flow": (frozenset({"duration"}), "monetary"),
    "per_share": (frozenset({"duration"}), "monetary_per_share"),
    "shares": (frozenset({"instant", "duration"}), "shares"),
}


class RegistryValidationError(ValueError):
    """Raised when the canonical metric YAML fails contract validation."""


def _non_empty_str(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be non-empty")
    return stripped


class CanonicalMetric(BaseModel):
    """Governed canonical metric definition. ``key`` is semantic identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    name: str
    kind: MetricKind
    statement: Statement
    period_type: PeriodType
    value_kind: ValueKind
    unit_dimension: UnitDimension
    definition: str
    includes: tuple[str, ...] = Field(min_length=1)
    excludes: tuple[str, ...] = Field(min_length=1)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        key = _non_empty_str(value, "key")
        if METRIC_KEY_PATTERN.fullmatch(key) is None:
            raise ValueError(f"malformed metric key: {value!r}")
        return key

    @field_validator("name", "definition")
    @classmethod
    def _required_text(cls, value: str, info: ValidationInfo) -> str:
        return _non_empty_str(value, str(info.field_name))

    @field_validator("includes", "excludes")
    @classmethod
    def _contract_lists(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        field_name = str(info.field_name)
        cleaned: list[str] = []
        seen: set[str] = set()
        for entry in value:
            item = _non_empty_str(entry, field_name)
            if item in seen:
                raise ValueError(f"duplicate entries in {field_name}")
            seen.add(item)
            cleaned.append(item)
        if not cleaned:
            raise ValueError(f"{field_name} must be non-empty")
        return tuple(cleaned)

    @model_validator(mode="after")
    def _statement_matrix(self) -> Self:
        allowed_periods, unit = _STATEMENT_MATRIX[self.statement]
        if self.period_type not in allowed_periods:
            raise ValueError(
                f"{self.key}: statement {self.statement!r} requires period_type in "
                f"{sorted(allowed_periods)}, got {self.period_type!r}"
            )
        if self.unit_dimension != unit:
            raise ValueError(
                f"{self.key}: statement {self.statement!r} requires unit_dimension "
                f"{unit!r}, got {self.unit_dimension!r}"
            )
        if self.kind != "reported":
            raise ValueError(f"{self.key}: kind must be 'reported'")
        if self.value_kind != "numeric":
            raise ValueError(f"{self.key}: value_kind must be 'numeric'")
        return self
