# P2 measurement runbook

Execute after P2 software is on `main` (parallel extract, companyfacts cache, quality report). This document is operator steps; outcomes belong in PR notes and `docs/reviews/` per `P2-scale-spike.md`.

## Prerequisites

- `SEC_USER_AGENT` set; default SEC rate limits in `src/edgar/sec/client.py`.
- `make db-up`, `make migrate`, `EDGAR_DATA_ROOT` with space for hundreds of bundles.
- Walmart (or P0) extract timing acceptable; spike uses `--jobs 4`–`8` locally.

## P2.2 — Accession list

```bash
uv run python scripts/p2_build_spike_accession_list.py \
  --seeds fixtures/spike/p2-stratification-seeds.toml \
  --target-min 500 --target-max 1000
git add fixtures/spike/p2-accessions.txt fixtures/spike/p2-sample.csv
```

Confirm `500 <= wc -l < fixtures/spike/p2-accessions.txt <= 1000`. Do not commit `var/` objects.

## P2.3 — Retrieve and extract

Retrieve in bounded batches (SEC fair access):

```bash
uv run python scripts/p2_spike_retrieve.py --limit 50
# repeat until skipped_existing covers the list
uv run edgar filings extract \
  --accessions-file fixtures/spike/p2-accessions.txt \
  --jobs 4
uv run python scripts/p2_spike_summarize_extract.py
```

Commit a redacted summary markdown under `docs/assessment-2026-09/plan/notes/` or `docs/reviews/`. Gate: ≥90% extract success.

## P2.4 — Companyfacts cache

```bash
uv run edgar filings companyfacts \
  --accessions-file fixtures/spike/p2-accessions.txt
```

## P2.5 — Quality report

```bash
uv run edgar build --check-gold \
  --quality-report var/reports/p2-quality.json \
  --output-dir var/builds/p2
```

Inspect oracle and census tables; do not commit full `p2-quality.json` unless redacted.

## CI baseline

Tests and local smoke use `fixtures/spike/p2-accessions-baseline.txt` (six filings), not the full measurement list.
