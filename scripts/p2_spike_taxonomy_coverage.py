"""Post-extraction taxonomy-release coverage check for P2.2 stratification.

Reads a quality-report JSON produced by ``edgar build --quality-report`` and
prints whether distinct US-GAAP release tokens span the required eras.

Release tokens are path segments such as ``2024`` or ``2009-01-31`` (see
``filing_taxonomy_release`` in the quality pipeline).

Usage:
  uv run python scripts/p2_spike_taxonomy_coverage.py \\
    --quality-report var/reports/p2-quality.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from edgar.spike.taxonomy_era import era_flags_from_release_tokens


def _collect_release_tokens(quality_payload: dict[str, object]) -> set[str]:
    tokens: set[str] = set()
    cells = quality_payload.get("cells") or []
    if not isinstance(cells, list):
        return tokens
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        release = cell.get("filing_taxonomy_release")
        if isinstance(release, str) and release.strip() and release not in {"unknown", "mixed"}:
            tokens.add(release.strip())
    return tokens


def main() -> None:
    parser = argparse.ArgumentParser(description="P2 taxonomy-release coverage from quality JSON")
    parser.add_argument("--quality-report", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.quality_report.read_text(encoding="utf-8"))
    tokens = _collect_release_tokens(payload)
    print(f"distinct_filing_taxonomy_releases={sorted(tokens)}")
    flags = era_flags_from_release_tokens(tokens)
    for key, present in flags.items():
        print(f"{key}={'yes' if present else 'no'}")
    if not all(flags.values()):
        raise SystemExit("taxonomy-release stratification axes not all represented")


if __name__ == "__main__":
    main()
