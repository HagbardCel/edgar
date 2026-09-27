# P4 — Extensions and review queue

**Duration:** about two to four weeks. **Depends on:** P3 exit (may start
queue prototyping on P1 tables after P2 if needed, but do not invent a
second review store).

## Goal

The residual after Stage-1 decisions is **visible, ranked, and reducible**
without per-filing human qualification.

- Tier 2: issuer extension family reuse, guarded by value continuity.
- Tier 3: structural *candidates* (value equality or verified calculation
  position) that rank the queue and never auto-accept.
- Tier 4: humans write issuer **decision records** in Git. Optional LLM
  proposals never accept.
- `edgar review list|show` prints the queue. **Observation** precision is
  measured on gold values for publishing tiers (1, 2, 4). **Tier-3
  candidate** precision is measured on reviewed exact/non-exact labels.

## Preconditions

- P2 quality report exists (it sizes this phase).
- `MetaLinks` parser from P1.6 works.
- Decision loader from P1.2 can load `registry/decisions/issuers/**/*.yml`.

## Out of scope

- Time views and quarterly selection (P5).
- New headline metrics (P6), except issuer decisions for the existing eight.
- LLM auto-approval. Agent frameworks. Embedding similarity as acceptance.
- Per-occurrence qualification packets and review-profile state machines
  (the adopted M2 design). An evidence packet is a **read-only JSON
  document**, not a workflow object.

## Work items

### P4.1 — Unmapped-candidate detection

For each P1 slot with `status=missing`, look at primary-statement
(`MetaLinks` `groupType=statement`) presentation-arc targets in the same
undimensioned required-context period that have numeric USD facts and **no**
exact decision.

Emit findings `unmapped_candidate` with: concept QName, label,
documentation (MetaLinks or filer label), statement `longName`, calc parent
and children, value, prior-year same local-name if any.

**Validation gate P4.1**

```bash
uv run pytest -q tests/unit/test_unmapped_candidates.py
# eBay disposal-group R&D extension appears as a candidate on the
# research_and_development missing path *only if* the standard R&D fact
# is absent. On eBay FY2023 R&D is present — the extension must still be
# listable via `edgar review show --concept ...` for the narrower test.
```

On eBay FY2023, R&D is **not** missing (standard concept exists). The
extension still belongs in a “related concepts on the statement” panel so a
reviewer can write a `narrower` decision. Implement that as
`nearby_unmapped`, not by forcing the slot to `missing`.

---

### P4.2 — Tier 2 continuity

**Decision file:**
`registry/decisions/issuers/0001065088/DisposalGroup-product-development.yml`
(example).

```yaml
id: ebay.research_and_development.disposal
metric: research_and_development
source:
  family: issuer
  issuer_cik: "0001065088"
  local_name: DisposalGroupIncludingDiscontinuedOperationProductDevelopment
  exclude_qnames: []
relation: narrower
status: accepted
method: reviewed
rationale: "Disposal-group product development is a component of R&D."
evidence:
  - kind: filer_documentation
    accession: "0001065088-24-000036"
    locator: "ebay_DisposalGroupIncludingDiscontinuedOperationProductDevelopment"
reviewed: {by: "<reviewer>", on: "<date>"}
reviewed_occurrences:
  - accession: "0001065088-24-000036"
    source_qname: "{…}DisposalGroupIncludingDiscontinuedOperationProductDevelopment"
contract_hash: "<hash of current contract>"
```

The evidence locator is the **extension concept being justified**, not the
standard `ResearchAndDevelopmentExpense` tag.

**Overlap-period continuity** (not “this year equals last year”):

```text
filing t-1:
  FY2023 as-filed extension = 100

filing t:
  FY2023 comparative extension = 100   ← continuity evidence
  FY2024 current extension     = 120   ← economic change; still reuse
```

Compare the **same period dates** (as-filed in t-1 vs comparative in t).
Do **not** require FY2024 current == FY2023 comparative. Values normally
change year to year.

**Auto-reuse** on a later eBay filing when **all** of:

1. An accepted issuer decision exists for that `local_name`. Expansion
   is `origin=issuer` and matching CIK (two year-specific namespaces
   both match). `contract_hash` is current;
2. A comparable overlap period **exists** and the values **agree**
   (as-filed t-1 equals comparative in t, OIM-consistent);
3. Documentation / preferred label did not change (string compare);
4. The later filing's expanded QName is not in `exclude_qnames`.

Overlap rules — no identity residual override:

```text
overlap exists and agrees     → may reuse (if 1, 3, 4 also hold)
overlap exists and disagrees  → queue
no overlap exists             → queue
```

An accounting identity that still closes is **evidence on the queue
item**, not automatic acceptance. That would be Tier-3-style structural
auto-accept.

Exact QNames remain distinct in `source.*`; the *decision* is what is
reused.

**Tier provenance.** The decision file is one; the **application** differs.
Key is `(accession, source_qname)`, not QName alone:

```text
(accession, source_qname) ∈ reviewed_occurrences
    → application_method=reviewed, tier=4
otherwise, continuity guards pass
    → application_method=continuity, tier=2
```

Precision-by-tier reports these support fields, not the file alone.

`narrower` and `related` decisions **never** publish as the metric's value.
They only explain why a nearby concept is not exact. Exact issuer
decisions (rare) may publish.

**Validation gate P4.2**

```bash
uv run pytest -q tests/unit/test_tier2_continuity.py
# same local_name, new namespace year, overlap agrees → reused
# new year's current value differs from last year's as-filed → still reused
# overlap exists and disagrees → queued (identity residual does not save it)
# no overlap → queued (identity/label are evidence only)
# narrower decision does not fill research_and_development
# (accession, qname) in reviewed_occurrences → tier 4
# later filing, same qname, different accession → tier 2
```

---

### P4.3 — Tier 3 structural *candidates* (no auto-accept)

Implement two proof types only. Do not add a decision engine. **Neither
proof accepts a mapping.** They attach evidence to a queue item.

1. **Value equality.** Extension fact numeric equals a standard-concept
   fact for the same context and unit. Proof record: both fact ids and the
   `Decimal`. Counterexample you must test: two different concepts both
   `0` — proof may fire as *evidence*, still not exact.
2. **Verified calculation parent.** Extension is the calc parent of the
   same children (by local name or by already-mapped concepts) as a
   standard total, **and** the weighted sum of child facts equals the
   parent fact (do not trust the linkbase without arithmetic).

Policy flag `registry/decisions/_policies.yml` (or equivalent):

```yaml
tier3_value_equality: rank   # rank | off   — never "accept"
tier3_calc_parent: rank
```

A human (P4.4 / P4.5) writes an accepted decision if they agree. Do not
write `registry/decisions/generated/` from these proofs.

Auto-acceptance of a *narrow* proof class needs a later ADR and a gold
set showing effectively perfect precision. Out of scope for P4.

**Validation gate P4.3**

```bash
uv run pytest -q tests/unit/test_tier3_proofs.py
# equality attaches evidence; does not create status=accepted
# two zeros of different concepts: no exact decision written
# calc proof fails when weights do not reconstruct the parent
# policy off → no proof attached
```

---

### P4.4 — Evidence packet and `edgar review`

`edgar review list` prints queue items ranked by:

1. Headline metric is `missing` and a primary-statement candidate exists;
2. Identity `fail`;
3. Oracle `differ`;
4. Nearby narrower/related only.

`edgar review show <id>` prints JSON/Markdown: definition, labels,
statement and line, calc neighbours, values, prior mapping, identity
residual, any Tier 3 proof attempt.

Packet is derived at show-time from `source.*` + decisions. Do not persist
packets in a table. Stale rejected decisions (wrong `contract_hash`)
appear as history and do **not** suppress the item.

**Validation gate P4.4**

```bash
uv run edgar review list --json | python -c "import json,sys; json.load(sys.stdin)"
uv run pytest -q tests/unit/test_review_queue.py
```

---

### P4.5 — Gold growth and precision by tier

Add at least **20** new gold **value** slots from the P2 spike (rendered
R-file values, not selector output). Tag each published observation with
its **publishing** tier (`1 | 2 | 4`). Tier 3 does not publish, so it
does not appear here.

Report **value precision** in CI (numeric gold slots only):

```text
value_precision_tier1, value_precision_tier2, value_precision_tier4
n_value_gold, n_value_errors
```

Also report **gold_assertion_pass**: every gold assertion matches,
including non-value labels (`missing`, `unsupported` + reason,
`conflict`). A change that publishes a value where gold says `missing`
fails this check even though it is not a numeric-precision miss.

Separately, if any Tier-3 candidates were reviewed, report **candidate**
precision from mapping-relation labels (not financial values):

```text
tier3_candidate_precision =
  reviewed Tier-3 candidates eventually judged exact
  -------------------------------------------------
  reviewed Tier-3 candidates
```

Precision CI is **two numbers**, not one:

```text
registry/gold/cohorts/<id>.yml     # slot ids; append-only new files
                                   # m0.yml exists from P1.3

regression set = union of every cohort file on the base branch
current set    = regression set ∪ cohorts added in this change

gold_assertion_pass on the regression set must not drop
  (every prior assertion: value, missing, unsupported, conflict)
  → fails --check-gold --require-precision-floor

value_precision on the current set is reported only
```

Checking only the newest cohort is wrong: a break in `m0.yml` must fail
even if a later cohort is clean.

`--require-precision-floor` does **not** apply a numeric publication
floor. That threshold, if any, is set by an ADR from P2/P6 measurements.

New labels go in a **new** cohort file. Do not rewrite an older file to
hide a regression. Adding harder cases may lower current
`value_precision`. That must **not** fail CI. A failed prior assertion
must.

Do not treat `tier3_candidate_precision` as observation precision.

**Validation gate P4.5**

```bash
uv run edgar build --check-gold --require-precision-floor
# union of base-branch cohorts: no assertion regression
# new cohort file may exist; current value_precision reported, not gated
# each new slot cites accession + R-file locator or statement line
```

---

### P4.6 — Optional LLM proposals (last, skippable)

Only if P4.1–P4.5 are done and the queue is still large.

- One structured call per queue item. Versioned prompt, schema-validated
  output `(metric, relation, rationale)`.
- Record model id, prompt version, input hash, parameters, raw failure.
- Storage under `var/llm/` — never in `registry/decisions/` until a
  **human** accepts. A Tier 3 proof does not write a decision.
- `LLM_ENABLED=false` remains the default; tests do not require a model.
- Measure proposal precision on a held-out gold slice. If it does not beat
  “always pass” review time, delete the integration.

Follow `AGENTS.md` local-LLM rules exactly.

**Validation gate P4.6** (if implemented)

```bash
LLM_ENABLED=false uv run pytest -q
# a fixture proposal file can be applied only via the same path as a human decision PR
```

## Phase exit gate

| Check | Pass |
|---|---|
| Queue non-empty on the spike and ranked | yes |
| Tier 2 unit tests green | yes |
| Tier 3 never writes `status: accepted` | yes |
| Narrower never publishes as exact | yes |
| Observation precision by publishing tier reported | yes |
| Tier-3 candidate precision reported only if reviews exist | yes |
| P1 15/15 still pass | yes |
| `make check` | green |

## Pitfalls

- **Publishing a narrower extension as R&D.** The eBay disposal-group
  concept is the regression test.
- **Trusting calculation arcs without summing facts.** Filers ship broken
  calc linkbases.
- **Writing ledger-like state for packets.** If you need a table, you have
  left this spec.
- **Continuity on local_name alone** without overlap-period agreement.
- **Letting an identity residual accept a mismatch.** That is not Tier 2.

## Stop and ask if

- Tier-3 **candidate** precision (reviewed exact/non-exact labels) is
  < 95% — disable ranking rather than loosening the proof, and do not
  treat that number as observation precision.
- You want a third proof type. Measure whether the first two already clear
  most of the queue.
