"""Post-extraction taxonomy-release coverage check for P2.2 stratification.

Reads a quality-report JSON produced by ``edgar build --quality-report`` and
prints whether distinct US-GAAP release tokens span the required eras.

Usage:
  uv run python scripts/p2_spike_taxonomy_coverage.py \\
    --quality-report var/reports/p2-quality.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _collect_release_tokens(quality_payload: dict[str, object]) -> set[str]:
    tokens: set[str] = set()
    cells = quality_payload.get("cells") or []
    if not isinstance(cells, list):
        return tokens
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        release = cell.get("filing_taxonomy_release")
        if isinstance(release, str) and release.strip() and release != "unknown":
            tokens.add(release.strip())
    return tokens


def _era_flags(tokens: set[str]) -> dict[str, bool]:
    joined = " ".join(sorted(tokens)).lower()
    return {
        "xbrl_us_2009_era": any(marker in joined for marker in ("2009", "xbrl.us", "us-gaap-2009")),
        "transition_2011_era": any(marker in joined for marker in ("2011", "us-gaap-2011")),
        "modern_fasb_sec": any(
            marker in joined
            for marker in ("fasb.org", "xbrl.sec.gov", "us-gaap-202", "us-gaap-2018")
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="P2 taxonomy-release coverage from quality JSON")
    parser.add_argument("--quality-report", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.quality_report.read_text(encoding="utf-8"))
    tokens = _collect_release_tokens(payload)
    print(f"distinct_filing_taxonomy_releases={sorted(tokens)}")
    flags = _era_flags(tokens)
    for key, present in flags.items():
        print(f"{key}={'yes' if present else 'no'}")
    if not all(flags.values()):
        raise SystemExit("taxonomy-release stratification axes not all represented")


if __name__ == "__main__":
    main()
