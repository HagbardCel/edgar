# Curated semantic registry

Git-authoritative metric ontology and approved mapping rules for Phase 2A.

## Files

| File | Contents |
| --- | --- |
| `metric-families.json` | Organizational family metadata |
| `metric-definitions.json` | Versioned measurement contracts |
| `mapping-rules.json` | Human-approved concept→metric decisions only |

All files share the same `registry_schema_version`. Immutable records carry their own schema version (`definition_schema_version`, `rule_schema_version`).

## Sync

```bash
uv run edgar metrics sync
```

Requires PostgreSQL and Phase 1 `concept_identity` rows for every mapping rule source QName. Evidence citations must resolve to exactly one persisted projection artifact.

## Read

```bash
uv run edgar metrics list
uv run edgar metrics show operating_company_revenue --version 1
uv run edgar mappings list
uv run edgar mappings explain map-000001
uv run edgar mappings export --format markdown
```

Public reads fail with **sync required** when Git `registry_hash` ≠ latest DB revision.

## Governance

- Only human-reviewed rules belong in `mapping-rules.json`.
- Do not fabricate `reviewed_by`.
- LLM proposals stay outside this directory until reviewed.

See [docs/adr/0010-curated-semantic-registry.md](../docs/adr/0010-curated-semantic-registry.md).
