"""Frozen M0 financial-benchmark.yml bytes from the clean M1A-2 starting commit."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BENCHMARK = _REPO_ROOT / "fixtures" / "analysis" / "financial-benchmark.yml"

# git rev-parse HEAD at the clean M1A-2 base (M1A-1 hardening already committed).
M1A2_BASE_COMMIT = "885464731de484236e41c111290d6bdb2111ea69"
# hashlib.sha256 of the file bytes at that commit — not a Git blob OID.
FROZEN_BENCHMARK_SHA256 = "6ef12974d1a83df89517dda69036c378b3d6691651e96f96bf83ea02da617f14"


def test_financial_benchmark_raw_sha256_matches_m1a2_base() -> None:
    digest = hashlib.sha256(_BENCHMARK.read_bytes()).hexdigest()
    assert len(digest) == 64
    assert digest == FROZEN_BENCHMARK_SHA256
    subprocess.run(
        ["git", "diff", "--exit-code", M1A2_BASE_COMMIT, "--", str(_BENCHMARK)],
        cwd=_REPO_ROOT,
        check=True,
    )
