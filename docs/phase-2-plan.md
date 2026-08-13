# Phase 2 plan

**Status:** Phase 2A implemented. Phase 2B (deterministic mapping engine) is next.

## Objective

Convert selected raw XBRL facts into precise, auditable canonical observations while preserving fundamental economic distinctions. Phase 2A establishes the semantic contract layer only.

## Sub-phases

```text
Phase 2A  Metric ontology + curated mapping registry   (PR #9)
Phase 2B  Deterministic mapping engine                 (PR #10)
Phase 2C  Review / acceptance + canonical observations
Phase 2D  Longitudinal validation + quality reporting
```

### Phase 2A (current)

Deliverables:

- Git-authoritative `semantic-registry/` (families, 20 v1 definitions, curated mapping rules)
- Pydantic validation, frozen canonical-v1 hashing, cross-record validation
- PostgreSQL materialization (`metric_family`, `metric_definition`, `metric_mapping_rule`, `semantic_registry_revision`)
- `edgar metrics` / `edgar mappings` CLI (sync, list, show, explain, export)
- No `metric_observation`, candidate generation, precedence, or LLM auto-approval

Exit gate: see [phase-2-data-model.md](phase-2-data-model.md) and ADR 0010.

### Phase 2B

- Candidate generation from taxonomy identity and networks
- Hard compatibility filters against metric contracts
- Rule precedence among **current** rules
- Still no canonical observations until 2C acceptance workflow

### Phase 2C–2D

- Human acceptance of fact-level mappings
- `metric_observation` production
- Longitudinal validation and quality tiers

## Dependencies

Phase 2A requires Phase 1 evidence: concept identity, labels, references, networks, contexts, dimensions, facts, projection identity. Contract drafting may proceed in parallel with Phase 1D; registry sync requires cataloged projections for citation resolution.

## Non-goals (Phase 2A)

Automatic candidates, embeddings, LLM mapping, derived metrics, industry master, web UI, canonical observations.

## Local real-corpus acceptance (pre-merge gate)

After cataloging and projecting corpus filings referenced in `semantic-registry/mapping-rules.json`:

```bash
./scripts/phase2a_acceptance.sh
```

Record the run in the PR. Synthetic A–F cases run in CI via `tests/integration/test_metric_semantic_acceptance.py`.
