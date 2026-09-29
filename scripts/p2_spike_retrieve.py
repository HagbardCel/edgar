"""Retrieve FilingBundles for accessions in the P2 measurement list.

Requires ``SEC_USER_AGENT``. Skips accessions that already have a published bundle.
Continues after per-accession failures and merges into a cumulative JSON report.

Usage:
  uv run python scripts/p2_spike_retrieve.py \\
    --accessions-file fixtures/spike/p2-accessions.txt \\
    --limit 50
"""

from __future__ import annotations

import argparse
from pathlib import Path

from edgar.config import Settings
from edgar.domain.identifiers import accession_to_cik
from edgar.ingestion.accession_file import parse_accession_file
from edgar.ingestion.acquisition import AcquisitionService
from edgar.spike.retrieve_ledger import (
    TERMINAL_FAIL,
    TERMINAL_KNOWN_FAIL,
    TERMINAL_NOT_ATTEMPTED,
    TERMINAL_SKIP_PUBLISHED,
    TERMINAL_SUCCESS,
    LedgerRow,
    load_ledger,
    merge_ledger,
    write_ledger_report,
)
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieve P2 spike accessions")
    parser.add_argument(
        "--accessions-file",
        type=Path,
        default=Path("fixtures/spike/p2-accessions.txt"),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max new acquisition attempts this run (0 = all missing)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("var/reports/p2-retrieve.json"),
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Re-attempt accessions that failed in a prior cumulative report",
    )
    args = parser.parse_args()
    accessions = parse_accession_file(args.accessions_file)
    settings = Settings()
    repo = BundleRepository(settings.edgar_data_root, ObjectStore(settings.edgar_data_root))
    ledger = load_ledger(args.report)
    batch_updates: dict[str, LedgerRow] = {}
    attempted_new = 0
    batch_retrieved = 0
    batch_failed = 0
    had_failure = False
    with AcquisitionService(settings) as service:
        for accession in accessions:
            cik = accession_to_cik(accession)
            if repo.list_published(cik, accession):
                row = LedgerRow(accession, TERMINAL_SKIP_PUBLISHED)
                batch_updates[accession] = row
                continue
            prior = ledger.get(accession)
            if (
                prior is not None
                and prior.status == TERMINAL_FAIL
                and not args.retry_failed
            ):
                batch_updates[accession] = LedgerRow(
                    accession,
                    TERMINAL_KNOWN_FAIL,
                    failure_class=prior.failure_class,
                    failure_message=prior.failure_message,
                )
                continue
            if args.limit and attempted_new >= args.limit:
                batch_updates[accession] = LedgerRow(accession, TERMINAL_NOT_ATTEMPTED)
                continue
            attempted_new += 1
            try:
                service.acquire(accession)
            except Exception as exc:  # noqa: BLE001 — record and continue per P2 batch policy
                had_failure = True
                batch_failed += 1
                batch_updates[accession] = LedgerRow(
                    accession,
                    TERMINAL_FAIL,
                    failure_class=type(exc).__name__,
                    failure_message=str(exc),
                )
                print(f"failed {accession}: {type(exc).__name__}: {exc}", flush=True)
                continue
            batch_retrieved += 1
            batch_updates[accession] = LedgerRow(accession, TERMINAL_SUCCESS)
            print(f"retrieved {accession}", flush=True)
    ledger = merge_ledger(ledger, batch_updates)
    write_ledger_report(
        args.report,
        ledger,
        batch_attempted_new=attempted_new,
        batch_retrieved=batch_retrieved,
        batch_failed=batch_failed,
    )
    from edgar.spike.retrieve_ledger import summarize_ledger

    summary = summarize_ledger(ledger)
    print(
        f"batch attempted_new={attempted_new} retrieved={batch_retrieved} failed={batch_failed} "
        f"cumulative_retrieved={summary['cumulative_retrieved']} "
        f"cumulative_failed={summary['cumulative_failed']} "
        f"report={args.report}",
    )
    if had_failure:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
