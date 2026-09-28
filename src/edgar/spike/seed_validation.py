"""Validate issuer seeds against SEC submissions metadata."""

from __future__ import annotations

from typing import Any


class SeedValidationError(ValueError):
    """Submissions metadata does not match the curated seed."""


def submissions_entity_name(payload: dict[str, Any]) -> str:
    name = payload.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


def validate_seed_identity(
    payload: dict[str, Any],
    *,
    cik: str,
    expected_name: str | None,
) -> None:
    """Fail closed when the SEC entity name does not match the seed."""
    if not expected_name:
        return
    actual = submissions_entity_name(payload).upper()
    expected = expected_name.strip().upper()
    if not actual:
        raise SeedValidationError(f"CIK {cik}: submissions payload has no entity name")
    if expected not in actual and actual not in expected:
        raise SeedValidationError(
            f"CIK {cik}: expected entity name containing '{expected_name}', got '{actual}'",
        )
