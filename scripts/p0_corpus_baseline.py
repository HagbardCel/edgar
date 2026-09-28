"""Capture offline extract collections for P0 structural diff (not committed).

Usage:
  uv run python scripts/p0_corpus_baseline.py [--label SHA] [--out var/p0-baseline]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from pathlib import Path

from edgar.corpus_acceptance import resolve_published_bundle
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from edgar.xbrl.semantic import run_offline_extract
from edgar.xbrl.source_wire import report_extraction_to_dict

COLLECTIONS = (
    "concepts",
    "declarations",
    "labels",
    "references",
    "contexts",
    "dimensions",
    "units",
    "measures",
    "facts",
    "relationships",
    "issues",
)


def _git_sha() -> str:
    out = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    return out[:12]


def _require_bundle(repo: BundleRepository, cik: str, accession: str):
    resolution = resolve_published_bundle(repo, cik, accession)
    if resolution.error is not None or resolution.bundle is None:
        raise SystemExit(
            f"{accession}: bundle resolution failed: {resolution.error_code}: {resolution.error}"
        )
    return resolution.bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default=None)
    parser.add_argument("--out", type=Path, default=Path("var/p0-baseline"))
    args = parser.parse_args()
    label = args.label or _git_sha()
    root = Path("var").resolve()
    store = ObjectStore(root)
    repo = BundleRepository(root, store)
    corpus = tomllib.loads(Path("fixtures/corpus.toml").read_text(encoding="utf-8"))
    out_dir = args.out / label
    out_dir.mkdir(parents=True, exist_ok=True)

    for filing in corpus["filings"]:
        accession = filing["accession"]
        cik = filing["cik"]
        bundle = _require_bundle(repo, cik, accession)
        result = run_offline_extract(bundle, store)
        payload = report_extraction_to_dict(result.report)
        snapshot = {name: payload[name] for name in COLLECTIONS}
        snapshot["extractor_version"] = payload.get("extractor_version")
        path = out_dir / f"{accession}.json"
        path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
        print(f"wrote {path} extractor={snapshot['extractor_version']}")


if __name__ == "__main__":
    main()
