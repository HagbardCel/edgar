"""Pinned definition hashes for P1 walking-skeleton metric keys."""

from __future__ import annotations

from pathlib import Path

from edgar.registry.hashing import definition_hash
from edgar.registry.loader import load_metrics_yml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_METRICS_YML = _REPO_ROOT / "registry" / "metrics.yml"

PINNED_HASHES: dict[str, str] = {
    "cash_excluding_restricted_cash": (
        "42e3ef09680a26ef55429b0399e28e69f1a13239cae0651b0186430a22a83313"
    ),
    "cash_purchases_of_ppe": (
        "e4bce1078d73e7132623984fd3bd2bccccfa4340ec7f21d0acf0d137216c8711"
    ),
}


def test_p1_new_metric_definition_hashes_stable() -> None:
    loaded = load_metrics_yml(_METRICS_YML)
    by_key = {m.key: m for m in loaded.metrics}
    for key, expected in PINNED_HASHES.items():
        metric = by_key[key]
        assert definition_hash(metric) == expected
