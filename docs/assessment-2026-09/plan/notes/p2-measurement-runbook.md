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

Confirm `500 <= wc -l fixtures/spike/p2-accessions.txt <= 1000` (lines include supplemental 10-K/A rows beyond the primary count). Inspect `var/reports/p2-strata.txt` for realized fiscal-year × industry counts. Do not commit `var/` objects.

## P2.3 — Retrieve and extract

Snapshot storage **after** list build (submissions JSON may already be in the object store) and **before** retrieval:

```bash
uv run python scripts/p2_spike_storage_snapshot.py --label pre-retrieval \
  --output var/reports/p2-storage-pre.json
```

Retrieve in bounded batches (SEC fair access):

```bash
uv run python scripts/p2_spike_retrieve.py --limit 50
# repeat until skipped_existing covers the list; failures are recorded in var/reports/p2-retrieve.json
uv run edgar filings extract \
  --accessions-file fixtures/spike/p2-accessions.txt \
  --jobs 4
uv run python scripts/p2_spike_storage_snapshot.py --label post-extract \
  --output var/reports/p2-storage-post.json
uv run python scripts/p2_spike_summarize_extract.py \
  --storage-before var/reports/p2-storage-pre.json \
  --storage-after var/reports/p2-storage-post.json
```

Commit a redacted summary markdown under `docs/assessment-2026-09/plan/notes/` or `docs/reviews/`. Gate: ≥90% extract success on **primary** 10-K rows.

## P2.4 — Companyfacts cache

```bash
uv run edgar filings companyfacts \
  --accessions-file fixtures/spike/p2-accessions.txt
```

## P2.5 — Quality report (spike population)

Run the six-filing gold regression separately from the spike measurement build:

```bash
uv run edgar build --check-gold --output-dir var/builds/p1-gold
uv run edgar build \
  --accessions-file fixtures/spike/p2-accessions.txt \
  --quality-report var/reports/p2-quality.json \
  --sample-csv fixtures/spike/p2-sample.csv \
  --output-dir var/builds/p2
```

`--accessions-file` selects which filings `run_build` processes. Without it, `edgar build` still defaults to `fixtures/corpus.toml` (six filings).

## CI baseline

Tests and local smoke use `fixtures/spike/p2-accessions-baseline.txt` (six filings), not the full measurement list.
