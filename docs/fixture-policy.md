# Fixture policy

**Status:** Working draft. Inventory may expand when a required behavior is not represented. Spike details live in [docs/spikes/0001-arelle-offline-closure.md](spikes/0001-arelle-offline-closure.md) after Slice 0.

## Two fixture classes

### Committed fixtures

Small purpose-built assets for unit and contract tests:

```text
tests/fixtures/unit/
tests/fixtures/contracts/
tests/fixtures/expected/
```

May include XML/HTML fragments, sample indexes, expected inspection JSON, manifests, and hashes. Do not commit complete SEC bundles.

### Downloaded frozen corpus

Full filing bundles outside Git:

```text
var/fixtures/sec/
```

Repository commits:

```text
fixtures/corpus.yaml
fixtures/manifests/   # expected hashes once frozen
```

Commands (planned):

```bash
uv run edgar fixtures fetch
uv run edgar fixtures verify
```

"Frozen" means pinned by accession, acquisition-policy version, and expected payload hashes.

## Attachment policy

Mirror the complete SEC accession directory plus the external XBRL DTS closure captured from the first online Arelle load. No semantic allowlists.

Logical paths:

| Kind | Path |
| --- | --- |
| Accession files | `accession/{original_filename}` |
| Index responses | `metadata/index.json`, `metadata/index.html`, `metadata/index-headers.html` |
| Discovery record | `metadata/discovery.json` |
| External DTS deps | `external/{sha256_of_original_uri}/{sanitized_basename}` |

Complete submission text is kept only under its original accession filename (for example `accession/{accession}.txt`) with `artifact_role = complete_submission`. Do not duplicate it under `metadata/`.

### Payload identity

`payload_hash` covers immutable source / deterministic acquisition snapshots. It excludes:

- the manifest itself
- volatile operational attributes (timestamps, retries, machine info, logs)
- the mutable raw issuer submissions JSON
- the generated offline catalog

Canonical accession discovery (`metadata/discovery.json`) **is** included. Raw submissions responses may be retained as provenance but are excluded from payload identity.

### Completeness severity

- **Fatal:** missing filer-submitted indexed attachment, missing primary document, missing complete submission text, unresolved XBRL dependency required for offline load, payload hash mismatch.
- **Warning:** missing optional SEC-generated rendering files when canonical parsing does not require them.

### Size safeguards

Configurable limits: `MAX_FILE_BYTES`, `MAX_BUNDLE_BYTES`, `MAX_EXTERNAL_DEPENDENCY_BYTES`, `MAX_REDIRECTS`. Breaches stop acquisition, mark the bundle incomplete, and emit a structured quality issue.

## Initial micro-corpus

See [fixtures/corpus.yaml](../fixtures/corpus.yaml).

Minimum coverage across the set:

- Material issuer extension concepts
- Dimensional disclosures (explicit; typed if available)
- Awkward or malformed HTML (add a sixth filing if needed)
- Multiple statement roles
- Inline XBRL continuation chains (at least one)
- Numeric and non-numeric Inline XBRL facts (at least one)
- Duplicate visual fact presentations (ideally)
- Taxonomy transition (desirable, not mandatory)

## Expectation split

For each full filing fixture:

1. **Acquisition expectations** — inventory, payload hash, external dependency inventory, closure hash, completeness classification.
2. **Parser expectations** — document/concept/context/unit/fact/relationship counts, selected known facts, continuation chains, extension concepts.

Do not require parser counts to be part of the acquisition manifest.
