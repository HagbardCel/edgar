"""Build the stratified P2 measurement accession list from SEC submissions.

Requires ``SEC_USER_AGENT``. Writes ``fixtures/spike/p2-accessions.txt`` and
``fixtures/spike/p2-sample.csv``. Does not retrieve filing bundles.

Usage:
  uv run python scripts/p2_build_spike_accession_list.py \\
    --seeds fixtures/spike/p2-stratification-seeds.toml \\
    --target-min 500 --target-max 1000
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

from edgar.config import Settings
from edgar.domain.identifiers import submissions_url, validate_cik
from edgar.sec.client import ControlledFetcher
from edgar.spike.seed_validation import SeedValidationError, validate_seed_identity
from edgar.spike.stratified_sample import (
    format_stratum_report,
    load_issuer_seeds,
    select_stratified_filings,
    write_spike_outputs,
)
from edgar.spike.submissions_filings import SubmissionsFilingRow, iter_submissions_annual_filings
from edgar.storage.objects import ObjectStore


def _load_submissions_rows(
    fetcher: ControlledFetcher,
    store: ObjectStore,
    cik: str,
    *,
    max_bytes: int,
    expected_name: str | None,
) -> tuple[SubmissionsFilingRow, ...]:
    normalized = validate_cik(cik)
    _result, obj = fetcher.fetch_to_store(
        submissions_url(normalized),
        store,
        max_bytes=max_bytes,
    )
    payload = json.loads(store.open_bytes(obj.sha256))
    if not isinstance(payload, dict):
        raise SeedValidationError(f"CIK {cik}: submissions payload is not a JSON object")
    validate_seed_identity(payload, cik=normalized, expected_name=expected_name)
    historical: list[dict[str, object]] = []
    filings = payload.get("filings") or {}
    for file_meta in filings.get("files") or []:
        if not isinstance(file_meta, dict):
            continue
        name = file_meta.get("name")
        if not isinstance(name, str) or not name:
            continue
        hist_url = f"https://data.sec.gov/submissions/{name}"
        _hr, hist_obj = fetcher.fetch_to_store(hist_url, store, max_bytes=max_bytes)
        block = json.loads(store.open_bytes(hist_obj.sha256))
        if isinstance(block, dict):
            historical.append(block)
    return tuple(
        iter_submissions_annual_filings(
            normalized,
            payload,
            historical_blocks=tuple(historical),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build P2 stratified accession list")
    parser.add_argument(
        "--seeds",
        type=Path,
        default=Path("fixtures/spike/p2-stratification-seeds.toml"),
    )
    parser.add_argument("--target-min", type=int, default=500)
    parser.add_argument("--target-max", type=int, default=1000)
    parser.add_argument(
        "--accessions-out",
        type=Path,
        default=Path("fixtures/spike/p2-accessions.txt"),
    )
    parser.add_argument(
        "--sample-csv-out",
        type=Path,
        default=Path("fixtures/spike/p2-sample.csv"),
    )
    parser.add_argument(
        "--strata-report",
        type=Path,
        default=Path("var/reports/p2-strata.txt"),
        help="Write realized primary strata counts (local, not committed by default)",
    )
    args = parser.parse_args()
    settings = Settings()
    seeds_raw = tomllib.loads(args.seeds.read_text(encoding="utf-8"))
    issuer_rows = seeds_raw.get("issuer") or []
    if not isinstance(issuer_rows, list):
        raise SystemExit("seeds file must contain [[issuer]] tables")
    seeds = load_issuer_seeds(issuer_rows)
    store = ObjectStore(settings.edgar_data_root)
    rows: list[SubmissionsFilingRow] = []
    try:
        with ControlledFetcher(
            settings.require_user_agent(),
            min_interval_seconds=settings.sec_min_interval_seconds,
            max_redirects=settings.max_redirects,
            timeout_seconds=settings.sec_timeout_seconds,
            max_retries=settings.sec_max_retries,
        ) as fetcher:
            for seed in seeds.values():
                rows.extend(
                    _load_submissions_rows(
                        fetcher,
                        store,
                        seed.cik,
                        max_bytes=settings.max_file_bytes,
                        expected_name=seed.expected_name,
                    )
                )
    except SeedValidationError as exc:
        raise SystemExit(str(exc)) from exc
    sample = select_stratified_filings(
        rows,
        seeds,
        target_min=args.target_min,
        target_max=args.target_max,
    )
    write_spike_outputs(
        sample,
        accessions_path=str(args.accessions_out),
        sample_csv_path=str(args.sample_csv_out),
    )
    report = format_stratum_report(sample)
    args.strata_report.parent.mkdir(parents=True, exist_ok=True)
    args.strata_report.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(
        f"wrote {len(sample.primary)} primary + {sample.amendment_count} amendments "
        f"({len(sample.all_picks)} total lines) -> {args.accessions_out}",
    )
    print(f"wrote sample metadata -> {args.sample_csv_out}")
    print(f"wrote strata report -> {args.strata_report}")


if __name__ == "__main__":
    main()
