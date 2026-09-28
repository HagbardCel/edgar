"""Walmart offline extract timing for P0 exit gate (no DB write)."""

from __future__ import annotations

import statistics
import time
from pathlib import Path

from edgar.storage.objects import ObjectStore
from edgar.xbrl.extraction_receipt import load_bundle_ref
from edgar.xbrl.semantic import run_offline_extract

CIK = "0000104169"
ACCESSION = "0000104169-24-000056"


def main() -> None:
    root = Path("var").resolve()
    bundle_parent = root / "bundles" / CIK / ACCESSION
    opaque = next(bundle_parent.iterdir())
    loaded = load_bundle_ref(data_root=root, bundle_dir=opaque)
    store = ObjectStore(root)
    run_offline_extract(loaded.bundle, store)
    samples: list[float] = []
    for _ in range(3):
        start = time.perf_counter()
        result = run_offline_extract(loaded.bundle, store)
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
