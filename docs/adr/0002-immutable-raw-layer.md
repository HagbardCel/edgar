# ADR 0002: Immutable raw layer

- **Status:** Accepted
- **Date:** 2026-07-30
- **Updated:** 2026-08-07 (PR #3)

## Context

SEC filings are legal source evidence. Overwriting downloaded bytes, or silently mutating manifests, destroys reproducibility and auditability.

## Decision

Raw SEC artifacts are **immutable**:

- Every object has a SHA-256 hash.
- Writes use temporary file + atomic rename.
- Never overwrite verified bytes with different bytes.
- Paths are relative to the configured data root.
- Parsing must work with network disabled.
- `payload_hash` identifies the deterministic **payload snapshot/inventory** under the applicable payload-hash contract. It excludes the authoritative replay contract and volatile operational metadata such as retrieval timestamps. The exact production hash construction is **not** frozen by this ADR.
- `payload_hash` is **not a complete FilingBundle identity**. A complete FilingBundle must also distinguish the authoritative replay contract, including report inputs and URI bindings, as specified by [ADR 0008](0008-lean-xbrl-semantic-projection.md) and [`docs/data-model.md`](../data-model.md). This ADR does **not** define the exact FilingBundle equality or reuse algorithm.

## Consequences

- Same verified bytes / SHA-256 reuse content objects.
- Same `payload_hash` does **not** necessarily imply the same FilingBundle.
- Parser defects are fixed by regenerating derived outputs, not by editing source artifacts.
- Fixture refresh is an explicit, reviewed workflow.

## Alternatives considered

- Mutable working copies of filings — rejects reproducibility.
- Include retrieval timestamps in payload identity — causes spurious bundle churn.
- Treat `payload_hash` alone as complete FilingBundle identity — rejected once explicit URI bindings / report inputs are part of offline replay (see ADR 0008).
