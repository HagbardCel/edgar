# B — Response to hybrid-architecture feedback

**Status:** independent reply, then adopted revisions. The feedback is not
authoritative. Where this file disagrees, the assessment and plan keep the
earlier recommendation. Where it agrees, those documents were changed in the
same revision as this file.

A later hardening pass is recorded in [C](C-feedback-response.md). Treat C
as current for decision-record schema, OIM duplicates, P0.3, and Tier-3
measurement. This file remains the first-round verdict.

The input argued, in short: adopt most of this assessment's *execution
strategy* and lean runtime; do not throw away the current target's
*semantic-governance* model; implement that model simply in Git.

## Verdict

The feedback is right on the largest methodological point and on three
concrete design errors. It is wrong, or too cautious, where it treats the
current target package as still the architectural baseline with a 20–30%
carry-forward.

After this pass, the intended change is:

> Adopt the P0–P2 execution strategy and the lean runtime (resolve → select
> → validate; Git authority; measured quality). Keep exact source QNames,
> relation vocabulary, exact-only publication, and **semantic decision
> records** — as Git artifacts, not as a PostgreSQL ledger. Do not
> auto-accept structural proofs. Do not treat a later accession as a
> restatement.

That is close to the feedback's hybrid diagram. It is **not** a decision to
keep M1A–M4, knowledge clocks, per-report qualification, dual hash schemes,
or the review-profile state machine. Those remain rejected.

Call it 75% of the original assessment, plus four corrections that the
assessment should have made the first time.

## Point by point

### 1. Sequencing (P0 → P1 → P2 first) — **adopt**

Agreed, and this was already the recommendation. Epistemic risk before
infrastructure risk. No change of direction. P0.1 still blocks P1.

### 2. Q1 / Q2 / Q3 as the central model — **adopt (already foundational)**

Agreed. [05](05-mapping-strategy.md) §1 already separates concept meaning,
contract relation, and selection. The current target said something similar
(“mapping is not observation selection”) and then bound qualification to
occurrences, which collapsed the distinction in practice.

No new layer is required. The operational chain stays:

```text
taxonomy / MetaLinks / packages   →  Q1 evidence
decision record (Git)             →  Q2
QName expansion                   →  supports
deterministic select              →  Q3
validate                          →  findings
```

### 3. Global rules, with release-aware QNames — **adopt, with a correction**

Agreed that `us-gaap:Assets → total_assets` should be decided once.

**Correction accepted.** A prefix match on the namespace URI is an
*expansion algorithm*, not concept identity. Source identity remains the
expanded QName (`namespace URI + local name`). That was already an
`AGENTS.md` invariant; P1's wording treated the family match as if it were
the identity.

The model is now:

```text
source fact     → exact QName  {http://fasb.org/us-gaap/2023}Assets
decision        → family us-gaap + local_name Assets + relation + scope
expansion       → the set of exact QNames this decision covers
                  (P1: family prefix + local name;
                   later: same, plus taxonomy-table checks on
                   type / period / balance / documentation drift)
```

P1 still does not require a hand-maintained per-release QName list. That
would recreate the M5 continuity trap. Expansion is computed and tested;
it is not “the QName is the family string.”

**Not adopted:** delaying multi-year reuse until a human compares each
release's declaration. That is the hidden dependency [08](08-migration-plan-assessment.md)
called out. Continuity of *family + local name* is the default; material
drift (docs/type/period/balance change) is a later validator that *narrows*
expansion, not a gate that forbids it.

### 4. Measured quality; oracles are not truth — **adopt**

Agreed. No change. `companyfacts` remains an oracle. Consistent duplicates
remain a selector rule, not a review item.

### 5. Drop SQLMesh — **adopt (already dropped)**

Agreed. SQLMesh was never in this assessment's mandatory architecture. It
stays out until someone can name the interdependent materializations it
would earn.

### 6. DuckDB/Parquet after P2; do not delete PostgreSQL now — **adopt**

Agreed. That was already P2.7 / P3.3. The original v2 “PostgreSQL is the
system of record” is not restored as a principle; it is one option P2 may
keep.

### 7. Ledger implementation vs ledger semantics — **adopt the compromise**

This is the feedback's best architectural point, and the original
assessment was too thin.

**Agreed:** a semantic decision is an intellectual artifact. Rejected
mappings, narrower/broader conclusions, and “we looked and said no” are
knowledge. If they live only in Git diffs of active rules, the review
queue will rediscover them.

**Agreed:** the PostgreSQL ledger, mirror, propose/accept lifecycle, and
M2 mutation machinery are still excess. Zero rows have ever been written.

**Compromise now in the plan:**

```text
registry/decisions/**/*.yml     # authority: accepted, rejected, non-exact
        ↓ load + expand QNames
runtime rule table              # accepted decisions only
        ↓
resolve / select

registry/gold/*.yml             # independent of decisions
```

A decision record is lean, not a reconstitution of M2:

```text
id, metric,
source: {family, local_name},
relation, scope,
status: accepted | rejected,
method: curated | continuity | reviewed,
rationale,
evidence: [{kind, quote, locator?}]   # short, optional
reviewed: {by, on},
supersedes: <id>? ,
contract_hash
```

Resolve never reads `rejected`. The review queue does, so the same
concept+metric is not re-opened without new evidence.

**Rejected from the feedback:** capability states, review-profile check
groups, typed occurrence qualification, evidence-pin ceremonies, and a
second “active rules” authoring format that drifts from the decisions.
Decisions *are* the authored form; the rule table is derived.

### 8. Tier-3 numeric-equality auto-acceptance — **reject our earlier spec**

Agreed with the feedback. Equal values are not semantic identity. Zero is
a sufficient counterexample. Calculation topology is evidence.

Tier 3 is now a **deterministic high-confidence candidate** with a recorded
proof. It ranks the queue. It does not publish and it does not write an
accepted exact decision.

Auto-acceptance of a *narrow* proof class can be reconsidered only after a
gold set shows effectively perfect precision for that class. Until then,
the conservatism of “non-exact must not become exact observations” stands.

07 T14 is reclassified: we are **not** giving this up. See the updated
trade-off table.

### 9. Provenance: simplify implementation, keep one completeness boundary — **adopt**

The original assessment said “golden counts + one assertion at persist”
and, in places, sounded as if CI fixtures were enough. That was sloppy.

**Keep:** every Arelle item fact is persisted or produces an explicit
completeness issue. That remains the highest-order source rule.

**Keep:** one runtime integrity boundary at extract/commit (counts +
referential anti-joins).

**Keep:** a build/extraction manifest with bundle hash, artifact hashes,
Arelle version, extractor version, taxonomy package hashes (when used),
fact counts, issue counts, code version.

**Still remove:** `ExtractionReceipt` as a fourth representation,
upstream inventory on the runtime path, and the other eleven check sites.

07 T8 is tightened: we give up *redundant* re-counts, not *the* completeness
check.

### 10. Taxonomy once per release; MetaLinks is not the official taxonomy — **adopt, plus a P0.3 bugfix**

Agreed on the grain (standard taxonomy once; filing holds used standard
concepts, extensions, networks, facts).

Agreed that `MetaLinks.json` is excellent **evidence** and must not become
the sole canonical substitute for official packages. P1 may parse MetaLinks;
P3 still pins packages after a parity test (or explicitly defers them).

**Bug accepted.** The P0.3 keep-set omitted concepts that exist only as
subjects of persisted labels or references. If those resources stay, their
concepts must stay. The keep-set is now:

1. concepts used by facts;
2. relationship source/target concepts;
3. subjects of labels/references we still persist;
4. all non-standard (issuer) namespaces.

And labels/references for unused *standard* concepts are filtered to the
same keep-set, so we do not keep 17k labels “just in case.”

### 11. P5 time model — **adopt the redesign; reject our earlier flags**

Two real errors in our P5 spec. Both are fixed.

**Comparative identity.** A FY2022 comparative in a FY2023 10-K must not
inherit `DocumentFiscalYearFocus = 2023`. Slot identity is now:

```text
(cik, metric, period_start | instant, period_end, unit, scope)
```

`fiscal_year` / `fiscal_period` are **derived** from that period against
the issuer's fiscal calendar. The supplying filing's DEI focus describes
*that filing's own* reporting period only. Required context remains the
anchor for the filing's own period (annual-v1, quarterly-v1). Comparatives
are selected by context dates.

**Restatement.** `winner.accession != as_filed.accession` is not a
restatement. Later 10-Ks repeat comparatives. Flags are now:

- `supplying_accession`
- `reported_again` (later filing, consistent value)
- `value_changed` (inconsistent under decimal rules)
- `restatement_candidate` only when `value_changed`

### 12. Hybrid diagram — **adopt as the picture, not as a stay-the-course**

The diagram in the feedback matches the revised 04 target, with two
clarifications:

- SOURCE storage is still a P2 decision.
- REGISTRY is Git decision records + contracts + gold, not a second
  runtime API besides resolve/select.

**Not adopted:** treating this as “keep the current architecture, apply a
better sequence.” The current *implementation path* and most of its
planned machinery remain the problem. The current *principles* that
survive are listed in 04 “What stays” plus decision-record semantics.

### 13. Process note (“do not merge the assessment as written”)

This directory was never an adopted ADR. It is a recommendation. The
corrections above are the revision the feedback asked for. Adoption still
requires P0.1.

### Two concrete implementation issues — **adopt both**

| Issue | Change |
|---|---|
| P0.3 keep-set missed label/reference subjects | Fixed in [P0](plan/P0-freeze-and-fix.md) |
| P1 annual selector must not treat 10-Qs as annual slots | Fixed in [P1](plan/P1-walking-skeleton.md): `annual-v1` runs only on `10-K` and `10-K/A`. JPM/KO remain **tests** that the annual selector yields `unsupported`/`missing`, not members of the annual corpus |

## What I still reject

| Feedback implication | Why it is rejected |
|---|---|
| Keep the current target package as governing, with this PR as a 70–80% overlay | After revision, *this* directory (plus a new ADR) should become the target. The M1A–M4 package stays historical. Overlaying two governing stories is how the docs already drifted from the code. |
| Per-release human comparison before family reuse | Expansion + later drift checks. Requiring review per US-GAAP year is the M5 trap. |
| Rich M2 evidence/profile/qualification model, just stored as YAML | Decision records stay small. Ceremony was the cost. |
| Restore knowledge clocks | Mapping vintage = Git commit on the manifest. Market time = `accepted_at`. |
| Fixtures-only completeness (the feedback attributed this to us) | We do **not** adopt a fixtures-only posture. We keep one runtime completeness boundary. |

## Documents updated in this revision

| Document | What changed |
|---|---|
| [04](04-target-architecture.md) | Decision records; QName expansion; observation grain; completeness; ledger implementation vs semantics |
| [05](05-mapping-strategy.md) | Expansion vs identity; Tier 3 = candidates; comparative periods; restatement flags |
| [07](07-lean-architecture-tradeoffs.md) | T8, T14; knowledge store wording |
| [08](08-migration-plan-assessment.md) | Pointers to the corrections |
| [P0](plan/P0-freeze-and-fix.md) | Keep-set includes label/reference subjects |
| [P1](plan/P1-walking-skeleton.md) | Decision YAML; expansion; 10-K/10-K/A only |
| [P3](plan/P3-consolidate.md) | Git decision store, not “delete ledger semantics”; runtime completeness |
| [P4](plan/P4-extensions-and-review.md) | Tier 3 candidates only |
| [P5](plan/P5-time-and-quarterly.md) | Period grain; restatement flags |
| [README](README.md) | Link to this file |
