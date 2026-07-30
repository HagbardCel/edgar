# Planning Artifact Update

## Updated artifacts

### `docs/phase-1-plan.md`

Changes:

- Added XBRL labels and references to Phase 1.
- Added role and arcrole definitions.
- Added presentation, calculation, and definition networks.
- Added inline fact-to-document provenance.
- Expanded schema, CLI, tests, fixtures, and acceptance criteria.
- Clarified that canonical metric mapping remains out of scope.
- Added a Phase 2 readiness gate so mappings can begin without reparsing source filings.

### `AGENTS.md`

Changes:

- Added semantic-fidelity invariants.
- Prohibited name- or label-only metric equivalence.
- Added preservation requirements for taxonomy networks.
- Added later-phase metric mapping rules and LLM restrictions.
- Added relationship-specific test and completion requirements.
- Added references to the full project roadmap and metric-semantics document.

### New: `docs/metric-semantics.md`

Defines:

- raw fact, filed observation, canonical metric, and research feature layers
- metric-family and measurement-contract model
- typed mapping relationships
- global/industry/issuer/period scopes
- candidate generation, hard checks, evidence scoring, validation, and review
- quality tiers
- local-LLM role
- research sensitivity requirements

### New: `docs/project-roadmap.md`

Defines the complete project from product specification through:

1. filing/XBRL foundation
2. metric ontology and mapping
3. period/restatement normalization
4. historical scaling
5. security and market data
6. empirical research datasets
7. filing text intelligence
8. analytical applications
9. operational hardening
