# P3 — Consolidate

**Duration:** about three to four weeks. **Depends on:** P2 exit gate and the
storage / taxonomy ADRs from P2.7.

## Goal

The same P1 observations, on the six-filing gold set **and** the P2 spike,
come from a smaller system:

- one extraction schema (no dual DTO / wire family);
- storage as decided in P2.7;
- standard taxonomy stored once per release (if packages were adopted);
- mapping authority is Git only (ledger and YAML mirror deleted);
- receipts folded into the build / publication manifest;
- corpus-acceptance harness folded into `edgar build --check-gold` +
  fixture goldens.

Target from [03](../03-capability-inventory.md): production code on the order
of **≤ 18k** physical lines, not as a hard fail but as a PR check you
explain if you miss.

## Preconditions

- P2 quality report exists.
- Storage ADR and taxonomy ADR are merged (or explicitly “keep PostgreSQL /
  keep closure capture”).
- P1 gold still passes.

## Out of scope

- New mapping tiers (P4).
- Time views and 10-Q policy (P5).
- New metrics (P6).
- Changing published numbers to make a deletion easier. Parity first.

## Work items

Do these in order. Each item has its own gate. Do not combine “delete the
ledger” with “switch to DuckDB” in one PR.

### P3.1 — Fact-level golden parity harness

Before deleting anything, freeze a parity snapshot:

```text
For each accession in {six corpus} ∪ {P2 spike sample of ≥ 20}:
  hash of sorted (concept_clark, context_period, entity, unit, decimals,
                  resolved_numeric or lexical, source_locator)
```

Store hashes under `fixtures/parity/p3-facts-<extractor>.json`. This is the
guardrail for P3.2–P3.4.

**Validation gate P3.1**

```bash
uv run pytest -q tests/contract/test_p3_fact_parity.py
# six corpus accessions present; spike sample listed
```

---

### P3.2 — One record schema; worker writes it once

**Read first:** `src/edgar/xbrl/records.py`, `source_records.py`,
`_source_build.py`, `source_wire.py`, `worker.py`.

**Do:**

1. Choose **one** typed schema (keep the `source_records` names if they are
   the live persist path; delete the unused half of `records.py`).
2. Worker emits that schema (Arrow/Parquet **only if** the storage ADR
   chose DuckDB/Parquet; otherwise keep a single JSON-lines or dict payload,
   not two).
3. Delete `_source_build.py` when the worker output is already the persist
   input.
4. Delete `source_wire.py` codecs that exist only to translate between the
   two families.
5. Bump `SOURCE_RECORDS_SCHEMA_VERSION` and `EXTRACTOR_VERSION` if the
   bytes on the wire change. Re-run P3.1.

Work in small PRs: “delete unused record types” then “worker emits persist
shape” then “delete adapter”.

**Validation gate P3.2**

```bash
rg -n "class RoleDeclarationRecord|from edgar.xbrl.records import" src
# dead family gone or justified leftovers listed in the PR
uv run pytest -q tests/contract/test_arelle_report_extraction.py
uv run pytest -q tests/contract/test_p3_fact_parity.py
```

Fact hashes unchanged.

---

### P3.3 — Storage cutover (only if ADR says so)

**If PostgreSQL stays:** skip this item. Still apply “taxonomy once” (P3.4)
and delete knowledge-DB (P3.5).

**If DuckDB/Parquet:**

1. Add `duckdb` (and `pyarrow` if needed) to `pyproject.toml` with a
   justification comment in the PR.
2. One file `var/edgar.duckdb` (path from settings). Per-report replace =
   `DELETE` + `INSERT` in one DuckDB transaction, same grain as today.
3. Publications = Parquet under `var/publications/<id>/` plus
   `manifest.json`.
4. Port `tests/integration/test_source_persist.py` ideas: atomic replace,
   rollback, no silent drop of raw artifacts. Tests become temp-file tests;
   Docker is no longer required for them.
5. Remove `source.*` persist path and Alembic from the **live** workflow
   only after parity. Keep migrations in git history; do not rewrite old
   revisions.
6. `make db-up` becomes optional or documentation-only.

**Validation gate P3.3**

```bash
uv run pytest -q tests/contract/test_p3_fact_parity.py
uv run edgar build --check-gold
# P2 spike rebuild time and bytes recorded vs P2.3 (must not regress badly)
```

---

### P3.4 — Taxonomy tables once per release

**If packages were adopted:**

1. `edgar taxonomy load path/to/us-gaap-YYYY.zip` pins the zip in the object
   store and parses concepts, labels (including documentation), references,
   standard networks into `taxonomy/{release}/`.
2. Extraction joins standard metadata by `(namespace_uri, local_name)`.
   Per-report declarations stay at the P0.3 keep-set.
3. Closure capture for **standard** URIs is replaced by the package. Issuer
   extension files remain in the filing bundle. Missing package → fail
   closed (do not hit the network).
4. Re-run the P2.7 parity probe on the same ≥ 20 filings.

**If packages were deferred:** implement only a `taxonomy/` parse of the
already-captured US-GAAP schema from a bundle (one release at a time) so
declaration metadata is not copied per report. Keep closure capture.

**Validation gate P3.4**

```bash
uv run pytest -q tests/contract/test_p3_fact_parity.py
# declaration rows / filing remain at P0.3 levels, not ~18.5k
```

---

### P3.5 — Git is the only knowledge store

Delete, in one PR sequence after rules-check is in CI:

| Remove | Replacement |
|---|---|
| `registry.canonical_metric` mirror + `edgar registry sync` | `edgar rules check` + `edgar metrics list` reading YAML |
| `registry.mapping_assertion` ledger + propose/accept/reject | `registry/rules/**/*.yml` + PRs |
| `src/edgar/db/registry.py`, `registry_schema.py`, migration `0002` as a *live* requirement | historical files may remain until the DB is gone |
| `semantic-registry/` archive in the working tree | git history |

Update CLI help. Update `AGENTS.md` Phase 2C bullets: YAML is authority;
there is no mirror and no ledger.

Keep `definition_hash` in `src/edgar/registry/hashing.py` — rules still pin
it.

**Validation gate P3.5**

```bash
uv run edgar rules check
uv run edgar metrics list
rg -n "mapping_assertion|canonical_metric" src
# no live writers
make check
```

---

### P3.6 — Receipts → manifest; acceptance → build

- Stop threading `ExtractionReceipt` through persist. Identity fields
  (bundle hash, extractor version, arelle version, lock digest) go on
  `manifest.json` for extracts and builds.
- Keep `upstream_inventory` as a **test helper** if useful; remove it from
  `SourceExtractService` runtime. One integrity check at commit: fact count
  and FK anti-joins.
- Fold `src/edgar/corpus_acceptance.py` checks that still matter into
  `edgar build --check-gold` and contract tests. Delete the rest.

**Validation gate P3.6**

```bash
rg -n "ExtractionReceipt|upstream_item_fact_count" src
# runtime path: at most one check site + schema leftover if PG remains
uv run pytest -q tests/contract/test_p3_fact_parity.py
uv run edgar build --check-gold
```

---

### P3.7 — Line-count and doc trim

- Delete August residue left from P0.4 if any.
- Archive or delete the M0 static validators
  (`tests/helpers/financial_cases.py`,
  `tests/unit/test_financial_benchmark_manifest.py`) now that P1 gold is the
  acceptance test.
- Trim `AGENTS.md` toward ~150–200 lines: mission, invariants, commands,
  current phase. Do not lose source invariants.
- Leave `docs/architecture/` in place or move to `docs/archive/` in a
  dedicated docs PR (no code).

**Validation gate P3.7**

```bash
git ls-files '*.py' | rg -v '^tests/' | while read f; do wc -l < "$f"; done | awk '{s+=$1} END {print s}'
# explain if > 18000
make check
```

## Phase exit gate

| Check | Pass |
|---|---|
| P3.1 fact hashes match after all deletions | yes |
| P1 gold 15/15 | yes |
| `edgar rules check` is the knowledge CI entry | yes |
| No live ledger/mirror writers | yes |
| `make check` | green |
| P2 spike `build` still runs (spot-check ≥ 50 accessions) | yes |

## Pitfalls

- **One giant PR.** Reviewers cannot see which deletion broke parity.
- **Migrating regenerable data.** Rebuild extracts; do not write complex
  `UPDATE`s to reshape `source.*`.
- **Keeping a “compatibility” wire.** That is the four-representation
  problem again.
- **Deleting `definition_hash`.** Rules need it.
- **Dropping issuer extension files** when adding packages. Only standard
  URIs come from packages.

## Stop and ask if

- Parity hashes change and you cannot explain the delta in one paragraph.
- DuckDB decimal scale cannot hold a value you already store in PostgreSQL
  `NUMERIC` (then persist lexical + an issue; never float-cast).
- CI time explodes because you inlined the whole spike into default tests.
  Default tests stay small; spike checks are opt-in or nightly.
