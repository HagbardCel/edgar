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
  residual (era-aware); P4 exists for that.
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
| Taxonomy release | at least one 2009/`xbrl.us` era, one 2011-transition, and modern `fasb.org` / `xbrl.sec.gov` (a filer can use different supported releases in the same fiscal year — record the **actual** namespace family/release, not only FY) |
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
oracle_value(companyfacts_json, cik, local_name, accession,
             period_start|instant, period_end, unit) -> Decimal | None
```

Compare only **standard-taxonomy, non-dimensional** facts — that is what
companyfacts contains. Align on the **same identity as the observation**:
CIK, exact standard concept, accession, period dates, unit. FY/FP (or
`report_focus`) are descriptive corroboration only — do not key the
oracle on them. Do not use “latest.”

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

Rows: metric × fiscal year × **taxonomy release** × industry (SIC
division or the bucket from P2.2). Columns:

| Column | Definition |
|---|---|
| `n_filings` | denominator |
| `n_value` / `n_missing` / `n_conflict` / `n_unsupported` | from observations |
| `coverage` | `n_value / n_applicable` (`unsupported` excluded). **Era-aware:** a filing is not applicable for a concept that does not exist / is not used in that taxonomy release (e.g. RFCWCEAT before ASC 606) |
| `oracle_agree` / `oracle_differ` / `oracle_absent` | P2.4 |
| `identity_pass` / `identity_fail` / `identity_na` | P1.7 |
| `gold_precision` | only where gold labels exist (still mostly M0) |

Working hypotheses to confirm or refute (from [05](../05-mapping-strategy.md)
§8) — write the measured number next to each:

- Total assets, operating cash flow: coverage ≥ 95% for non-financial
  issuers; treat this as a hypothesis, not a release gate.
- Revenue: coverage 75–90% **where the exact concept exists and is
  relevant**, lower for banks. Pre-ASC-606 `missing` on RFCWCEAT is
  expected, not a selector bug.
- R&D: many correct `missing`.

**Validation gate P2.5**

The report file exists, is generated by code (not hand-edited), and the PR
quotes coverage and oracle-agreement **per metric and taxonomy era**. If
revenue coverage is < 50% **in eras where RFCWCEAT is in the taxonomy and
commonly used**, stop and inspect 20 random `missing` before starting P3 —
the required-context or unit filter may be wrong. Low 2010–2017 coverage
on that tag is not that signal.

---

### P2.6 — FSDS / sample census (no full extra extract)

A **single recent** FSDS quarter cannot answer “was this tag rare before
2018.” Use one of:

1. selected **historical** FSDS quarters that cover pre- and post-ASC 606
   (at least one ≤ 2016 and one ≥ 2019), or
2. the already-extracted P2 sample: count distinct accessions per exact
   `local_name` × taxonomy era.

Do **not** check bulk zips into git.

Count, for each P1 exact `local_name`, how many distinct filings report it
as a non-dimensional tag **per era**. RFCWCEAT rare before 2018 is
expected (ASU 2014-09). Put the table in the P2 report.

**Validation gate P2.6**

A table of concept × **era** coverage (FSDS historical quarters or the
P2 sample) is in the P2 report. No production dependency on FSDS files.

---

### P2.7 — Decision ADRs (required before P3)

Write two short ADRs (or one ADR with two decisions), using P2 numbers:

1. **Storage.** DuckDB/Parquet vs keep PostgreSQL for `source.*`.
   Required inputs: bytes/filing, rebuild time, `build` query time on the
   spike, whether anyone needs concurrent writers in the next year.
2. **Taxonomy resolution.** Pinned official packages vs keep closure
   capture. Required input: a **parity probe** on ≥ 20 spike filings
   using the P3.1 fact-aspect key (including dimensions and unit
   structure), **plus** for used standard concepts: datatype, period
   type, balance, labels/documentation hash, and relevant
   relationship/network identity. Fact values alone are not enough to
   drop closure capture.

If you cannot run the parity probe, the ADR must say “packages deferred;
closure capture stays” rather than guessing.

**Validation gate P2.7**

```bash
test -f docs/adr/0015-*.md   # numbers as actually assigned
rg -n "bytes per filing|parity" docs/adr/0015-*.md
```

---

### P2.8 — Bounded independent semantic audit

The six-filing M0 gold cannot test the central hypothesis (family-wide
exactness holds outside those examples). `companyfacts` and FSDS do not
prove that concept C is exact for contract M.

Independently inspect rendered statements for:

```text
30–50 issuer-years
× selected high-risk metrics (at least revenue, and one BS + one CF)
stratified across:
  taxonomy release
  industry
  year
  company size
  extension intensity
```

Record each label in `registry/gold/p2-audit.yml` (accession, metric,
period dates, expected numeric or expected `missing`, R-file locator).
Do not label from the selector or from `companyfacts`.

Also measure **metadata drift** for each P1 exact standard decision
across every taxonomy release seen in the spike:

```text
datatype, period type, balance, documentation/reference fingerprint
```

Material drift → queue a proposed `exclude_qnames` edit (human PR). Do
not mutate Git from the detector.

**Validation gate P2.8**

The P2 report quotes audit `n`, errors, empirical precision, and the
drift table. P3 does not start if the audit shows family-wide exactness
failing on a standard concept that P1 treats as continuous.

## Phase exit gate

| Check | Pass |
|---|---|
| Spike list committed, 500–1,000 10-Ks | yes |
| Extract success ≥ 90% | yes |
| Quality report generated from code | yes |
| Oracle agreement reported per metric (period-date identity) | yes |
| P2.8 semantic audit + drift census in the report | yes |
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
