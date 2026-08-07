# ADR 0003: No LLM in the critical path

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

Local coding LLMs are useful for development, diagnostics, and later experimental mapping suggestions. They must not become sources of truth for filings, facts, or canonical metric decisions.

## Decision

LLMs are **outside** the canonical ingestion and parsing path:

- The system must start, test, ingest, and parse with `LLM_ENABLED=false`.
- No LLM may invent filing text or facts, alter source artifacts, auto-approve ambiguous mappings, or refresh golden files without review.
- Any code-mediated LLM call records purpose, prompt version, model identity, input hash, parameters, and failures, stored separately from canonical decisions.

## Consequences

- Canonical modules do not import LLM implementations.
- Experimental notebooks and assistants remain optional.
- Phase 2 mapping review stays human-accountable.

## Alternatives considered

- LLM-assisted section extraction in Phase 1 canonical path — rejected; heuristics must be deterministic and fixture-tested.
- LLM as SEC downloader — rejected; use the shared SEC HTTP client only.
