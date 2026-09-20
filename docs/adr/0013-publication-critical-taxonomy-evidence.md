# ADR 0013: Publication-critical official taxonomy evidence is M1A

- **Status:** Accepted
- **Date:** 2026-09-13
- **Clarifies:** [ADR 0012](0012-adopt-bounded-financial-architecture.md) phase
  ownership only
- **Does not change:** D1–D9 semantic architecture; the frozen exact-review
  profile (`registry/review-profile.yml`); M0 economic assessments; source
  architecture; registry authority; or M3 release strictness

## Context

M0 froze a bounded independently reviewed benchmark and one exact-review
profile. Nine `relation=exact` cases record `declaration_definition` as
`not_assessed` because affirmative US-GAAP concept definition/documentation is
absent from the resolved filing DTS under closed-world offline replay. Those
cases correctly classified the gap as `official_taxonomy_evidence`, but labelled
`required_phase: M5`.

That sequencing is inconsistent with the adopted migration:

```text
M0 → M1A → M2 → M3 → M4
```

with M5 as an evidence-triggered extensions menu. M2 requires exact-review
profile evidence for release mappings; M3 requires nine non-vacuous annual core
value slots (six of which are among the nine blocked cases). Deferring required
affirmative evidence to M5 would make M3 publication-critical work depend on an
optional later menu item.

The epistemic assessment itself is sound. Only phase ownership was wrong.

## Decision

1. **Named release-blocking official-taxonomy evidence belongs to M1A.**
   Bounded, pinned official US-GAAP taxonomy packages required by the nine M0
   benchmark cases (and any later named release case with the same gap) are
   publication-critical M1A scope: resolve the authoritative package/release,
   acquire through a controlled path, pin publisher URL + package/release
   identity + artifact hash, and inspect declaration/documentation in isolation
   via a bounded offline Arelle reader producing an external evidence packet.

2. **Generalized taxonomy continuity, indexing, and reuse remain M5.** Cross-
   release continuity, reusable equivalence policies, an official taxonomy
   package index, and generalized reuse infrastructure stay in the M5 menu until
   demonstrated need justifies them. M1A does not introduce a package index or
   warehouse.

3. **Filing DTS and official-package evidence stay separate.** Official packages
   must not be loaded into a filing's DTS so that external documentation appears
   filing-sourced. No ambient installed taxonomy package, Arelle cache, or
   network fallback may silently alter closed-world filing replay. Package
   identity must not be inferred solely from a Clark QName namespace string;
   M1A verifies and records the package/release in the evidence packet.

4. **Profile and assessment bytes remain frozen.** This ADR does not amend
   `registry/review-profile.yml` or M0 `review_assessment` content. Required
   affirmative evidence still cannot pass as `not_assessed`, `unsupported`, or
   `assessed_absent`. `assessed_absent` after a complete search is an honest
   terminal assessment but does not make an exact claim publication-eligible.

5. **Inherited M1A requirement shape.** For each of the nine cases, M1A inherits:

   ```text
   (case_id, exact Clark QName, official-taxonomy affirmative evidence required)
   ```

   Actual package/release identity is resolved and pinned during M1A, not frozen
   by this convergence correction.

## Consequences

- Living migration and architecture docs treat bounded official-taxonomy
  evidence for named publication cases as M1A work.
- `derive_m1a_requirements()` will include `official_taxonomy_evidence` once
  benchmark cases carry `required_phase: M1A` for that capability.
- ADR 0012 remains the adopted migration authority; this ADR corrects only the
  M1A/M5 ownership boundary demonstrated by the M0 benchmark.
- Agents must not implement M5 continuity/indexing ahead of its gate in order
  to clear these nine cases.

## Alternatives considered

- **Weaken the exact-review profile or waive `declaration_definition`** —
  Rejected: would falsify the frozen evidence standard.
- **Leave ownership at M5 and accept a pre-M3 gap** — Rejected: contradicts M2
  profile evidence and M3's nine-slot release gate.
- **Edit ADR 0012 in place** — Rejected: ADR 0012 is accepted historical
  evidence; a later ADR is the mechanism ADR 0012 already anticipates for
  replacing a forward-looking assumption.
- **Introduce a package index or taxonomy warehouse in M1A** — Rejected:
  exceeds the named-case evidence need; remains M5.
