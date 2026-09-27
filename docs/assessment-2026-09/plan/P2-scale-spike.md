# P2 — Scale spike

**Duration:** about two to three weeks. **Depends on:** P1 exit gate green.

## Goal

Run Stage-1 decisions (the eight P1 metrics, global exact decisions only) on
**500–1,000 real 10-Ks**, then write down numbers that decide P3.

This phase is a *measurement* phase. New product features are limited to:
parallel extract, an oracle comparator, a quality report, and two short ADRs.

## Preconditions

- `edgar build --check-gold` passes on the six-filing corpus.
- Walmart extract ≤ 25 s (P0). If not, finish P0.2/P0.3 first — otherwise
  1,000 filings will take weeks.
- SEC user-agent is set (`EDGAR_USER_AGENT` / existing client settings).
  Stay below the project's default rate. No extra concurrency “to go faster”
  without reading `src/edgar/sec/client.py`.

## Out of scope

- Changing the selector policy because coverage looks low. Record the
  residual; P4 exists for that.
- DuckDB cutover, ledger deletion, DTO collapse (P3).
- LLM review (P4).
- Downloading an unbounded corpus. The spike list is a committed file.

## Work items

### P2.1 — Parallel extract

**Read first:** `src/edgar/ingestion/source_extract.py`,
`src/edgar/xbrl/semantic.py` (`run_offline_extract`), `src/edgar/cli.py`
(`filings extract`).

Add:

```text
edgar extract --accessions-file PATH --jobs N
```

or `edgar filings extract --jobs N` over a list. Each worker process handles
**one accession** end-to-end (catalog if needed + extract + persist). Do not
share a SQLAlchemy session across processes.

`N` default: `1`. Recommended spike value: `4`–`8` on a laptop, still
serialized through the existing SEC client when retrieving.

Retrieval of new filings uses `edgar filings retrieve` / `AcquisitionService`
and the existing rate limiter. **Do not** add a second `httpx` client.

**Tests:** unit-test that the accession file parser rejects empty lines and
malformed accessions. One integration test with `jobs=2` on two *fixture*
bundles (not live SEC).

**Validation gate P2.1**

```bash
uv run pytest -q tests/unit/test_extract_jobs.py
# two fixture accessions with --jobs 2 complete; fact counts match --jobs 1
```

---

### P2.2 — Stratified spike list

Create `fixtures/spike/p2-accessions.txt` (or `.toml`) **before** mass
download. Target 500–1,000 10-K accessions, not 10-Qs.

Stratify by hand or with the submissions API (existing client):

| Axis | Buckets (aim for all of them) |
|---|---|
| Fiscal year | 2010–2012, 2013–2015, 2016–2018, 2019–2021, 2022–2025 |
| Industry | at least retail, tech, manufacturing, healthcare, **bank**, energy |
| Size | mega-cap and smaller (use SICs / known CIK lists, not tickers as keys) |
| Amendment | include some 10-K/A but they are not the count target |

Commit the **list** (accessions + CIK + year + SIC if known). Do not commit
the raw filings.

Download with the existing retrieve command, bounded batches (e.g. 50/day if
you are a single user — follow the SEC fair-access policy already encoded in
the client). Store under the normal `var/` object store.

**Validation gate P2.2**

```bash
wc -l fixtures/spike/p2-accessions.txt    # 500–1000
# file is committed; no objects/ blobs added to git
rg -c "10-K" fixtures/spike/p2-accessions.txt
```

A short `fixtures/spike/README.md` states how the sample was drawn and that
it is not a probability sample of the market.

---

### P2.3 — Extract the spike and record cost

Run extract over the list. Write `var/reports/p2-extract.json` (local, not
committed unless redacted) with, per accession:

- wall seconds;
- fact count, declaration count, relationship count;
- extractor version;
- success / typed failure.

Summarize in the PR (committed markdown, e.g.
`docs/assessment-2026-09/plan/notes/p2-extract-summary.md` or a spike
report under `docs/reviews/`):

| Metric | Value |
|---|---|
| Filings attempted / succeeded | |
| Median / p95 extract seconds | |
| Median facts / declarations | |
| Bytes added to object store | |
| Bytes added to PostgreSQL | |
| Failures by class | |

**Validation gate P2.3**

- ≥ 90% of listed 10-Ks extract successfully. Investigate a sample of
  failures (do not silently drop them).
- Median extract time is consistent with P0 (tens of seconds, not ~100 s).
- No raw filings committed.

---

### P2.4 — `companyfacts` oracle

**Read first:** `src/edgar/sec/client.py` (reuse it). The endpoint is the
SEC companyfacts JSON for a CIK. Cache the response in the object store
like any other retrieved artifact (hash, no overwrite of different bytes).

Write `financials/oracle.py`:

```text
oracle_value(companyfacts_json, local_name, fy, fp, accession_or_end) -> Decimal | None
```

Compare only **standard-taxonomy, non-dimensional** facts — that is what
companyfacts contains. Align on fiscal year / period end, not on “latest”.

For each P1 observation with `status=value` and a standard exact rule:

- `agree` — same `Decimal` (or consistent under the observation's decimals);
- `differ` — both present, not consistent;
- `absent` — no companyfacts point.

Do not change the observation because the oracle differs. Record a finding.

**Tests:** committed excerpt of a companyfacts JSON (one concept, two
periods) under `tests/fixtures/`. No live call in default tests. A
`network`-marked test may fetch one CIK if you already have the pattern.

**Validation gate P2.4**

```bash
uv run pytest -q tests/unit/test_financials_oracle.py
# live (opt-in): oracle findings exist for the six-filing corpus
```

---

### P2.5 — Quality report

`edgar build --quality-report var/reports/p2-quality.json` (and a markdown
sibling) over the spike.

Rows: metric × fiscal year × industry (SIC division or the bucket from
P2.2). Columns:

| Column | Definition |
|---|---|
| `n_filings` | denominator |
| `n_value` / `n_missing` / `n_conflict` / `n_unsupported` | from observations |
| `coverage` | `n_value / n_applicable` (`unsupported` excluded from applicable) |
| `oracle_agree` / `oracle_differ` / `oracle_absent` | P2.4 |
| `identity_pass` / `identity_fail` / `identity_na` | P1.7 |
| `gold_precision` | only where gold labels exist (still mostly M0) |

Working hypotheses to confirm or refute (from [05](../05-mapping-strategy.md)
§8) — write the measured number next to each:

- Total assets, operating cash flow: coverage ≥ 95% for non-financial
  issuers; treat this as a hypothesis, not a release gate.
- Revenue: coverage 75–90%, lower for banks.
- R&D: many correct `missing`.

**Validation gate P2.5**

The report file exists, is generated by code (not hand-edited), and the PR
quotes coverage and oracle-agreement **per metric**. If revenue coverage is
< 50% outside banks, stop and inspect 20 random `missing` before starting
P3 — the required-context or unit filter may be wrong.

---

### P2.6 — FSDS census (no full extract)

Download the SEC Financial Statement Data Sets `num`/`pre` for one recent
quarter (bulk zip). Do **not** check the zip into git.

Count, for each P1 exact `local_name`, how many distinct `adsh` in that
quarter's 10-Ks report it as a non-dimensional tag. This sizes P4: if
`RevenueFromContractWithCustomerExcludingAssessedTax` is rare before 2018,
that is expected (ASU 2014-09). Put the table in the P2 report.

**Validation gate P2.6**

A table of concept × year-ish coverage from FSDS is in the P2 report. No
production dependency on FSDS files.

---

### P2.7 — Decision ADRs (required before P3)

Write two short ADRs (or one ADR with two decisions), using P2 numbers:

1. **Storage.** DuckDB/Parquet vs keep PostgreSQL for `source.*`.
   Required inputs: bytes/filing, rebuild time, `build` query time on the
   spike, whether anyone needs concurrent writers in the next year.
2. **Taxonomy resolution.** Pinned official packages vs keep closure
   capture. Required input: a **parity probe** on ≥ 20 spike filings
   (same fact counts and a hash of `(concept, context, unit, value)`).

If you cannot run the parity probe, the ADR must say “packages deferred;
closure capture stays” rather than guessing.

**Validation gate P2.7**

```bash
test -f docs/adr/0015-*.md   # numbers as actually assigned
rg -n "bytes per filing|parity" docs/adr/0015-*.md
```

## Phase exit gate

| Check | Pass |
|---|---|
| Spike list committed, 500–1,000 10-Ks | yes |
| Extract success ≥ 90% | yes |
| Quality report generated from code | yes |
| Oracle agreement reported per metric | yes |
| Storage + taxonomy ADRs merged or explicitly deferred with numbers | yes |
| `make check` | green |
| P1 gold still 15/15 on the six-filing corpus | yes |

## Pitfalls

- **Treating the spike as the market.** It is stratified convenience. Say so.
- **Raising coverage by relaxing undimensioned / USD / exact-only.** That
  hides the residual P4 is supposed to measure.
- **A second HTTP stack** for companyfacts or FSDS. Use `ControlledFetcher`.
- **Committing corpora.** Accessions lists and redacted reports only.
- **Starting P3 because extract “felt fine”.** P3 needs the ADR numbers.

## Stop and ask if

- Extract success < 90% and failures share one new error class.
- Oracle `differ` rate on total assets or OCF is > 2% — likely a period or
  unit bug, not “SEC is wrong”.
- You want to add metrics before the report exists. That is P6.
