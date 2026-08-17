"""Unit tests for the Phase 2C canonical metric YAML contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from edgar.registry.hashing import (
    definition_hash,
    duplicate_payload_signature,
    semantic_registry_hash,
)
from edgar.registry.loader import load_metrics_yml
from edgar.registry.models import CanonicalMetric, RegistryValidationError

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PRODUCTION_YML = _REPO_ROOT / "registry" / "metrics.yml"

EXPECTED_CANONICAL_METRIC_KEYS = frozenset(
    {
        "revenue",
        "cost_of_revenue",
        "gross_profit",
        "research_and_development",
        "selling_general_administrative",
        "operating_expenses",
        "operating_income",
        "interest_expense",
        "pretax_income",
        "income_tax_expense",
        "net_income",
        "net_income_attributable_to_parent",
        "cash_and_cash_equivalents",
        "short_term_investments",
        "accounts_receivable",
        "inventory",
        "current_assets",
        "property_plant_equipment_net",
        "goodwill",
        "intangible_assets_net",
        "total_assets",
        "accounts_payable",
        "current_liabilities",
        "short_term_debt",
        "long_term_debt",
        "total_liabilities",
        "shareholders_equity",
        "operating_cash_flow",
        "capital_expenditure",
        "depreciation_and_amortization",
        "investing_cash_flow",
        "financing_cash_flow",
        "dividends_paid",
        "share_repurchases",
        "basic_eps",
        "diluted_eps",
        "weighted_average_shares_basic",
        "weighted_average_shares_diluted",
        "shares_outstanding",
    }
)


def _metric_dict(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "key": "revenue",
        "name": "Revenue",
        "kind": "reported",
        "statement": "income_statement",
        "period_type": "duration",
        "value_kind": "numeric",
        "unit_dimension": "monetary",
        "definition": "Ordinary operating revenue before operating expenses.",
        "includes": ["sales of goods", "service revenue"],
        "excludes": ["gross profit", "billings"],
    }
    payload.update(overrides)
    return payload


def _write_yml(path: Path, metrics: list[dict[str, Any]]) -> Path:
    file_path = path / "metrics.yml"
    file_path.write_text(
        yaml.safe_dump({"metrics": metrics}, sort_keys=False),
        encoding="utf-8",
    )
    return file_path


def test_production_registry_loads_all_expected_keys() -> None:
    loaded = load_metrics_yml(_PRODUCTION_YML)
    keys = {metric.key for metric in loaded.metrics}
    assert keys == EXPECTED_CANONICAL_METRIC_KEYS
    assert len(loaded.metrics) == 39
    assert len(loaded.semantic_registry_hash) == 64
    for metric in loaded.metrics:
        assert metric.kind == "reported"
        assert metric.value_kind == "numeric"
        assert metric.includes
        assert metric.excludes
        assert metric.definition.strip()
        assert len(definition_hash(metric)) == 64


def test_duplicate_key_rejected(tmp_path: Path) -> None:
    first = _metric_dict()
    second = _metric_dict(name="Also revenue", definition="A different sentence.")
    path = _write_yml(tmp_path, [first, second])
    with pytest.raises(RegistryValidationError, match="duplicate metric key"):
        load_metrics_yml(path)


def test_invalid_key_rejected() -> None:
    with pytest.raises(ValueError, match="malformed metric key"):
        CanonicalMetric.model_validate(_metric_dict(key="Revenue"))
    with pytest.raises(ValueError, match="malformed metric key"):
        CanonicalMetric.model_validate(_metric_dict(key="1revenue"))


def test_unknown_enum_rejected() -> None:
    with pytest.raises(ValueError):
        CanonicalMetric.model_validate(_metric_dict(kind="derived"))
    with pytest.raises(ValueError):
        CanonicalMetric.model_validate(_metric_dict(statement="notes"))


def test_unknown_yaml_field_rejected(tmp_path: Path) -> None:
    payload = _metric_dict()
    payload["family"] = "revenue"
    path = _write_yml(tmp_path, [payload])
    with pytest.raises(RegistryValidationError, match="Extra inputs"):
        load_metrics_yml(path)


def test_missing_includes_excludes_and_definition_rejected() -> None:
    with pytest.raises(ValueError):
        CanonicalMetric.model_validate(_metric_dict(definition="   "))
    with pytest.raises(ValueError):
        CanonicalMetric.model_validate(_metric_dict(includes=[]))
    with pytest.raises(ValueError):
        CanonicalMetric.model_validate(_metric_dict(excludes=[]))


def test_statement_period_unit_matrix() -> None:
    CanonicalMetric.model_validate(_metric_dict())
    with pytest.raises(ValueError, match="period_type"):
        CanonicalMetric.model_validate(_metric_dict(period_type="instant"))
    with pytest.raises(ValueError, match="unit_dimension"):
        CanonicalMetric.model_validate(_metric_dict(unit_dimension="shares"))
    CanonicalMetric.model_validate(
        _metric_dict(
            key="shares_outstanding",
            name="Shares outstanding",
            statement="shares",
            period_type="instant",
            unit_dimension="shares",
            definition="Common shares outstanding at period end.",
            includes=["period-end common shares"],
            excludes=["weighted-average shares"],
        )
    )
    CanonicalMetric.model_validate(
        _metric_dict(
            key="weighted_average_shares_basic",
            name="Weighted-average shares, basic",
            statement="shares",
            period_type="duration",
            unit_dimension="shares",
            definition="Weighted-average basic shares.",
            includes=["basic WASO"],
            excludes=["diluted WASO"],
        )
    )
    with pytest.raises(ValueError, match="unit_dimension"):
        CanonicalMetric.model_validate(
            _metric_dict(
                key="shares_outstanding",
                statement="shares",
                period_type="instant",
                unit_dimension="monetary",
            )
        )


def test_definition_hash_deterministic_and_order_insensitive() -> None:
    left = CanonicalMetric.model_validate(_metric_dict(includes=["b", "a"], excludes=["y", "x"]))
    right = CanonicalMetric.model_validate(_metric_dict(includes=["a", "b"], excludes=["x", "y"]))
    assert definition_hash(left) == definition_hash(right)


def test_semantic_change_changes_definition_hash() -> None:
    base = CanonicalMetric.model_validate(_metric_dict())
    changed = CanonicalMetric.model_validate(
        _metric_dict(definition="A broader revenue concept including other income.")
    )
    assert definition_hash(base) != definition_hash(changed)


def test_name_only_change_preserves_definition_and_registry_hash() -> None:
    base = CanonicalMetric.model_validate(_metric_dict())
    renamed = CanonicalMetric.model_validate(_metric_dict(name="Total Revenue"))
    assert definition_hash(base) == definition_hash(renamed)
    assert semantic_registry_hash([base]) == semantic_registry_hash([renamed])


def test_duplicate_payload_ignores_key_and_name(tmp_path: Path) -> None:
    first = _metric_dict(key="revenue")
    second = _metric_dict(key="total_revenue", name="Total Revenue")
    assert duplicate_payload_signature(
        CanonicalMetric.model_validate(first)
    ) == duplicate_payload_signature(CanonicalMetric.model_validate(second))
    path = _write_yml(tmp_path, [first, second])
    with pytest.raises(RegistryValidationError, match="exact duplicate definition payload"):
        load_metrics_yml(path)


def test_yaml_key_order_does_not_affect_semantic_hash(tmp_path: Path) -> None:
    metric = _metric_dict()
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / "metrics.yml").write_text(
        yaml.safe_dump({"metrics": [metric]}, sort_keys=True),
        encoding="utf-8",
    )
    reversed_metric = dict(reversed(list(metric.items())))
    (second / "metrics.yml").write_text(
        yaml.safe_dump({"metrics": [reversed_metric]}, sort_keys=False),
        encoding="utf-8",
    )
    left = load_metrics_yml(first / "metrics.yml")
    right = load_metrics_yml(second / "metrics.yml")
    assert left.semantic_registry_hash == right.semantic_registry_hash
    assert definition_hash(left.metrics[0]) == definition_hash(right.metrics[0])
