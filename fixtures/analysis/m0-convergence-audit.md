# M0 post-merge convergence audit

Recorded: 2026-09-13 (UTC)

Role: post-merge architectural findings after PR #14 landed M0 on `main`.
This file is separate from [`m0-inventory.md`](m0-inventory.md) (timestamped
2026-09-07 working-state snapshot) and [`m0-restore-report.md`](m0-restore-report.md)
(restore proof).

## Baseline topology (correct — do not reopen)

```text
actual main merge:
  commit = eaeafa9e4849f29f0b07bab9a9e74c1ef9277fc8
  tree   = 32176c40cac247f2179cf7a525eb17082ea92dd7

M0 reviewed head (preserved):
  commit = 303af7403df6506a06934750c7cdb429b633d557
```

PR #14 itself is complete. Step 3 merge mechanics are correct. No revert or
redo of that PR is warranted.

## Findings

| Finding | Severity | Status |
|---|---|---|
| Nine benchmark cases gate `official_taxonomy_evidence` at `required_phase: M5` while exact-review `declaration_definition` is `not_assessed` and blocks M2; six of nine are M3 `CORE_VALUE_SLOTS` | P1 | Remediated in Step 5 (ADR 0013 + phase reclassification) |
| `core_value_slot_replacements` credits original slots without resolving replacement to a real `state=value` case | P2 | Remediated in Step 5 (validator hardening) |
| Fresh PR CI synthetic merge used `303af740 → 9ec101a` rather than `303af740 → a533579` | Audit observation | No action |

### P1 — Pre-M3 vs M5 evidence sequencing

Dependency chain:

```text
M3 core value
  → exact review profile (frozen)
  → declaration_definition required
  → nine cases: not_assessed (honest — filing DTS lacks affirmative definitions)
  → official_taxonomy_evidence gated at required_phase: M5
  → M5 is after / optional relative to M3
```

**Resolution principle:** reclassify phase ownership, not epistemic assessment.
The benchmark correctly records that affirmative definition evidence is absent
from the resolved filing DTS under closed-world offline replay. Only the
`required_phase` label was wrong. Named publication-critical official-taxonomy
evidence belongs to M1A; generalized continuity, indexing, and reuse remain M5.
See [ADR 0013](../../docs/adr/0013-publication-critical-taxonomy-evidence.md).

Frozen invariants preserved by remediation:

```text
registry/review-profile.yml — byte-for-byte unchanged
review_assessment / evidence_pins / conclusions — unchanged
only capability phase ownership + architecture sequencing corrected
```

### P2 — Dormant replacement validator weakness

`validate_benchmark_static()` accepted any string pair for
`replacement_metric_key` / `replacement_accession` and credited the original
core slot without resolving a real `state=value` benchmark case. The live M0
benchmark has no active replacements, so today's nine-slot result was unaffected;
a future bogus replacement could falsely green validation. Step 5 hardens the
escape hatch to a single `replacement_case_id` schema with annual-release and
period-signature bounds.

### CI observation (no action)

```text
fresh PR CI synthetic merge:
  commit = dc2e455…
  tree   = 32176c40…  (same filesystem state as final main merge)
```

CI used the older synthetic graph `303af740 → 9ec101a` rather than
`303af740 → a533579`. Because `tree(a533579) == tree(9ec101a)`, CI tested the
exact filesystem tree that landed. No corrective action warranted.

## Remediated named cases (official_taxonomy_evidence → M1A)

| case_id | metric_key | in CORE_VALUE_SLOTS |
|---|---|---|
| `ebay_fy2022_total_assets_value` | `total_assets` | yes |
| `ebay_fy2022_operating_cash_flow_value` | `operating_cash_flow` | yes |
| `ebay_fy2023_total_assets_value` | `total_assets` | yes |
| `ebay_fy2023_operating_cash_flow_value` | `operating_cash_flow` | yes |
| `walmart_fy2024_total_assets_value` | `total_assets` | yes |
| `walmart_fy2024_operating_cash_flow_value` | `operating_cash_flow` | yes |
| `ebay_fy2023_operating_income_value` | `operating_income` | no |
| `ebay_fy2023_rnd_value` | `research_and_development` | no |
| `ebay_fy2023_cash_ppe_purchases_value` | `cash_purchases_of_ppe` | no |

Three revenue `CORE_VALUE_SLOTS` are not part of this remediation (they already
satisfy `declaration_definition` via issuer policy).
