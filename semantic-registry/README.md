# Curated semantic registry

Git-authoritative metric ontology and approved mapping rules for Phase 2A.

## Files

| File | Contents |
| --- | --- |
| `metric-families.json` | Organizational family metadata |
| `metric-definitions.json` | Versioned measurement contracts (`definition_version` = economic semantics) |
| `mapping-rules.json` | Human-approved concept→metric decisions |

The loaded registry exposes a single `registry_hash` over canonical `{families, definitions, rules}`.

## CLI (Git-only except explain)

```bash
uv run edgar metrics list
uv run edgar metrics show operating_company_revenue --version 1
uv run edgar mappings list
uv run edgar mappings export --format json
uv run edgar mappings explain <rule_key>   # requires DB + pinned projection evidence
```

`mappings export` is DB-free. `mappings explain` resolves pinned `ProjectionConceptEvidence` only; it displays scope metadata but does not apply scope-based applicability (Phase 2B).

## Evidence

Mapping rules pin:

- `bundle_fingerprint` (from `bundle_fingerprint()` in `src/edgar/domain/bundle.py`)
- semantic projection identity (`projection_version`, `arelle_version`, `semantic_config_fingerprint`)
- concept QName

Do not use `filing_bundle_opaque_id` in authoritative evidence.

## Governance

- Only human-reviewed rules belong in `mapping-rules.json`.
- Semantic changes to approved rules → new `rule_key` + `supersedes`.
- Do not fabricate `reviewed_by`.

See [docs/adr/0010-curated-semantic-registry.md](../docs/adr/0010-curated-semantic-registry.md).
