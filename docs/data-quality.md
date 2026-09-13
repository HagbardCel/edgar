# Data quality

Documentation scope: this file describes the implemented baseline. Proposed changes are in the [target package](architecture/README.md); see the [documentation index](README.md) for status and authority.

**Status:** Operational posture for V2 source extraction.

## Principles

- Prefer fail-closed representation over silent loss of filed evidence.
- Unrecognized Arelle diagnostics block “complete” extraction status unless
  classified complete-compatible under the versioned diagnostic policy.
- Nil, invalid, and unresolved facts remain rows with explicit status — not drops.
- Extension concepts and issuer networks are preserved; QName similarity is never
  economic equivalence.
- Document sections that cannot be located become extraction issues, not invented
  text.

## Provenance

Every persisted `source.*` extraction row traces to:

- filing accession / `source.filing`
- filesystem FilingBundle (payload + URI bindings)
- report key / document path
- parser / Arelle version recorded on the report or block rows

## Idempotency

- Catalog: natural uniqueness on accession and document paths.
- Extract: transactional replace of extraction-owned rows for a filing.
- Reruns must not duplicate catalog identity or leave partial extraction state
  marked successful.

## What quality does *not* mean

- Automatic acceptance of canonical metrics (observation selection remains Phase 2D+, unimplemented).
- LLM auto-approval of ambiguous mapping rules.
- Ambient cache or network fetches during offline extract.
