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
uv run edgar mappings explain <rule_key>   # requires DB + pinned source.* evidence
```

`mappings export` is DB-free. `mappings explain` resolves pinned `SourceConceptEvidence` only; it displays scope metadata but does not apply scope-based applicability (Phase 2B).

## Evidence

Mapping rules pin:

- `accession_number` (canonical dashed form)
- concept expanded QName (`namespace_uri` + `local_name`)

Explain returns one enrichment section per matching `source.xbrl_report` for that filing. `arelle_version` may appear as optional display metadata on report payloads but is not part of pin identity.

Do not use `filing_bundle_opaque_id`, `bundle_fingerprint`, `projection_version`, or `semantic_config_fingerprint` in authoritative evidence.

## Governance

- `mapping-rules.json` contains only human-approved rules — never synthetic
  integration-test decisions or provisional candidates.
- Phase 2A close-out state: three reviewed real-corpus rules with relationship
  types `equivalent`, `broader_than`, and `incompatible` (count is the close-out
  ledger, not a permanent fixed size).
- Provisional candidates remain outside the authoritative registry until approved.
- Workflow: propose candidate + evidence packet → human reviews filing/XBRL
  evidence → human records `reviewed_by` / `reviewed_at` → rule committed to Git.
- Semantic changes to approved rules → new `rule_key` + `supersedes`.
- Do not fabricate `reviewed_by`.

See [docs/adr/0010-curated-semantic-registry.md](../docs/adr/0010-curated-semantic-registry.md).
