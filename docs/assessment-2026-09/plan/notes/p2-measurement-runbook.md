# P2 measurement runbook

Execute after P2 software is on `main` (parallel extract, companyfacts cache, quality report). This document is operator steps; outcomes belong in PR notes and `docs/reviews/` per `P2-scale-spike.md`.

## Prerequisites

- `SEC_USER_AGENT` set; default SEC rate limits in `src/edgar/sec/client.py`.
- `make db-up`, `make migrate`, `EDGAR_DATA_ROOT` with space for hundreds of bundles.
- Walmart (or P0) extract timing acceptable; spike uses `--jobs 4`–`8` locally.

## P2.2 — Accession list

Preflight every CIK/name pair (fail closed before historical submissions walks):

```bash
uv run python scripts/p2_validate_spike_seeds.py \
  --seeds fixtures/spike/p2-stratification-seeds.toml \
  --output fixtures/spike/p2-seed-validation.tsv
```

Build the list:

```bash
uv run python scripts/p2_build_spike_accession_list.py \
  --seeds fixtures/spike/p2-stratification-seeds.toml \
  --target-min 500 --target-max 1000
git add fixtures/spike/p2-accessions.txt fixtures/spike/p2-sample.csv
```

**Validation gate:** read `var/reports/p2-strata.txt` — `primary_10k` must be between 500 and 1000. Total lines in `p2-accessions.txt` may exceed that count because supplemental `10-K/A` rows are appended. Do not use `wc -l` as the primary gate. Inspect realized fiscal-year × industry counts in the strata report. Do not commit `var/` objects.

## P2.3 — Retrieve and extract

Snapshot storage **after** list build (submissions JSON may already be in the object store) and **before** retrieval:

```bash
uv run python scripts/p2_spike_storage_snapshot.py --label pre-retrieval \
  --output var/reports/p2-storage-pre.json
```

Retrieve in bounded batches (`--limit` is **new acquisition attempts**, not successes):

```bash
uv run python scripts/p2_spike_retrieve.py --limit 50
# repeat until not_attempted=0; cumulative ledger in var/reports/p2-retrieve.json
# use --retry-failed to re-attempt prior failures after investigation
uv run edgar filings extract \
  --accessions-file fixtures/spike/p2-accessions.txt \
  --jobs 4
uv run python scripts/p2_spike_storage_snapshot.py --label post-extract \
  --output var/reports/p2-storage-post.json
uv run python scripts/p2_spike_summarize_extract.py \
  --sample-csv fixtures/spike/p2-sample.csv \
  --storage-before var/reports/p2-storage-pre.json \
  --storage-after var/reports/p2-storage-post.json \
  --retrieve-report var/reports/p2-retrieve.json
```

The summarizer exits non-zero if primary `10-K` success rate is below 90%. Commit a redacted summary markdown under `docs/assessment-2026-09/plan/notes/` or `docs/reviews/`.

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
uv run python scripts/p2_spike_taxonomy_coverage.py \
  --quality-report var/reports/p2-quality.json
```

`--accessions-file` selects which filings `run_build` processes. Without it, `edgar build` still defaults to `fixtures/corpus.toml` (six filings).

Post-extraction taxonomy stratification: the coverage script classifies `filing_taxonomy_release` tokens (for example `2009-01-31`, `2011-01-31`, `2024`) into 2009-era, 2011-transition, and modern (calendar year ≥ 2018) buckets.

## CI baseline

Tests and local smoke use `fixtures/spike/p2-accessions-baseline.txt` (six filings), not the full measurement list.
