# C — Response to the hardening critique

**Status:** independent reply, then a specification-hardening revision. No
architecture reopening. The feedback is not authoritative; every item below
was accepted or rejected on its own merits.

A later pass is recorded in [D](D-feedback-response.md). Treat D as current
for taxonomy-family prefixes, OIM grouping, decision uniqueness, P2 audit,
and P5 focus-vs-kind. This file remains the second-round verdict.

The input argued: the revised direction is now the right one; do not return
to M1A–M4; make one focused commit that closes remaining correctness holes
before P0.1 treats this as governing.

## Verdict

I agree with that framing. The previous revision settled the architecture.
This pass is **specification hygiene**: the selector's duplicate rule, the
decision-record lifecycle, a few measurement claims, leftover “rules”
wording, and a CI format failure.

I do **not** reopen Git-vs-ledger, Tier-3 auto-accept (already rejected),
DuckDB-now, knowledge clocks, or per-report qualification.

Call the result: adopt this directory as the intended direction after P0.1,
with the holes below closed.

## Point by point

### 1. Duplicate consistency = OIM intervals — **adopt (P1 blocker)**

Agreed. Rounding both values to the coarser `decimals` with
`ROUND_HALF_EVEN` is not the XBRL OIM rule. The OIM treats each numeric as
an interval of half-width `0.5 × 10^(-d)` (closed, so rounding mode does
not matter). Duplicates are consistent iff the intervals' intersection is
non-empty. Same `decimals` additionally requires equal reported numerics.
`INF` is the degenerate interval `[value, value]`.

The 2500/`-2` vs 3000/`-3` pair is the required counterexample: OIM-consistent,
rounding-algorithm-`conflict`. The Walmart pair remains consistent and the
survivor is still the more precise filed value (`decimals=-6` →
`9867000000`), with all fact ids kept as co-supports.

This is now the P1.4 contract. It must land before P1 is authorized.

### 2. Tier-3 auto-accept remnants + candidate precision — **adopt**

Agreed. §11 of [05](05-mapping-strategy.md) still authorized Tier-3
auto-accept. That was a stale sentence and is deleted. S8, the failure-mode
table, P4.6, and P4.5/`precision_tier3` are aligned:

- Observation gold measures **published values** (Tiers 1, 2, 4).
- Tier 3 has **candidate precision**: among reviewed Tier-3 items, the
  share later judged `exact`. That needs mapping-relation labels, not
  financial values.

No observation is published at Tier 3.

### 3. Decision lifecycle = Git current state — **adopt**

Agreed. `supersedes` mixed an append-only ledger into YAML. For this
architecture:

- One file is the current conclusion.
- A PR edits it.
- Git history is the revision log.
- Runtime loads current files. There is no “active head” walk.

**Also agreed** on stale rejections. Any decision with operational effect —
including “do not reopen this concept+metric” — must carry a
`contract_hash` equal to the **current** contract. A rejected file whose
hash is stale is historical evidence only; it does **not** suppress the
queue. P1 now requires `contract_hash` on accepted **and** rejected
records; CI fails the same way for both when the contract moved.

### 4. Drift escape hatch — **adopt**

Agreed. Family + local name remains the default expansion. When a later
drift check (or a reviewer) finds a release that is not the same concept,
the decision records it:

```yaml
source:
  family: us-gaap
  local_name: Foo
  exclude_qnames:
    - "{http://fasb.org/us-gaap/2025}Foo"
```

Issuer decisions may use the same field. No per-year ceremony unless an
exception exists.

### 5. Evidence required on accepted decisions — **adopt (lightweight)**

Agreed, with the same bound as before: no review profiles, capability
states, or packet lifecycle.

An **accepted** decision must have `rationale` and **at least one**
evidence item (`kind`, plus enough to find the source: MetaLinks/taxonomy
artifact hash, or accession+locator). The quote is optional. Rejected
decisions need `rationale`; evidence is recommended but not required.

### 6. P0.3 keep-set is not a fixed point — **adopt**

Agreed. The previous wording was circular. The algorithm is now:

```text
base_concepts =
    fact concepts
  ∪ relationship endpoints
  ∪ all issuer-extension declarations

persisted labels/references = resources whose subject ∈ base_concepts
persisted declarations      = base_concepts
```

No extra standard concept is kept “because a label exists.” A filing-specific
need for another standard concept would be an explicit later policy, not
P0.3.

### 7. Unit structure and entity scheme — **adopt (P1)**

Agreed. `EXISTS measure_local_name = 'USD'` accepts `USD/shares`. Monetary
contracts require:

- exactly one numerator measure;
- that measure's QName is ISO 4217 USD
  (`http://www.xbrl.org/2003/iso4217`, `USD`);
- no denominator.

Entity match is SEC CIK scheme plus a 10-digit zero-padded identifier, not
“strip zeros on any string.”

### 8. Fiscal classification is conservative — **adopt (specify before P5)**

Agreed this is not a P1 blocker. Period dates remain identity. FY/FP are
derived only by matching a comparative period to an **anchor** created from
some filing's own required context + that filing's DEI FY/FP. Unique match
→ fill FY/FP; otherwise FY/FP stay unknown. No generic 52/53-week calendar
engine unless P5 data demands it.

### 9. Quality methodology — **adopt the softening**

Agreed on both counts.

- `companyfacts` / FSDS validate extraction, period matching, and
  cross-system agreement. They do **not** prove that concept C is exact for
  contract M. That remains taxonomy evidence + reviewed decisions +
  independently labeled gold.
- The ±0.5 pp binomial interval assumed IID labels. The gold set is
  stratified and clustered. Report `n`, errors, empirical precision, and
  breakdowns. Population intervals only after a probability sample and
  cluster-aware estimates.

### 10. Decision vs rule terminology — **adopt**

Agreed. Authored object = **Decision**. Runtime = expansion / **Support**.
Lineage key = `decision_id`. `edgar rules check` may keep its CLI name
(it validates decisions). Manifests say `decisions_commit`.

### 11. CI format failure — **adopt (mechanical)**

Agreed. Ruff formats Python fences in
[A](A-evidence-and-method.md). Those fences are reformatted in this
revision so `ruff format --check .` is green.

## What I still reject

| Implication | Why |
|---|---|
| Reopen the architecture | The holes were specification bugs. The direction stands. |
| Restore `supersedes` / YAML ledger | Git current-state is enough; a chain of heads is M2 in files. |
| Optional evidence on accepted decisions | Too thin for the one non-regenerable asset. One pointer is enough. |
| Keep rounding-based duplicate consistency “because it passed Walmart” | Walmart is necessary, not sufficient. OIM is the standard. |

## Documents updated in this revision

| Document | What changed |
|---|---|
| [04](04-target-architecture.md) | Decision schema: no `supersedes`; required evidence; `exclude_qnames`; terminology |
| [05](05-mapping-strategy.md) | OIM duplicates; §11; S8; gold stats; failure modes |
| [07](07-lean-architecture-tradeoffs.md) | Oracle is not semantic proof; decisions commit |
| [08](08-migration-plan-assessment.md) | Pointer to this file |
| [P0](plan/P0-freeze-and-fix.md) | Non-circular keep-set; decision-file wording in the ADR |
| [P1](plan/P1-walking-skeleton.md) | OIM; units; entity; decision schema; `decision_id` |
| [P3](plan/P3-consolidate.md) | No `supersedes` |
| [P4](plan/P4-extensions-and-review.md) | Decision files; candidate precision; LLM → human only |
| [P5](plan/P5-time-and-quarterly.md) | Anchor-based FY/FP |
| [P6](plan/P6-breadth.md) | Decisions, not `standard.yml` rules |
| [A](A-evidence-and-method.md) | Ruff-formatted Python fences |
| [README](README.md) | Link to this file |
