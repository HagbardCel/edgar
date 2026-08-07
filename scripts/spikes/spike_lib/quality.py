"""Structured quality issues for spikes (JSON now; PostgreSQL later)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Severity = Literal["fatal", "warning", "info"]


@dataclass(frozen=True)
class QualityIssue:
    severity: Severity
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
