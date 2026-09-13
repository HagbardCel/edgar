# Historical Phase 2A semantic registry (superseded)

This directory is **not live authority**. It is retained as a historical archive of
the Phase 2A Git mapping store.

Live Phase 2C surfaces:

- Canonical metric contracts: [`registry/metrics.yml`](../registry/metrics.yml)
- Mapping decisions: PostgreSQL `registry.mapping_assertion`
- CLI: `edgar registry validate|sync`, `edgar metrics list|show`, `edgar mappings …`

Do not load these JSON files from production code. See the Phase 2C amendment in
[ADR 0010](../docs/adr/0010-curated-semantic-registry.md).
