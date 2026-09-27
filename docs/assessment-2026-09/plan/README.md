# Implementation sequence

**Status:** specification for the recommended sequence in
[08](../08-migration-plan-assessment.md). **Not adopted.** Do not start P1+ until
the P0.1 ADR is accepted. P0.2 (locator fix) is an extraction bugfix and may
proceed under current invariants.

These files are written for a developer who knows Python and SQL, but not this
repository's history. Follow them in order. Do not skip a phase exit gate.

## How to use these files

1. Read the parent assessment first: [01](../01-goals-and-principles.md),
   [05](../05-mapping-strategy.md), [04](../04-target-architecture.md), then
   this index.
2. Open the current phase file. Complete work items in the numbered order.
3. Run that item's **validation gate** before starting the next item.
4. Run the **phase exit gate** before opening the next file.
5. If a gate fails, stop and fix. Do not weaken the gate.

Each file uses the same shape:

| Section | Meaning |
|---|---|
| Goal | What must be true when the phase ends |
| Preconditions | What must already be true |
| Out of scope | Work that belongs later; do not do it here |
| Work items | Ordered tasks with files, algorithms, tests |
| Phase exit gate | Commands and expected results |
| Pitfalls | Known ways this work goes wrong |

## Sequence

```text
P0 Freeze and fix
 └─ P0.1 ADR (blocks P1+)     P0.2 locator + grain + residue (bugfix)
        │
        ▼
P1 Walking skeleton ── 8 metrics × 6 filings, existing PostgreSQL
        │
        ▼
P2 Scale spike ── 500–1,000 filings, oracles, measured decisions
        │
        ▼
P3 Consolidate ── one schema, storage per P2 ADR, Git decisions only
        │
        ├──────────► P4 Extensions and review queue
        │
        └──────────► P5 Time views and quarterly / YTD
                         │
                         ▼
                    P6 Breadth (39 metrics, industries, history)
```

| File | Duration | First user-visible result |
|---|---|---|
| [P0 — Freeze and fix](P0-freeze-and-fix.md) | ~1 week | 10-K extract ≤ 25 s |
| [P1 — Walking skeleton](P1-walking-skeleton.md) | ~2 weeks | Canonical values for 8 metrics on 6 filings |
| [P2 — Scale spike](P2-scale-spike.md) | ~2–3 weeks | Quality report on 500–1,000 10-Ks |
| [P3 — Consolidate](P3-consolidate.md) | ~3–4 weeks | Smaller system; same numbers |
| [P4 — Extensions and review](P4-extensions-and-review.md) | ~2–4 weeks | Ranked exception queue |
| [P5 — Time and quarterly](P5-time-and-quarterly.md) | ~2–3 weeks | First / latest views; 10-Q slots |
| [P6 — Breadth](P6-breadth.md) | ongoing | Full metric set and history |

P4 and P5 may overlap after P3. P6 requires both.

## Standing rules (every phase)

These are not optional. They come from [01](../01-goals-and-principles.md) and
`AGENTS.md`.

1. **`Decimal` for every filed or published number.** Never `float`.
2. **Do not invent missing facts, sections, or identifiers.**
3. **Do not collapse broader / narrower / related into exact.**
4. **Do not aggregate dimensional facts** unless a later phase adds an explicit
   policy (P6 segments).
5. **CIKs are 10-digit zero-padded strings. Accessions stay dashed.**
6. **Timestamps stay distinct.** Filing date ≠ SEC acceptance ≠ period end ≠
   extraction time. Published `available_at` is the SEC acceptance timestamp.
7. **LLMs never approve a mapping.** They may propose in P4 only.
8. **No network in default tests.** Live SEC calls stay `network`-marked and
   opt-in.
9. **A parser or extractor change that alters persisted output bumps
   `EXTRACTOR_VERSION`** (`src/edgar/xbrl/source_records.py`, currently
   `source-extract-v5`).
10. **Do not edit an already-applied Alembic migration.** Add a new revision.
11. **Do not commit `.env`, credentials, or uncontrolled filing corpora.**
12. **Run the commands you claim.** Paste the output into the PR.

## House conventions

- Commands: `make check` at phase end; targeted `uv run pytest` at item gates.
- New modules go under `src/edgar/<area>/`. Do not import `scripts/spikes/`
  from `src/`.
- Tests: unit tests have no database and no network. Integration tests use
  `edgar_test` and the marker `database`.
- Knowledge (contracts, **decision records**, gold) lives in Git under
  `registry/`. Rejected decisions stay; the runtime applies accepted ones.
- Derived output (observations, findings) is rebuildable. Do not add Alembic
  tables for it in P1–P2.
- When counts change (declarations, issues), the PR must say *why* and show
  the old and new numbers.

## If you get stuck

Stop and ask when:

- a gate fails after one honest fix attempt and the cause is unclear;
- the instructions conflict with a live test or `AGENTS.md` invariant;
- P2 measurements overturn a P3 assumption (that is expected; write an ADR);
- you are tempted to add a table, hash scheme, or lifecycle state that the
  current phase file does not name.
