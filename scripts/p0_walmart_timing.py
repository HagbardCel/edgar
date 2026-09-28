"""Walmart offline extract timing for P0 exit gate (no DB write)."""

from __future__ import annotations

import statistics
import time
from pathlib import Path

from edgar.corpus_acceptance import resolve_published_bundle
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from edgar.xbrl.semantic import run_offline_extract

CIK = "0000104169"
ACCESSION = "0000104169-24-000056"


def main() -> None:
    root = Path("var").resolve()
    store = ObjectStore(root)
    repo = BundleRepository(root, store)
    resolution = resolve_published_bundle(repo, CIK, ACCESSION)
    if resolution.error is not None or resolution.bundle is None:
        raise SystemExit(f"bundle resolution failed: {resolution.error_code}: {resolution.error}")
    bundle = resolution.bundle
    run_offline_extract(bundle, store)
    samples: list[float] = []
    for _ in range(3):
        start = time.perf_counter()
        result = run_offline_extract(bundle, store)
        elapsed = time.perf_counter() - start
        samples.append(elapsed)
        print(
            f"run facts={len(result.report.facts)} "
            f"relationships={len(result.report.relationships)} "
            f"declarations={len(result.report.declarations)} "
            f"elapsed={elapsed:.2f}s"
        )
    med = statistics.median(samples)
    print(f"median={med:.2f}s min={min(samples):.2f}s max={max(samples):.2f}s")


if __name__ == "__main__":
    main()
