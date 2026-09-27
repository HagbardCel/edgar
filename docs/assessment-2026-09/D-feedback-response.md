# D — Response to the third hardening critique

**Status:** independent reply, then a specification-hardening revision. No
architecture reopening. The feedback is not authoritative; every item below
was accepted or rejected on its own merits.

The input argued: the direction is settled; current CI is green; make one
more focused commit so P0–P6 is an implementation contract, not another
redesign.

## Verdict

I agree with that framing. The architecture stays. This pass closes
remaining **correctness and measurement holes** that would contaminate P2
or make P1/P4/P5 silently wrong.

I do **not** reopen Git-vs-ledger, Tier-3 auto-accept, DuckDB-now, YAML
`supersedes`, or per-report qualification.

After these edits I consider the **architecture review finished**. Further
change should be implementation, plus the P2 measurements the plan already
asks for.

## Point by point

### 1. Historical taxonomy families — **adopt (P0/P1 blocker)**

Agreed. Prefixing only `http://fasb.org/us-gaap/` and
`http://xbrl.sec.gov/dei/` fails 2009 `xbrl.us` filings and the 2011 DEI
move to `xbrl.sec.gov`. That would drop standard facts from expansion,
treat them as issuer extensions in P0.3, and miss the required context.

One classifier, used everywhere:

```text
us-gaap:  http://xbrl.us/us-gaap/     http://fasb.org/us-gaap/
dei:      http://xbrl.us/dei/         http://xbrl.sec.gov/dei/
srt:      http://fasb.org/srt/
```

Tests must include 2009, 2011-transition, and modern URIs. P2 stratification
adds **taxonomy release**, not only fiscal year.

### 2. OIM groups are XBRL data points — **adopt (P1 blocker)**

Agreed. Interval overlap applies to **duplicates of the same fact identity**
(same concept QName and other aspects). Two exact mappings of *different*
concepts are semantic supports, not XBRL duplicates. They co-support only
when values are equal; otherwise `conflict`.

### 3. One current conclusion per semantic key — **adopt**

Agreed. Key:

```text
(metric, family, issuer_cik?, local_name, canonical scope)
```

`relation: broader` + `status: accepted` already says “not exact.” Do not
also keep `exact`/`rejected` for the same key. `rejected` is for a proposed
relation with **no** affirmative alternative.

### 4. Stale rejection is history-only, never fatal to resolve — **adopt**

Agreed. Pin:

```text
accepted + stale contract_hash  → fatal for resolve/build
rejected + stale contract_hash  → inactive history
                                 → does not suppress the queue
                                 → rules check lists it as stale/review-needed
```

CI fails on stale **accepted** records. Stale **rejected** records are
reported; they do not fail `edgar build`.

### 5. Bounded P2 semantic audit — **adopt**

Agreed. The risk-first argument requires an independent check that
family-wide exactness holds outside the six filings. P2 now includes a
30–50 issuer-year audit on high-risk metrics, stratified by taxonomy
release, industry, year, size, and extension intensity, plus a metadata
drift census (datatype, period type, balance, documentation fingerprint)
across encountered releases. Full ~1,600-label gold remains P6.

### 6. Revenue coverage is era-aware — **adopt**

Agreed. RFCWCEAT is expected to be rare before ASC 606. Coverage gates
use “concept exists / is relevant in that taxonomy era.” One recent FSDS
quarter cannot census pre-2018 use; P2.6 uses historical FSDS quarters or
the extracted P2 sample.

### 7. Oracle identity = observation identity — **adopt**

Agreed. `companyfacts` aligns on CIK, exact standard concept, accession,
period dates, and unit. FY/FP are descriptive only.

### 8. P3 parity includes dimensions and fact aspects — **adopt**

Agreed. Dropping `GeographyAxis=EuropeMember` must fail parity. Package
parity also compares datatype, period type, balance, documentation hash,
and relevant network identity for used concepts.

### 9. Tier-2 continuity is overlap-period — **adopt**

Agreed. Compare FY2023 as-filed to FY2023 comparative in the next filing,
not this year's current to last year's comparative. A changing new-year
value must still reuse.

### 10. Tier lives on the application, not the file — **adopt**

Agreed. Issuer decisions record `reviewed_occurrences`. Supports carry
`application_method = reviewed | continuity` and `tier = 4 | 2`.

### 11. Current rejected decisions need a source anchor — **adopt**

Agreed. A rejection that can suppress the queue needs the same minimal
evidence pointer as an accepted decision. Otherwise “new evidence” is
undefined.

### 12. Report focus ≠ duration kind — **adopt**

Agreed. `DocumentFiscalPeriodFocus=Q2` is the **report**. The required
duration on a Q2 10-Q is typically **YTD**. Model `report_focus` and
`period_kind` separately. Slot identity remains the dates.

### 13. Small inconsistencies — **adopt**

P0.3 allowed delta; 41-key registry and the two legacy contracts;
`unsupported` + `reason=wrong_form`; drift proposes, humans edit;
eBay evidence locator; P3 “Decisions need it.”

## What I still reject

| Implication | Why |
|---|---|
| Reopen the architecture | These are contract holes. The direction stands. |
| Fail `edgar build` on stale rejections | That would block the reopened queue the design requires. |
| Grow full gold in P2 | A bounded audit tests the hypothesis; 1,600 labels is still P6. |
| Generic fiscal calendar | Still not warranted; labels are just split correctly. |

## Documents updated in this revision

| Document | What changed |
|---|---|
| [04](04-target-architecture.md) | Family table; uniqueness; stale load; drift proposes; focus vs kind |
| [05](05-mapping-strategy.md) | OIM grouping; `wrong_form`; era-aware coverage |
| [08](08-migration-plan-assessment.md) | Pointer to this file |
| [P0](plan/P0-freeze-and-fix.md) | Family classifier; allowed extract delta |
| [P1](plan/P1-walking-skeleton.md) | Family, uniqueness, stale, OIM groups, 41 keys, `wrong_form` |
| [P2](plan/P2-scale-spike.md) | Release strata; semantic audit; oracle grain; FSDS history |
| [P3](plan/P3-consolidate.md) | Full fact-aspect parity; decision wording |
| [P4](plan/P4-extensions-and-review.md) | Overlap continuity; reviewed occurrences; evidence locator |
| [P5](plan/P5-time-and-quarterly.md) | `report_focus` vs `period_kind` |
| [P6](plan/P6-breadth.md) | 41 keys; legacy cash/capex stay until deprecated |
| [README](README.md) | Link to this file |
