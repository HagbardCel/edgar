# P4 — Extensions and review queue

**Duration:** about two to four weeks. **Depends on:** P3 exit (may start
queue prototyping on P1 tables after P2 if needed, but do not invent a
second review store).

## Goal

The residual after Stage-1 rules is **visible, ranked, and reducible**
without per-filing human qualification.

- Tier 2: issuer extension family reuse, guarded by value continuity.
- Tier 3: structural *candidates* (value equality or verified calculation
  position) that rank the queue and never auto-accept.
- Tier 4: humans write issuer rules in Git. Optional LLM proposals never
  accept.
- `edgar review list|show` prints the queue. Precision per tier is measured
  on gold.

## Preconditions

- P2 quality report exists (it sizes this phase).
- `MetaLinks` parser from P1.6 works.
- Rules loader from P1.2 can load `registry/rules/issuers/*.yml`.

## Out of scope

- Time views and quarterly selection (P5).
- New headline metrics (P6), except issuer rules for the existing eight.
- LLM auto-approval. Agent frameworks. Embedding similarity as acceptance.
- Per-occurrence qualification packets and review-profile state machines
  (the adopted M2 design). An evidence packet is a **read-only JSON
  document**, not a workflow object.

## Work items

### P4.1 — Unmapped-candidate detection

For each P1 slot with `status=missing`, look at primary-statement
(`MetaLinks` `groupType=statement`) presentation-arc targets in the same
undimensioned required-context period that have numeric USD facts and **no**
exact rule.

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
reviewer can write a `narrower` rule. Implement that as
`nearby_unmapped`, not by forcing the slot to `missing`.

---

### P4.2 — Tier 2 continuity

**Rule file:** `registry/rules/issuers/0001065088.yml` (example).

```yaml
- id: ebay.rnd.disposal.narrower
  metric: research_and_development
  concept_family: issuer
  issuer_cik: "0001065088"
  local_name: DisposalGroupIncludingDiscontinuedOperationProductDevelopment
  relation: narrower
  method: reviewed
  contract_hash: "<hash>"
```

**Auto-reuse** on a later eBay filing when:

1. An accepted issuer rule exists for that `local_name` (ignore namespace
   date suffix);
2. Comparative values are continuous: this year's fact equals last year's
   comparative, or the identity residual still closes;
3. Documentation / preferred label did not change (string compare).

If (2) or (3) fails → queue, do not auto-accept. Exact QNames remain
distinct in `source.*`; the *rule* is what is reused.

`narrower` and `related` rules **never** publish as the metric's value.
They only explain why a nearby concept is not exact. Exact issuer rules
(rare) may publish.

**Validation gate P4.2**

```bash
uv run pytest -q tests/unit/test_tier2_continuity.py
# same local_name, new namespace year, continuous values → reused
# label change → queued
# narrower rule does not fill research_and_development
```

---

### P4.3 — Tier 3 structural *candidates* (no auto-accept)

Implement two proof types only. Do not add a rule engine. **Neither
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

Packet is derived at show-time from `source.*` + rules. Do not persist
packets in a table.

**Validation gate P4.4**

```bash
uv run edgar review list --json | python -c "import json,sys; json.load(sys.stdin)"
uv run pytest -q tests/unit/test_review_queue.py
```

---

### P4.5 — Gold growth and precision by tier

Add at least **20** new gold slots from the P2 spike (rendered R-file
values, not selector output). Tag each observation with `tier`.

Report in CI (on the gold set only):

```text
precision_tier1, precision_tier2, precision_tier3, n_gold
```

A drop vs the previous commit fails `edgar build --check-gold` when
`--require-precision-floor` is set (default floor: do not decrease).

**Validation gate P4.5**

```bash
uv run edgar build --check-gold --require-precision-floor
# gold file grew; each new slot cites accession + R-file locator or
# statement line in a comment
```

---

### P4.6 — Optional LLM proposals (last, skippable)

Only if P4.1–P4.5 are done and the queue is still large.

- One structured call per queue item. Versioned prompt, schema-validated
  output `(metric, relation, rationale)`.
- Record model id, prompt version, input hash, parameters, raw failure.
- Storage under `var/llm/` — never in `registry/rules/` until a human or a
  Tier 3 proof accepts.
- `LLM_ENABLED=false` remains the default; tests do not require a model.
- Measure proposal precision on a held-out gold slice. If it does not beat
  “always pass” review time, delete the integration.

Follow `AGENTS.md` local-LLM rules exactly.

**Validation gate P4.6** (if implemented)

```bash
LLM_ENABLED=false uv run pytest -q
# a fixture proposal file can be applied only via the same path as a human rule PR
```

## Phase exit gate

| Check | Pass |
|---|---|
| Queue non-empty on the spike and ranked | yes |
| Tier 2 unit tests green | yes |
| Tier 3 never writes `status: accepted` | yes |
| Narrower never publishes as exact | yes |
| Gold precision by tier reported | yes |
| P1 15/15 still pass | yes |
| `make check` | green |

## Pitfalls

- **Publishing a narrower extension as R&D.** The eBay disposal-group
  concept is the regression test.
- **Trusting calculation arcs without summing facts.** Filers ship broken
  calc linkbases.
- **Writing ledger-like state for packets.** If you need a table, you have
  left this spec.
- **Continuity on local_name alone** without value/label guards.

## Stop and ask if

- Tier 3 precision on gold is < 95% — disable the policy rather than
  loosening the proof.
- You want a third proof type. Measure whether the first two already clear
  most of the queue.
