# P2 spike sample

Two accession lists serve different gates:

| File | Role |
|------|------|
| `p2-accessions-baseline.txt` | Frozen six-filing software baseline (format, extract jobs, `check-gold`). Committed; stable in CI. |
| `p2-accessions.txt` | P2 **measurement** list (target 500–1,000 annual filings). Built by `scripts/p2_build_spike_accession_list.py` and committed without raw filings. Until that run, it may still match the six-filing baseline. |

Neither list is a probability sample of the market. `p2-sample.csv` holds metadata joined by the quality report on accession. Industry buckets in the CSV come from stratification seeds; fiscal year and taxonomy release in the quality report are computed from the filing.

`edgar filings extract --accessions-file` reads one canonical dashed accession per line and rejects blank lines, comments, malformed accessions, and duplicates.

Whether filings have been retrieved is runtime state under `EDGAR_DATA_ROOT`. Retrieval must not silently change the committed lists; use `scripts/p2_spike_retrieve.py` with bounded `--limit` batches.

## Build the measurement list (P2.2)

Requires `SEC_USER_AGENT` (see `docs/development.md`).

```bash
uv run python scripts/p2_validate_spike_seeds.py  # updates p2-seed-validation.tsv
uv run python scripts/p2_build_spike_accession_list.py \
  --seeds fixtures/spike/p2-stratification-seeds.toml \
  --target-min 500 --target-max 1000
# Gate on primary_10k in var/reports/p2-strata.txt (500–1000), not total wc -l
```

Seeds live in `p2-stratification-seeds.toml` (CIK + expected SEC entity name + size). Industry buckets are derived from SEC SIC at build time. The builder walks SEC submissions per issuer and stratifies primary `10-K` filings (2010–2025), then appends bounded `10-K/A` rows.

## Measurement workflow (P2.3–P2.5)

See `docs/assessment-2026-09/plan/notes/p2-measurement-runbook.md`.

`edgar filings companyfacts --accessions-file fixtures/spike/p2-accessions.txt` is the explicit cache population path. `edgar build` only reads that cache offline.

The name census in a quality report counts distinct accessions per expanded Clark QName of facts whose context has no `source.context_dimension` row. A concept that appears only on a dimensional context is absent. A concept that appears both ways is counted once. A separate `name_reuse_aggregate` groups by semantic family, namespace release, and local name. That rollup is not source identity.
