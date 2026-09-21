"""Frozen M0 financial-benchmark.yml bytes from the clean M1A-2 starting commit."""

from __future__ import annotations

import hashlib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BENCHMARK = _REPO_ROOT / "fixtures" / "analysis" / "financial-benchmark.yml"

# hashlib.sha256 of the file bytes at the clean M1A-2 base — not a Git blob OID.
FROZEN_BENCHMARK_SHA256 = "6ef12974d1a83df89517dda69036c378b3d6691651e96f96bf83ea02da617f14"


def test_financial_benchmark_raw_sha256_matches_m1a2_base() -> None:
    assert len(FROZEN_BENCHMARK_SHA256) == 64
    assert FROZEN_BENCHMARK_SHA256.islower()
    digest = hashlib.sha256(_BENCHMARK.read_bytes()).hexdigest()
    assert digest == FROZEN_BENCHMARK_SHA256
