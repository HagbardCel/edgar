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

### Locally acquired Phase-1 acceptance corpus

Full filing bundles are acquired outside Git under the configured data root:

```text
{EDGAR_DATA_ROOT}/bundles/{cik}/{accession}/{opaque_id}/
```

Repository commits:

```text
fixtures/corpus.toml
fixtures/manifests/   # frozen Slice-0 evidence hashes (one accession)
fixtures/analysis/    # reviewed analysis/benchmark manifests and M0 reports
```

`fixtures/analysis/` contains small reviewed analysis/benchmark manifests and M0 reports
(for example `financial-benchmark.yml`, `m0-inventory.md`, `m0-restore-report.md`).
It does not contain complete filing bundles or copied SEC source artifacts. Full
FilingBundles remain outside Git under `EDGAR_DATA_ROOT`.

Acquire corpus bundles with:

```bash
export EDGAR_DATA_ROOT="$PWD/var/phase1-corpus"
export SEC_USER_AGENT="Your Name your@email.com"
uv run edgar filings retrieve --accession 0001065088-24-000036
```

`edgar fixtures fetch` / `edgar fixtures verify` are **not implemented**. Use `edgar filings retrieve` for the locally acquired acceptance corpus.

Each published `FilingBundle` is immutable once acquired. The repository does **not** yet pin every real-corpus bundle's complete acquisition snapshot across machines. The seven Slice-0 JSON files under `fixtures/manifests/0001065088-24-000036/` remain the committed frozen evidence boundary.

"Frozen" (for that committed evidence) means pinned by accession, acquisition policy/version, expected **payload snapshot/inventory**, and the authoritative replay contract, including required report input(s) and URI bindings necessary to reproduce offline loading. `payload_hash` alone does not identify the complete replay bundle.

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

See [fixtures/corpus.toml](../fixtures/corpus.toml).

Minimum coverage across the set (gate classification):

| Requirement | Gate |
| --- | --- |
| 2× 10-K, 2× 10-Q, amendment | **A** — `make phase1-corpus-acceptance` |
| Multiple industries | **A** — corpus `industry_group` + successful projection |
| Material extension concepts (used in facts/relationships) | **A** — scoped DB evidence |
| Dimensional disclosures | **A** — scoped DB evidence |
| Multiple statement roles (presentation networks) | **A** — scoped DB evidence |
| Taxonomy transition | **A** — one US-GAAP year per projection, same CIK ≥2 years |
| Exact hash / offline replay | **B** — `make phase1-acceptance` (unit + contract + integration) |
| Numeric and non-numeric Inline XBRL facts | **B** — contract tests |
| Duplicate fact multiplicity | **B** — contract + unit tests |
| Awkward / malformed HTML parser behavior | **B** — document parser unit tests |
| Awkward HTML in live corpus | **C** — add filing only if needed |
| Inline XBRL continuation chains | **C** — informational in corpus report |
| Duplicate visual presentations in live corpus | **C** — parser multiplicity covered by **B** |

## Expectation split

For each full filing fixture:

1. **Acquisition expectations** — inventory, payload hash, external dependency inventory, closure hash, completeness classification.
2. **Parser expectations** — document/concept/context/unit/fact/relationship counts, selected known facts, continuation chains, extension concepts.

Do not require parser counts to be part of the acquisition manifest.
