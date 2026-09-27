# P5 — Time views and quarterly / YTD

**Duration:** about two to three weeks. **Depends on:** P3. May overlap P4.

## Goal

The same exact rules produce:

- **as-filed** (already in P1);
- **first-reported** — earliest SEC acceptance that reports the slot;
- **latest-as-of(T)** — latest acceptance ≤ T, including comparatives in
  later filings; `value_changed` only when the number differs;
- **direct 10-Q** three-month and YTD slots using the required context of
  that 10-Q;
- **derived Q4** = annual − first-nine-months YTD, labelled `derived`, never
  `reported`.

Amendments compete per slot. A 10-K/A without statement facts (eBay
`0001065088-24-000094`) contributes nothing.

## Preconditions

- P1 selector is stable (`--check-gold` green).
- `source.filing.accepted_at` is populated for spike filings you will use.
  If it is null, leave `available_at` null — do not substitute filing date
  (standing rule 6). You may backfill acceptance from the submissions API
  via the existing client as a **retrieve** concern, not a selector guess.

## Out of scope

- Knowledge clocks (`semantic_as_of`, `acquired_as_of`). The
  `decisions_commit` on the build manifest is the mapping vintage.
- “Unreviewed later coverage blocks latest.” That was an artifact of
  per-report claims. Global decisions apply to all filings.
- `amends` edge table. Replacement is derived per slot by accession +
  acceptance time.
- Market/security joins (later product).
- Segment policies (P6).

## Work items

### P5.1 — Slot identity

Primary identity (what two facts must share to be the same observation):

```text
(cik, metric, period_start | instant, period_end, unit, scope)
```

`fiscal_year` and `report_focus` are **derived labels**, not identity.
`report_focus` is the DEI cover classification of **that report**
(`Q1 | Q2 | Q3 | FY`). It is **not** the duration kind of a fact.

`period_kind` (`annual | quarter | YTD | instant`) is taken from the
**dates** (and, for own-period facts, from whether the duration is the
fiscal year, a ~90-day quarter, or year-to-date). A Q2 10-Q typically has:

```text
DocumentFiscalPeriodFocus = Q2     → report_focus = Q2
required duration = FY start→Q2 end → period_kind = YTD
```

DEI does **not** say YTD. Do not store `fiscal_period = YTD` from focus.

Do **not** invent a generic issuer calendar (52/53-week years, fiscal-year
changes) unless P5 data shows it is needed.

Conservative derivation:

```text
own filing required context
+ that filing's DEI FY + DocumentFiscalPeriodFocus
        ↓
creates an issuer-period **anchor**
(cik, period_start|instant, period_end) → (fiscal_year, report_focus)

comparative period
        ↓
match against known anchors
        ↓
unique match → derived year + report_focus
no unique match → those labels stay unknown
period_kind always from the dates
```

A FY2022 comparative inside a FY2023 10-K has period dates in 2022; its
slot is 2022 even though the 10-K says focus 2023. If no earlier 10-K
created a 2022 anchor, leave year/focus unknown rather than guessing a
calendar.

Do not infer quarter from duration length alone (KO YTD vs quarter).

**Validation gate P5.1**

```bash
uv run pytest -q tests/unit/test_slot_identity.py
# eBay 10-K own period → FY 2023 + 2023-01-01/2023-12-31
# same 10-K comparative 2022-01-01/2022-12-31 → slot FY 2022, not 2023
# Walmart 10-K own instant → FY ending 2024-01-31 (not calendar 2023)
# KO 10-Q: DEI focus is Q2; required-context dates are YTD
#   → report_focus=Q2, period_kind=YTD (not "DEI says YTD")
```

---

### P5.2 — first-reported and latest-as-of

Input: all observations with `status=value` for a slot, each with
`available_at`.

- `first-reported`: min `available_at` (nulls sort last and **cannot** win).
- `latest-as-of(T)`: max `available_at` among those ≤ T. A later filing's
  **comparative** fact for the same slot is a candidate (same period start/end).
- Always store `supplying_accession`.
- If a later filing repeats the same slot with a decimals-consistent
  value, set `reported_again=true`. That is **not** a restatement.
- If the later value is not consistent, set `value_changed=true` and
  `restatement_candidate=true`.
- Never set restatement merely because `supplying_accession` ≠ the
  original 10-K accession.

`edgar build --view as-filed|first|latest --as-of 2024-12-31`.

**Validation gate P5.2**

```bash
uv run pytest -q tests/unit/test_time_views.py
# two accessions, same slot, same value, different acceptance
#   → latest supplying_accession changes, restatement_candidate is false
# two accessions, same slot, inconsistent values
#   → value_changed and restatement_candidate
# T before both → missing
# null accepted_at never selected
```

Use fabricated rows. Add one corpus test: eBay FY2022 as reported in the
FY2022 10-K vs as a comparative in the FY2023 10-K (stability metric).

---

### P5.3 — 10-Q three-month vs YTD

A 10-Q required context is usually **YTD**. The quarterly three-month
figure, if filed, is a different duration (start = period end minus ~90
days, but **only if a fact with that exact start/end exists**).

Selector policy `quarterly-v1`:

1. Read DEI `DocumentFiscalPeriodFocus` as `report_focus` (`Q1`/`Q2`/`Q3`).
   That is the **report**, not the duration kind.
2. YTD metric slot: required-context duration (`period_kind=YTD` from dates).
3. Three-month slot: only an undimensioned exact fact whose start/end match
   an explicit quarterly period present in the filing (`period_kind=quarter`).
   If absent → `missing`, do not subtract yet (that is P5.4 and only for Q4).

KO (`0000021344-24-000044`) and JPM (`0000019617-24-000453`) are the
fixtures. Their annual-selector revenue stays `missing`/`unsupported`.
Their quarterly build must not publish segment-dimensional revenue as
consolidated.

**Validation gate P5.3**

```bash
uv run pytest -q tests/unit/test_quarterly_select.py
# KO: YTD vs quarter periods are distinct; dimensional segment ≠ consolidated
# JPM: revenue remains unsupported under the P1 industry exclude
uv run edgar build --view as-filed --forms 10-Q --check-gold
```

Add gold rows for whatever KO **consolidated** figures you independently
read from the rendered statement (not from the selector). If you cannot
verify a number from the R file, do not put it in gold.

---

### P5.4 — Derived Q4

```text
Q4_derived = FY_annual - Q3_YTD
```

Same metric, same unit, decimals = coarsest of inputs. Kind =
`derived`. Findings must name both input accessions.

Do not emit derived Q4 when either input is missing/conflict, or when
fiscal year ends do not align.

**Validation gate P5.4**

```bash
uv run pytest -q tests/unit/test_derived_q4.py
# constructed annual 100, YTD9 70 → Q4 30 kind=derived
# missing YTD → no derived row
```

---

### P5.5 — Stability metric

For each gold or spike slot that appears as a comparative in a later 10-K:

`stable` if as-filed value equals the later comparative (consistent
decimals); else `changed` (possible restatement).

Add `stability_agree` / `stability_changed` to the quality report.

**Validation gate P5.5**

```bash
uv run pytest -q tests/unit/test_stability.py
# eBay FY2022 revenue vs comparative in FY2023 10-K — measure and record
```

## Phase exit gate

| Check | Pass |
|---|---|
| as-filed P1 gold unchanged | yes |
| first/latest: same value on a later 10-K is `reported_again`, not restated | yes |
| KO/JPM counterexamples still cannot publish as annual consolidated RFCWCEAT revenue | yes |
| Derived Q4 never `kind=reported` | yes |
| Comparative in a later 10-K uses period dates, not that 10-K's DEI FY | yes |
| Q2 10-Q: `report_focus=Q2` and required-context `period_kind=YTD` | yes |
| Null `accepted_at` cannot win a time view | yes |
| Quality report includes stability | yes |
| `make check` | green |

## Pitfalls

- **Using filing date as `available_at`.** Look-ahead and look-behind bugs.
- **Treating YTD as the quarter.** That is the KO trap.
- **Whole-filing supersession.** A 10-K/A that restates one note must not
  blank other slots.
- **Q4 subtraction across different accounting bases.** If an identity or
  contract hash differs, do not derive.

## Stop and ask if

- `accepted_at` is widely null in the spike. Fix acquisition before
  shipping latest/first as a product.
- You think you need `semantic_as_of`. Check out the `decisions_commit`
  and rebuild instead.
- You want a generic fiscal-calendar engine. Stay on anchors until the
  unknown-FY/FP rate on the spike demands more.
