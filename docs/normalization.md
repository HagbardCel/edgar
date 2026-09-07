# Canonical metric and mapping normalization (Phase 2C)

Documentation scope: this file describes the **implemented Phase 2C baseline**.
See the [documentation index](README.md) for status and authority.

Normative contract for Git-authoritative metric definitions and the PostgreSQL
mapping decision ledger. Observation selection is out of scope for this
baseline.

```text
metrics.yml                 = current canonical meaning
registry.canonical_metric   = synchronized DB mirror
registry.mapping_assertion  = immutable reviewed semantic history
current + accepted + exact + current definition hash
                            = eligible input to a future observation stage
source.*                    = extraction evidence untouched by registry writes
```

The Phase 2C implementation originally froze the following future eligibility
sketch: only current accepted exact mappings with a matching definition hash
would feed later observation selection. Forward implementation of contracts,
conditions, observation selection and publication is now governed by the adopted
M2/M3 rules in [architecture/mapping-and-review.md](architecture/mapping-and-review.md)
and [architecture/migration-plan.md](architecture/migration-plan.md)
([ADR 0012](adr/0012-adopt-bounded-financial-architecture.md)). This document
retains the Phase 2C wording as historical evidence of what the baseline
implemented and expected; it does not claim that Phase 2C was always designed
around the later M3 contract.

## 1. Purpose

Phase 2C records **what a reported metric means** and **which source concepts
reviewers have mapped to it**. It does not select facts, collapse dimensions,
or emit `metric_observation`.

## 2. Architecture boxes

- **Git `registry/metrics.yml`:** current measurement contracts.
- **`registry.canonical_metric`:** regenerable PostgreSQL mirror for FKs and
  queries. Not an independent definition authority.
- **`registry.mapping_assertion`:** append-only decision ledger.
- **`source.*`:** regenerable extraction of immutable filing evidence. Registry
  writes never upsert or mutate source rows; extraction replaces them transactionally.

## 3. Canonical metric contracts

Each metric is a frozen Pydantic contract: `key`, `name`, `kind=reported`,
`statement`, `period_type`, `value_kind=numeric`, `unit_dimension`,
`definition`, `includes`, `excludes`. Unknown YAML fields fail validation.

Statement / period / unit matrix (exhaustive):

```text
income_statement → duration + monetary
balance_sheet    → instant  + monetary
cash_flow        → duration + monetary
per_share        → duration + monetary_per_share
shares           → instant|duration + shares
```

Keys match `^[a-z][a-z0-9_]*$`. Includes and excludes are required and
non-empty. Duplicate keys fail. Two metrics with identical contracts except
`key`/`name` fail the duplicate-payload check.

## 4. Definition hash and semantic registry hash

`definition_hash` is SHA-256 of canonical JSON over
`{key, kind, statement, period_type, value_kind, unit_dimension, definition,
includes, excludes}`. It includes `key` and excludes `name`. YAML key order
does not affect it.

The **semantic registry hash** is SHA-256 of the sorted per-metric
`definition_hash` values. Name-only edits do not change it. Sync still diffs
**every mirrored field including `name`**.

## 5. YAML authority and the database mirror

`propose` and `accept` must:

1. Load and validate current `registry/metrics.yml`.
2. Load the corresponding `registry.canonical_metric` row.
3. Require the mirror to match the YAML metric on **all mirrored fields**.
4. Otherwise fail: `registry out of sync; run edgar registry sync`.
5. Snapshot `target_definition_hash` from the **YAML** hash, never from a stale
   DB hash alone.

`edgar registry sync` is transactional, diffs all mirrored fields, fails if a
YAML-removed key is still referenced by any mapping assertion, and does not
bump `synced_at` on unchanged rows.

## 6. Mapping assertion ledger

Rows are `INSERT` + `SELECT` only. Accept and reject insert a successor.
`UNIQUE(supersedes_id)` plus a service check forbid branching. There is no
generic revise command.

Source concept identity at the CLI/service boundary is Clark
`{namespace-uri}LocalName`. Prefix or local-name-only identity is rejected.
Propose fails if the QName is not already in `source.concept`.

## 7. Claim identity

Every successor copies exactly:

```text
source_concept_id
target_metric_key
target_definition_hash
relation
scope_kind
issuer_cik
valid_from
valid_to
```

Only `status`, `method`, `rationale`, `evidence`, `created_at`, and
`created_by` may change. One revision chain never spans two canonical meanings.
Wrong source, target, relation, or scope requires a new root.

## 8. Status transitions

`rejected` is terminal.

```text
candidate → accepted
candidate → rejected
accepted  → rejected   # revocation
```

Candidates are reviewable ledger content, not accepted semantic knowledge.

## 9. Accept requirements and definition-hash safety

Accepted rows require a non-empty rationale and non-empty evidence with
snapshots in `data`. Rejected rows require a non-empty rationale; evidence is
optional.

Accept a candidate only when YAML/mirror are in sync **and**
`candidate.target_definition_hash` equals the current YAML `definition_hash`.
Otherwise fail: the metric changed since proposal; reject (retains hash A) and
propose a new root against B. Successors always copy hash A; they never rewrite
it to a later YAML hash.

## 10. Publication eligibility versus current accepted

```text
current accepted assertion
        ≠ necessarily
currently publishable mapping
```

Frozen Phase 2C eligibility sketch for a then-future observation stage
(not implemented here; forward rules are adopted M2/M3 in
[architecture/mapping-and-review.md](architecture/mapping-and-review.md)):

```text
current
AND status = accepted
AND relation = exact
AND target_definition_hash = current YAML definition_hash
```

Stale accepted rows remain immutable history. `show`/export set
`definition_changed=true`. They are not currently publishable.

## 11. Conflict detection

Reject accepting a second **current + accepted + exact** mapping whose source
concept and overlapping scope point at a different metric, or a duplicate
current accepted `exact` for the same concept+metric+overlapping scope. Include
**stale** current accepted `exact` rows until revoked. Ignore candidates,
rejected, and superseded rows.

Accept locks `source.concept` with `SELECT … FOR UPDATE` before the overlap
query and insert.

## 12. Interval semantics

Two shared helpers; not one SQL predicate reused for two questions.

**`contains(report_period_end)`** (affected facts):

```text
both bounds NULL:
    report_period_end may be NULL

otherwise:
    report_period_end IS NOT NULL
    AND (valid_from IS NULL OR report_period_end >= valid_from)
    AND (valid_to   IS NULL OR report_period_end <= valid_to)
```

**`overlaps(other_interval)`** (acceptance conflict): NULL endpoints behave as
±infinity. Two issuer scopes overlap only for the same `issuer_cik`; global
overlaps every issuer.

Contains uses `source.filing.report_period_end`, not the fact context period.

## 13. Evidence provenance

Durable evidence may include accession, document identity/hash, source locator,
and QName. Snapshots live in `data`. Do **not** persist `source_fact_ids` or
treat filing surrogate IDs as the primary filing identity. Live fact IDs may
appear only on `MappingFactView`.

## 14. `show <id>` is the named revision

Assertion IDs identify revisions. `edgar mappings show 14` displays revision
`#14`, marks current vs superseded, and includes the full chain. It does not
silently resolve to the tip.

`definition_changed` compares the assertion hash to current YAML.
Mirror-out-of-sync is a separate warning (`mirror_out_of_sync`), not a
substitute for that flag.

Default `show` includes the first 25 affected facts; `--include-facts` returns
every qualifying occurrence.

## 15. List and export visibility

Default list and export are **current revisions of every status**, including
candidate and rejected. Filterable by status, relation, metric, issuer CIK, and
Clark concept. Superseded rows appear only in history.

Export order: source namespace, local name, scope, issuer, target metric,
relation, assertion id. JSON key order is sorted. Formats: JSON, JSONL,
Markdown. The MappingReport JSON Schema is committed under
`registry/schema/mapping-report.schema.json`.

## 16. Affected facts

Enumeration is a live query, never a persisted array:

```text
source.fact
  JOIN source.xbrl_report
  JOIN source.filing
WHERE fact.concept_id = assertion.source_concept_id
  AND (global OR filing.issuer_cik = assertion.issuer_cik)
  AND contains(report_period_end)
```

Return every qualifying occurrence (no dedup). Deterministic order: accession,
`report_period_end` NULLS LAST, source document, source locator, current fact
id.

## Explicit non-goals

No `semantic.*` / `metric_observation` / SQLMesh; no observation policy; no
candidate generation; no LLM; no in-place status updates; no prefix identity;
no PostgreSQL-authored metric definitions; no cascade-delete of mapping
history; no durable `source_fact_ids`; no treating candidates as accepted
knowledge; no accept against a stale mirror or a stale candidate hash; no 2D
publication path through a stale accepted assertion.
