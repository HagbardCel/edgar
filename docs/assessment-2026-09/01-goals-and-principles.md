# 01 — Goals and design principles

These goals are derived from the mission in `AGENTS.md`, the M0 benchmark, and the stated research
use (quantitative and textual research on SEC filings). They are restated independently, so the
adopted plan can be judged against them rather than against itself.

## Product in one sentence

For every SEC registrant filing 10-K/10-Q forms:

- **Preserve** what was filed.
- **Extract** what it states, faithfully.
- **Publish** point-in-time-correct canonical financial observations with explicit semantics.

Every published number must be traceable to a specific fact in a specific filing, via rules that a
reviewer can read, test and change in one place.

## Functional goals

1. **Evidence preservation.** Keep the filed bytes, and the SEC-generated companions, immutably and
   hash-addressed. Any derived output can be rebuilt from them offline.
2. **Faithful extraction.** Extract facts with their exact decimal value, lexical form, decimals,
   unit, period, entity and dimensions. Extract concept declarations, labels (including
   documentation), references and relationship networks, plus document text with locators. Nothing
   is silently dropped, coerced or invented.
3. **Canonical metric contracts.** Maintain a small, versioned vocabulary of metrics. Each has an
   explicit meaning, unit dimension, period type, sign and scope (for example consolidated vs
   segment, and parent vs total).
4. **Mapping.** Relate filed concepts to contracts with an explicit relation (exact, broader,
   narrower, related) and scope conditions. A relation is justified by evidence and reusable across
   filings and issuers wherever the underlying semantics are shared.
5. **Observation selection.** For each issuer, metric and fiscal period, choose the supporting fact
   or facts deterministically, or report a typed reason for not publishing: missing, conflict,
   unmapped candidate, or unsupported.
6. **Point-in-time correctness.** Know when each value became publicly available (the SEC acceptance
   time) and which filing supplied it. Support "as first reported" and "latest as of T" views,
   including amendments and restatements.
7. **Research outputs.** Produce versioned, reproducible datasets with a manifest, suitable for
   analysis in Python/SQL, joinable to securities and market data later.
8. **Coverage at market scale.** Handle the full EDGAR 10-K/10-Q population: roughly 25–30k filings
   per year, more than 15 years of XBRL, tens of thousands of issuers.
9. **Measured quality.** Continuously measure and report accuracy, coverage and conflict rates by
   metric, industry and method, against independent references.
10. **Minimal human effort.** Human judgement is spent on reusable decisions (contracts, policies,
    rules for concept families) and on residual exceptions, never on routine per-filing
    confirmation.

## Engineering and design principles

1. **One owner per kind of truth.**
   - Raw bytes live in the object store.
   - Human knowledge (contracts, decision records, gold values) lives in Git.
   - Everything else is derived and rebuildable.

   Never keep two authoritative copies that need synchronization checks.
2. **Derived state is disposable.** Anything computable from raw bytes plus versioned code and
   knowledge carries its producer version. It is replaced, not migrated, when the producer changes.
3. **Rules over reviews.** Prefer a rule that decides a class of cases, applied and tested
   uniformly, over per-instance confirmation. Review effort should scale with the number of distinct
   semantics, not with filings × metrics.
4. **Standards before inventions.** Use what the XBRL/EDGAR ecosystem already specifies:
   - taxonomy definitions;
   - EDGAR Filer Manual context and role conventions;
   - duplicate-fact consistency rules;
   - calculation semantics;
   - SEC-published structured data as an oracle.

   Use them before designing local frameworks.
5. **Fail closed at the edges, not everywhere.** Validate untrusted input once, at the boundary where
   it enters a trusted representation. Internal code trusts its own typed data; re-verification
   belongs in tests, not in every layer.
6. **Deterministic core, probabilistic periphery.**
   - Canonical outputs come from deterministic code and reviewed rules.
   - Statistical or LLM components may propose.
   - Deterministic proofs or humans accept.
7. **Measure before building.** No new infrastructure layer without a measured problem it solves:
   performance, correctness failure, or scale limit.
8. **End-to-end early.** Every milestone should produce a user-visible increment: more metrics, more
   filings, better measured quality.
9. **Small, flat, typed Python.** One representation per concept. Plain functions over service
   objects. I/O at the edges. `Decimal` for values.
10. **Proportionate tests.** Test domain truths (fixtures of real filing behavior, invariants,
    golden outputs), not the ceremony around them.
11. **Short, current documentation.** One architecture document that describes what exists. ADRs for
    decisions. Plans are temporary and deleted or archived when executed or abandoned.
12. **Conservative interpretation remains non-negotiable.** Simplicity must not collapse semantic
    distinctions, such as:
    - broader vs narrower;
    - segment vs consolidated;
    - parent vs total net income;
    - GAAP vs non-GAAP;
    - quarter vs year-to-date.

## Non-goals (for now)

- Web applications, distributed queues, cloud infrastructure, multi-user concurrency.
- Guaranteed values for every issuer and period; a typed "not published" is a valid output.
- Full standardization of all line items; start from a curated set of research metrics.
- Re-implementing XBRL validation that Arelle or SEC already performs.

## A decision test for new mechanisms

Before adding a table, hash scheme, lifecycle state, protocol version or verification pass, answer:

1. Which functional goal fails without it, and how would we observe the failure?
2. Is there an ecosystem standard or existing component that already does it?
3. Does it create a second copy of some truth?
4. What does it cost per filing at 400k filings, and per human decision?
5. Can it be added later without rework if we skip it now?

If the answer to (5) is yes and (1) has no observed failure, defer it.
