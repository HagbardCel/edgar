"""Summarize ``var/reports/p2-extract.json`` for the P2.3 measurement table."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

from edgar.spike.extract_summary import (
    PRIMARY_SUCCESS_RATE_MIN,
    load_extract_records,
    summarize_extract_by_form,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("var/reports/p2-extract.json"),
    )
    parser.add_argument(
        "--sample-csv",
        type=Path,
        default=Path("fixtures/spike/p2-sample.csv"),
        help="Sample metadata (form) joined on accession for primary vs amendment gates",
    )
    parser.add_argument(
        "--min-primary-success-rate",
        type=float,
        default=PRIMARY_SUCCESS_RATE_MIN,
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
    parser.add_argument(
        "--retrieve-report",
        type=Path,
        help="JSON from p2_spike_retrieve.py for object-store bytes per retrieved filing",
    )
    args = parser.parse_args()
    records = load_extract_records(args.report)
    summary = summarize_extract_by_form(records, args.sample_csv)
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
    print(f"all_attempted={attempted} all_succeeded={len(successes)} all_failed={len(failures)}")
    print(
        f"primary_10k_attempted={summary.primary.attempted} "
        f"primary_10k_succeeded={summary.primary.succeeded} "
        f"primary_10k_failed={summary.primary.failed}",
    )
    rate = summary.primary.success_rate
    if rate is not None:
        print(f"primary_10k_success_rate={rate:.4f}")
    print(
        f"amendments_attempted={summary.amendments.attempted} "
        f"amendments_succeeded={summary.amendments.succeeded} "
        f"amendments_failed={summary.amendments.failed}",
    )
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
        obj_delta = obj_after - obj_before
        pg_delta = pg_after - pg_before
        print(f"object_store_bytes_added={obj_delta}")
        print(f"postgres_source_registry_bytes_added={pg_delta}")
        retrieved_count = 0
        if args.retrieve_report and args.retrieve_report.is_file():
            retrieve = json.loads(args.retrieve_report.read_text(encoding="utf-8"))
            retrieved_count = int(retrieve.get("retrieved") or 0)
        if retrieved_count > 0:
            print(f"object_store_bytes_per_retrieved_filing={obj_delta / retrieved_count:.0f}")
        if len(successes):
            print(f"postgres_bytes_per_extracted_filing={pg_delta / len(successes):.0f}")
    gate_ok = summary.primary_meets_gate(args.min_primary_success_rate)
    if not gate_ok:
        raise SystemExit(
            f"primary 10-K success rate below {args.min_primary_success_rate:.0%}",
        )


if __name__ == "__main__":
    main()
