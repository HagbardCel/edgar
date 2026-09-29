"""Preflight: validate all P2 issuer seeds against SEC submissions (no list build).

Requires ``SEC_USER_AGENT``. Writes a TSV report and exits non-zero on mismatch.

Usage:
  uv run python scripts/p2_validate_spike_seeds.py \\
    --seeds fixtures/spike/p2-stratification-seeds.toml \\
    --output var/reports/p2-seed-validation.tsv
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

from edgar.config import Settings
from edgar.domain.identifiers import submissions_url, validate_cik
from edgar.sec.client import ControlledFetcher
from edgar.spike.seed_validation import (
    SeedValidationError,
    submissions_entity_name,
    validate_seed_identity,
)
from edgar.spike.sic_industry import industry_bucket_from_sic
from edgar.spike.stratified_sample import load_issuer_seeds
from edgar.storage.objects import ObjectStore


def _fetch_submissions(
    fetcher: ControlledFetcher,
    store: ObjectStore,
    cik: str,
    *,
    max_bytes: int,
) -> dict[str, object]:
    normalized = validate_cik(cik)
    _result, obj = fetcher.fetch_to_store(
        submissions_url(normalized),
        store,
        max_bytes=max_bytes,
    )
    payload = json.loads(store.open_bytes(obj.sha256))
    if not isinstance(payload, dict):
        raise SeedValidationError(f"CIK {cik}: submissions payload is not a JSON object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate P2 spike issuer seeds")
    parser.add_argument(
        "--seeds",
        type=Path,
        default=Path("fixtures/spike/p2-stratification-seeds.toml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("fixtures/spike/p2-seed-validation.tsv"),
    )
    args = parser.parse_args()
    settings = Settings()
    seeds_raw = tomllib.loads(args.seeds.read_text(encoding="utf-8"))
    issuer_rows = seeds_raw.get("issuer") or []
    seeds = load_issuer_seeds(issuer_rows)
    store = ObjectStore(settings.edgar_data_root)
    lines = [
        "cik\texpected_name\tsec_name\tsec_sic\tderived_bucket\tstatus",
    ]
    failures = 0
    with ControlledFetcher(
        settings.require_user_agent(),
        min_interval_seconds=settings.sec_min_interval_seconds,
        max_redirects=settings.max_redirects,
        timeout_seconds=settings.sec_timeout_seconds,
        max_retries=settings.sec_max_retries,
    ) as fetcher:
        for seed in sorted(seeds.values(), key=lambda item: item.cik):
            try:
                payload = _fetch_submissions(
                    fetcher,
                    store,
                    seed.cik,
                    max_bytes=settings.max_file_bytes,
                )
                validate_seed_identity(
                    payload,
                    cik=seed.cik,
                    expected_name=seed.expected_name,
                )
                sec_name = submissions_entity_name(payload)
                sic_raw = payload.get("sic")
                sic = str(sic_raw).strip() if sic_raw not in (None, "") else ""
                bucket = industry_bucket_from_sic(sic or None)
                status = "ok"
            except SeedValidationError as exc:
                failures += 1
                sec_name = ""
                sic = ""
                bucket = ""
                status = f"error: {exc}"
            lines.append(
                f"{seed.cik}\t{seed.expected_name or ''}\t{sec_name}\t{sic}\t{bucket}\t{status}",
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(seeds)} rows -> {args.output}")
    if failures:
        print(f"seed_validation_failures={failures}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
