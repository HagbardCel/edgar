"""Quality issues raised during acquisition and replay."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["fatal", "warning", "info"]


@dataclass(frozen=True)
class QualityIssue:
    severity: Severity
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "context": dict(self.context),
        }
