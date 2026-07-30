# ADR 0005: Amendment relationship semantics

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

The Phase 1 fixture corpus includes an amendment pair (eBay `10-K` and `10-K/A`). Later phases need a clear, conservative model for how amendments relate to original filings before any latest-known or restatement semantics are introduced.

## Decision

An amendment filing **amends** a prior filing. The directed relationship is:

```text
10-K/A --amends--> 10-K
```

This ADR does **not** assert filing-wide supersession. An amendment may affect only a limited portion of the original filing.

Invariants:

- Both filings remain immutable artifacts and remain independently queryable.
- No raw fact, section, or document from the original filing is deleted because an amendment exists.
- The affected scope of an amendment is not presumed to be the entire original filing.
- Point-in-time “latest known” / `known_at` / `superseded_at` observation semantics are deferred to Phase 3 (period normalization and restatements).

## Consequences

- Phase 1 stores an explicit `amends` (or equivalent) filing relationship when discovery evidence supports it.
- Research consumers must not silently replace an original filing with its amendment.
- Phase 3 may later introduce superseded-observation layers without rewriting immutable filing evidence.

## Alternatives considered

- Treat amendments as superseding the entire prior filing — too aggressive; amendments are often partial.
- Defer all amendment modeling until Phase 3 — rejected because the corpus already includes an amendment pair and acquisition must preserve the relationship evidence.
