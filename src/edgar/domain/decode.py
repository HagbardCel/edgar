"""Strict JSON-type decoding helpers for schema-v1 FilingBundle descriptors.

Persisted descriptors are never repaired: exact JSON types and exact key sets
are required. Booleans must be checked with ``type(x) is bool`` because
``bool`` is a subclass of ``int``.
"""

from __future__ import annotations

from collections.abc import Mapping, Set
from datetime import date, datetime
from typing import Any


class BundleDecodeError(ValueError):
    """Raised when a persisted bundle descriptor fails strict decoding."""


def require_object(value: object, *, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise BundleDecodeError(f"{label} must be a JSON object, got {type(value).__name__}")
    return value  # type: ignore[return-value]


def require_exact_keys(data: Mapping[str, Any], keys: Set[str], *, label: str) -> None:
    actual = set(data)
    missing = keys - actual
    if missing:
        raise BundleDecodeError(f"{label} missing fields: {sorted(missing)}")
    unknown = actual - keys
    if unknown:
        raise BundleDecodeError(f"{label} has unknown fields: {sorted(unknown)}")


def require_str(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise BundleDecodeError(f"{label} must be a JSON string, got {type(value).__name__}")
    return value


def require_bool(value: object, *, label: str) -> bool:
    if type(value) is not bool:
        raise BundleDecodeError(f"{label} must be a JSON boolean, got {type(value).__name__}")
    return value


def require_int(value: object, *, label: str) -> int:
    if type(value) is not int:
        raise BundleDecodeError(f"{label} must be a JSON integer, got {type(value).__name__}")
    return value


def require_list(value: object, *, label: str) -> list[Any]:
    if type(value) is not list:
        raise BundleDecodeError(f"{label} must be a JSON array, got {type(value).__name__}")
    return value


def require_list_of_str(value: object, *, label: str) -> list[str]:
    items = require_list(value, label=label)
    out: list[str] = []
    for i, item in enumerate(items):
        out.append(require_str(item, label=f"{label}[{i}]"))
    return out


def require_nullable_str(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return require_str(value, label=label)


def require_canonical_date(value: object, *, label: str) -> date:
    raw = require_str(value, label=label)
    if raw == "":
        raise BundleDecodeError(f"{label} must not be empty")
    parsed = date.fromisoformat(raw)
    if parsed.isoformat() != raw:
        raise BundleDecodeError(f"{label} is not canonical ISO date: {raw!r}")
    return parsed


def require_canonical_datetime(value: object, *, label: str) -> datetime:
    raw = require_str(value, label=label)
    if raw == "":
        raise BundleDecodeError(f"{label} must not be empty")
    parsed = datetime.fromisoformat(raw)
    if parsed.isoformat() != raw:
        raise BundleDecodeError(f"{label} is not canonical ISO datetime: {raw!r}")
    return parsed


def require_nullable_canonical_date(value: object, *, label: str) -> date | None:
    if value is None:
        return None
    return require_canonical_date(value, label=label)


def require_nullable_canonical_datetime(value: object, *, label: str) -> datetime | None:
    if value is None:
        return None
    return require_canonical_datetime(value, label=label)
