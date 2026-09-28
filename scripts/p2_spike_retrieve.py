"""Retrieve FilingBundles for accessions in the P2 measurement list.

Requires ``SEC_USER_AGENT``. Skips accessions that already have a published bundle.

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
        help="Max new retrievals this run (0 = all missing)",
    )
    args = parser.parse_args()
    accessions = parse_accession_file(args.accessions_file)
    settings = Settings()
    repo = BundleRepository(settings.edgar_data_root, ObjectStore(settings.edgar_data_root))
    retrieved = 0
    skipped = 0
    with AcquisitionService(settings) as service:
        for accession in accessions:
            cik = accession_to_cik(accession)
            if repo.list_published(cik, accession):
                skipped += 1
                continue
            if args.limit and retrieved >= args.limit:
                break
            service.acquire(accession)
            retrieved += 1
            print(f"retrieved {accession}")
    print(f"retrieved={retrieved} skipped_existing={skipped} total_listed={len(accessions)}")


if __name__ == "__main__":
    main()
