"""Deterministic hashes for canonical metric definitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from edgar.registry.models import CanonicalMetric

DEFINITION_HASH_FIELDS: tuple[str, ...] = (
    "key",
    "kind",
    "statement",
    "period_type",
    "value_kind",
    "unit_dimension",
    "definition",
    "includes",
    "excludes",
)
DUPLICATE_PAYLOAD_FIELDS: tuple[str, ...] = (
    "kind",
    "statement",
    "period_type",
    "value_kind",
    "unit_dimension",
    "definition",
    "includes",
    "excludes",
)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sorted_strings(values: Sequence[str]) -> list[str]:
    return sorted(values)


def _payload(metric: CanonicalMetric, fields: Sequence[str]) -> dict[str, Any]:
    dumped = metric.model_dump(mode="json")
    payload: dict[str, Any] = {}
    for field in fields:
        value = dumped[field]
        if field in {"includes", "excludes"}:
            payload[field] = _sorted_strings(value)
        else:
            payload[field] = value
    return payload


def definition_hash(metric: CanonicalMetric) -> str:
    """Mapping-review hash. Includes ``key``; excludes ``name``."""
    return sha256_hex(canonical_json_bytes(_payload(metric, DEFINITION_HASH_FIELDS)))


def duplicate_payload_signature(metric: CanonicalMetric) -> str:
    """Duplicate-contract signature. Excludes ``key`` and ``name``."""
    return sha256_hex(canonical_json_bytes(_payload(metric, DUPLICATE_PAYLOAD_FIELDS)))


def semantic_registry_hash(metrics: Sequence[CanonicalMetric]) -> str:
    """Hash of sorted per-metric definition hashes. Unchanged by name-only edits."""
    hashes = sorted(definition_hash(metric) for metric in metrics)
    return sha256_hex(canonical_json_bytes(hashes))
