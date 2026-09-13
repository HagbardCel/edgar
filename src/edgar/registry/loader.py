"""Load and validate ``registry/metrics.yml``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from edgar.registry.hashing import (
    definition_hash,
    duplicate_payload_signature,
    semantic_registry_hash,
)
from edgar.registry.models import CanonicalMetric, RegistryValidationError

METRICS_FILENAME = "metrics.yml"
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_DIR = _REPO_ROOT / "registry"


@dataclass(frozen=True)
class LoadedCanonicalRegistry:
    """Validated canonical metrics plus the semantic registry hash."""

    metrics: tuple[CanonicalMetric, ...]
    semantic_registry_hash: str
    path: Path

    def by_key(self) -> dict[str, CanonicalMetric]:
        return {metric.key: metric for metric in self.metrics}

    def get(self, key: str) -> CanonicalMetric | None:
        return self.by_key().get(key)


def default_metrics_path(registry_dir: Path | None = None) -> Path:
    directory = registry_dir if registry_dir is not None else DEFAULT_REGISTRY_DIR
    return directory / METRICS_FILENAME


def load_canonical_registry(registry_dir: Path | None = None) -> LoadedCanonicalRegistry:
    path = default_metrics_path(registry_dir)
    return load_metrics_yml(path)


def load_metrics_yml(path: Path) -> LoadedCanonicalRegistry:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RegistryValidationError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise RegistryValidationError(f"{path} must be a mapping with a 'metrics' list")
    unknown = set(raw) - {"metrics"}
    if unknown:
        raise RegistryValidationError(f"{path} has unknown top-level fields: {sorted(unknown)}")
    metrics_raw = raw.get("metrics")
    if not isinstance(metrics_raw, list) or not metrics_raw:
        raise RegistryValidationError(f"{path}: metrics must be a non-empty list")

    metrics: list[CanonicalMetric] = []
    keys: set[str] = set()
    payload_owners: dict[str, str] = {}
    errors: list[str] = []
    for index, item in enumerate(metrics_raw):
        prefix = f"metrics[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{prefix} must be a mapping")
            continue
        try:
            metric = CanonicalMetric.model_validate(item)
        except Exception as exc:
            errors.append(f"{prefix}: {exc}")
            continue
        if metric.key in keys:
            errors.append(f"duplicate metric key: {metric.key}")
        keys.add(metric.key)
        signature = duplicate_payload_signature(metric)
        owner = payload_owners.get(signature)
        if owner is not None:
            errors.append(f"exact duplicate definition payload: {owner!r} and {metric.key!r}")
        else:
            payload_owners[signature] = metric.key
        metrics.append(metric)

    if errors:
        raise RegistryValidationError("; ".join(errors))

    ordered = tuple(sorted(metrics, key=lambda item: item.key))
    return LoadedCanonicalRegistry(
        metrics=ordered,
        semantic_registry_hash=semantic_registry_hash(ordered),
        path=path,
    )


def metric_list_payload(registry: LoadedCanonicalRegistry) -> dict[str, Any]:
    return {
        "count": len(registry.metrics),
        "metrics": [
            {
                "definition_hash": definition_hash(metric),
                "key": metric.key,
                "kind": metric.kind,
                "name": metric.name,
                "period_type": metric.period_type,
                "statement": metric.statement,
                "unit_dimension": metric.unit_dimension,
                "value_kind": metric.value_kind,
            }
            for metric in registry.metrics
        ],
        "semantic_registry_hash": registry.semantic_registry_hash,
    }


def metric_show_payload(
    registry: LoadedCanonicalRegistry, metric: CanonicalMetric
) -> dict[str, Any]:
    dumped = metric.model_dump(mode="json")
    dumped["definition_hash"] = definition_hash(metric)
    return {
        "count": 1,
        "metrics": [dumped],
        "semantic_registry_hash": registry.semantic_registry_hash,
    }
