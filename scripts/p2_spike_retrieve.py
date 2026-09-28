"""Retrieve FilingBundles for accessions in the P2 measurement list.

Requires ``SEC_USER_AGENT``. Skips accessions that already have a published bundle.
Continues after per-accession failures and writes a JSON report.

Usage:
  uv run python scripts/p2_spike_retrieve.py \\
    --accessions-file fixtures/spike/p2-accessions.txt \\
    --limit 50
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from edgar.config import Settings
from edgar.domain.identifiers import accession_to_cik
from edgar.ingestion.accession_file import parse_accession_file
from edgar.ingestion.acquisition import AcquisitionService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore, write_json_atomic


@dataclass(frozen=True)
class RetrieveRow:
    accession: str
    status: str
    failure_class: str | None = None
    failure_message: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "accession": self.accession,
            "status": self.status,
            "failure_class": self.failure_class,
            "failure_message": self.failure_message,
        }


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
        help="Max new retrievals this run (0 = all missing)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("var/reports/p2-retrieve.json"),
    )
    args = parser.parse_args()
    accessions = parse_accession_file(args.accessions_file)
    settings = Settings()
    repo = BundleRepository(settings.edgar_data_root, ObjectStore(settings.edgar_data_root))
    retrieved = 0
    skipped = 0
    failed = 0
    rows: list[RetrieveRow] = []
    had_failure = False
    with AcquisitionService(settings) as service:
        for accession in accessions:
            cik = accession_to_cik(accession)
            if repo.list_published(cik, accession):
                skipped += 1
                rows.append(RetrieveRow(accession, "skipped_existing"))
                continue
            if args.limit and retrieved >= args.limit:
                rows.append(RetrieveRow(accession, "not_attempted_limit"))
                continue
            try:
                service.acquire(accession)
            except Exception as exc:  # noqa: BLE001 — record and continue per P2 batch policy
                had_failure = True
                failed += 1
                rows.append(
                    RetrieveRow(
                        accession,
                        "failed",
                        failure_class=type(exc).__name__,
                        failure_message=str(exc),
                    ),
                )
                print(f"failed {accession}: {type(exc).__name__}: {exc}", flush=True)
                continue
            retrieved += 1
            rows.append(RetrieveRow(accession, "retrieved"))
            print(f"retrieved {accession}", flush=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "retrieved": retrieved,
        "skipped_existing": skipped,
        "failed": failed,
        "total_listed": len(accessions),
        "accessions": [row.to_dict() for row in rows],
    }
    write_json_atomic(args.report, payload)
    print(
        f"retrieved={retrieved} skipped_existing={skipped} failed={failed} "
        f"total_listed={len(accessions)} report={args.report}",
    )
    if had_failure:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
