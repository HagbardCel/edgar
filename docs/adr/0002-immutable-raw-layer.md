# ADR 0002: Immutable raw layer

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

SEC filings are legal source evidence. Overwriting downloaded bytes, or silently mutating manifests, destroys reproducibility and auditability.

## Decision

Raw SEC artifacts are **immutable**:

- Every object has a SHA-256 hash.
- Writes use temporary file + atomic rename.
- Never overwrite verified bytes with different bytes.
- Paths are relative to the configured data root.
- Parsing must work with network disabled.
- Bundle identity is `payload_hash` over deterministic source snapshots (manifest and volatile operational metadata excluded).

## Consequences

- Reacquisition of identical bytes reuses content objects and, under the same policy, the same bundle identity.
- Parser defects are fixed by regenerating derived outputs, not by editing source artifacts.
- Fixture refresh is an explicit, reviewed workflow.

## Alternatives considered

- Mutable working copies of filings — rejects reproducibility.
- Include retrieval timestamps in payload identity — causes spurious bundle churn.
