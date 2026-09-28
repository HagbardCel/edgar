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
    parser.add_argument(
        "--storage-before",
        type=Path,
        help="JSON from p2_spike_storage_snapshot.py (pre-retrieval baseline)",
    )
    parser.add_argument(
        "--storage-after",
        type=Path,
        help="JSON from p2_spike_storage_snapshot.py (post-extract)",
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
    decls = [
        int(row["declaration_count"])
        for row in successes
        if row.get("declaration_count") is not None
    ]
    rels = [
        int(row["relationship_count"])
        for row in successes
        if row.get("relationship_count") is not None
    ]
    failure_classes = Counter(str(row.get("failure_class") or "unknown") for row in failures)
    print(f"attempted={attempted} succeeded={len(successes)} failed={len(failures)}")
    if walls:
        print(f"median_wall_seconds={statistics.median(walls):.2f}")
        print(f"p95_wall_seconds={statistics.quantiles(walls, n=20)[-1]:.2f}")
    if facts:
        print(f"median_facts={statistics.median(facts):.0f}")
    if decls:
        print(f"median_declarations={statistics.median(decls):.0f}")
    if rels:
        print(f"median_relationships={statistics.median(rels):.0f}")
    if failure_classes:
        print("failures_by_class:")
        for key, count in sorted(failure_classes.items()):
            print(f"  {key}: {count}")
    if args.storage_before and args.storage_after:
        before = json.loads(args.storage_before.read_text(encoding="utf-8"))
        after = json.loads(args.storage_after.read_text(encoding="utf-8"))
        obj_before = int(before.get("object_store_bytes") or 0)
        obj_after = int(after.get("object_store_bytes") or 0)
        pg_before = int(before.get("postgres_source_registry_bytes") or 0)
        pg_after = int(after.get("postgres_source_registry_bytes") or 0)
        print(f"object_store_bytes_added={obj_after - obj_before}")
        print(f"postgres_source_registry_bytes_added={pg_after - pg_before}")
        if len(successes):
            n = len(successes)
            print(f"object_store_bytes_per_successful_filing={(obj_after - obj_before) / n:.0f}")
            print(
                f"postgres_bytes_per_successful_filing={(pg_after - pg_before) / n:.0f}",
            )


if __name__ == "__main__":
    main()
