"""Compare current offline extract to a pinned P0 baseline directory."""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

from edgar.storage.objects import ObjectStore
from edgar.xbrl.extraction_receipt import load_bundle_ref
from edgar.xbrl.semantic import run_offline_extract
from edgar.xbrl.source_wire import report_extraction_to_dict

INVARIANT = frozenset({"contexts", "dimensions", "units", "measures", "facts", "relationships"})
ALLOWED_DELTA = frozenset(
    {
        "concepts",
        "declarations",
        "labels",
        "references",
        "issues",
        "extractor_version",
    }
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline_dir", type=Path)
    args = parser.parse_args()
    root = Path("var").resolve()
    store = ObjectStore(root)
    corpus = tomllib.loads(Path("fixtures/corpus.toml").read_text(encoding="utf-8"))
    failed = False
    for filing in corpus["filings"]:
        accession = filing["accession"]
        cik = filing["cik"]
        baseline_path = args.baseline_dir / f"{accession}.json"
        if not baseline_path.is_file():
            print(f"missing baseline {baseline_path}")
            failed = True
            continue
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        bundle_parent = root / "bundles" / cik / accession
        opaque = next(bundle_parent.iterdir())
        loaded = load_bundle_ref(data_root=root, bundle_dir=opaque)
        result = run_offline_extract(loaded.bundle, store)
        current = report_extraction_to_dict(result.report)
        for name in INVARIANT:
            if current[name] != baseline[name]:
                print(f"{accession}: invariant {name} changed")
                failed = True
        print(
            f"{accession}: concepts {len(baseline['concepts'])} -> {len(current['concepts'])} "
            f"declarations {len(baseline['declarations'])} -> {len(current['declarations'])} "
            f"labels {len(baseline['labels'])} -> {len(current['labels'])} "
            f"references {len(baseline['references'])} -> {len(current['references'])}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
