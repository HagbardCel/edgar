"""Summarize ``var/reports/p2-extract.json`` for the P2.3 measurement table."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("var/reports/p2-extract.json"),
    )
    args = parser.parse_args()
    payload = json.loads(args.report.read_text(encoding="utf-8"))
    records = payload.get("accessions") or []
    if not isinstance(records, list):
        raise SystemExit("report accessions must be a list")
    attempted = len(records)
    successes = [row for row in records if row.get("success")]
    failures = [row for row in records if not row.get("success")]
    walls = [float(row["wall_seconds"]) for row in successes if row.get("wall_seconds") is not None]
    facts = [int(row["fact_count"]) for row in successes if row.get("fact_count") is not None]
    failure_classes = Counter(str(row.get("failure_class") or "unknown") for row in failures)
    print(f"attempted={attempted} succeeded={len(successes)} failed={len(failures)}")
    if walls:
        print(f"median_wall_seconds={statistics.median(walls):.2f}")
        print(f"p95_wall_seconds={statistics.quantiles(walls, n=20)[-1]:.2f}")
    if facts:
        print(f"median_facts={statistics.median(facts):.0f}")
    if failure_classes:
        print("failures_by_class:")
        for key, count in sorted(failure_classes.items()):
            print(f"  {key}: {count}")


if __name__ == "__main__":
    main()
