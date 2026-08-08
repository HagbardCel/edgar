# ADR 0009: Filesystem FilingBundle acquisition and offline replay

- **Status:** Accepted
- **Date:** 2026-08-08
- **Phase:** 1A / PR #4

## Context

ADR 0002 deferred exact `payload_hash` construction and FilingBundle equality/reuse.
ADR 0007 locked offline replay invariants without freezing production wire formats.
PR #4 is the first production `src/edgar/` implementation and must freeze only the
filesystem acquisition and offline-replay contracts required for Phase 1A.

SEC citation for IXDS membership: XBRL Guide, June 2026, §1.4 / Table 6-8.

## Decision

### Layout (relative to `EDGAR_DATA_ROOT`)

```text
{data_root}/objects/sha256/{aa}/{sha256}
{data_root}/bundles/{cik}/{accession}/{opaque_id}/bundle.json
{data_root}/acquisition-attempts/{attempt_id}/result.json
{data_root}/locks/{cik}/{accession}.lock
```

Opaque id is UUID4 hex. Do **not** introduce a permanent production `bundle_hash`.

Exact metadata logical paths:

- `metadata/discovery.json`
- `metadata/index.json`
- `metadata/index.html`
- `metadata/index-headers.html`

Accession artifacts: `accession/{original_filename}`.
External DTS: `external/{sha256_of_canonical_requested_uri}/{sanitized_basename}`.

Supported forms: `10-K`, `10-K/A`, `10-Q`, `10-Q/A` only.

### Metadata source roles

| Source | Role |
|--------|------|
| Submissions JSON | Accession metadata; `primaryDocument`; form/dates |
| Archive `index.json` | Physical directory inventory only — no SEC document-type semantics |
| Filing `*-index.html` | Submitted-document table |
| Complete-submission SGML | Authoritative DOCUMENT blocks |

`discovery.json` contains accession-specific stable extracted fields only.
The submissions shard/URL that located the accession belongs in observations, not payload.

### `payload_hash` (`payload-hash-v1`)

SHA-256 hex of UTF-8 bytes from:

```python
json.dumps(
    {"artifacts": [...], "schema": "payload-hash-v1"},
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")  # no trailing newline
```

Artifact records `{byte_size, logical_path, sha256}` with keys sorted; `sha256`
lowercase hex; artifacts sorted by UTF-8 bytes of `logical_path`. Duplicate paths
are invalid. Descriptor, report inputs, URI bindings, observations, timestamps,
raw submissions snapshots, and temp Arelle state are excluded.

`MAX_BUNDLE_BYTES` is the sum of logical payload-member `byte_size` values
(not unique CAS objects), including late external DTS artifacts.

### `uri-identity-v1`

Absolute URI after reference resolution. Relative references resolve against the
referring document’s canonical base first.

- ASCII hosts only (non-ASCII → unsupported).
- IPv6-literal hosts are unsupported in Phase 1 (reject under `uri-identity-v1`).
- Empty query preserved as distinct (`/a` ≠ `/a?`).
- Order: parse → reject credentials/non-http(s) → lowercase scheme/host →
  default-port elision → uppercase percent hex → decode percent-encoded unreserved
  → empty path `/` → remove dot segments → query same percent rules → strip
  fragment → serialize.

### Fetch security

Parent `ControlledFetcher` is the sole network I/O component. Every hop:
`http`/`https` only; no credentials; resolve and validate all candidate IPs;
deny loopback/private/link-local/multicast/unspecified/reserved; connect only to
a pinned validated address; TLS/SNI against the original hostname.

### Shared Arelle subprocess

Online closure and offline replay use the same isolated worker subprocess:

- no `AF_INET` / `AF_INET6`
- closed-world local filesystem (no arbitrary `file:` from filing content)
- isolated config / packages / empty cache / no ambient catalog
- URI resolution via IPC to parent

Online miss → parent fetch. Offline miss → failure.

Materialized local bytes preserve the canonical HTTP(S) document URI/base.

### Report input

Discriminated:

- `InstanceReportInput`: exactly one URI, no target
- `IxdsReportInput`: ordered URIs (≥1), `target="default"`

Primary row: exactly one index-HTML row and one SGML DOCUMENT where
`TYPE == form_type` and filename equals `submissions.primaryDocument`.

IXDS (10-K/Q universe): members are structurally valid Inline XBRL among
reconciled submitted DOCUMENT attachments only. Exclude complete submission
container, `EX-FILING FEES`, SEC-generated artifacts, and metadata. Order:
primary first, then remaining by submitted filename. Independent non-primary
inline instance → `UNSUPPORTED_REPORT_INPUT`.

Traditional path: exactly one filer-submitted `EX-101.INS` with `xbrli:xbrl`
root; never SEC-generated `*_htm.xml`.

### Bundle equality

Normalized domain state (not raw `bundle.json` bytes):

- `schema_version`, `acquisition_policy_version`
- `FilingIdentity`: cik, accession, form_type, filing_date, accepted_at,
  report_period_end, primary_document
- `payload_hash`
- artifacts: logical_path, sha256, byte_size, artifact_kind, required
- report inputs and URI bindings (canonical forms)

Bump `acquisition_policy_version` when membership, report-input identification,
URI-binding construction, fetch-security, or replay contract changes.

### Publication

Accession-scoped lock at `{data_root}/locks/{cik}/{accession}.lock`.
Corrupt published descriptors fail closed. Revalidate before reuse.
Atomic publish: temp write + file fsync + rename + parent-directory fsync.

### Observations

Append-only under `acquisition-attempts/`. Outside FilingBundle identity and
`payload_hash`. Raw submissions CAS retention requires an observation SHA ref.

## Consequences

- Same payload + different URI bindings remain distinguishable.
- Production does not import Slice-0 wire formats or ceremony.
- PR #5 may catalog bundles without changing this filesystem contract.
- PR #6 projects semantics after offline replayability is proven.

## Alternatives considered

- Port Slice-0 `manifest-v3-spike` / `uri-bindings-v2` — rejected; requirements only.
- Permanent `bundle_hash` — rejected by data model.
- `EX-*` as IXDS membership discriminator — incorrect for SEC general IXDS rule.
- Separate-instance exception registry in PR4 — unnecessary for 10-K/Q forms.
- In-process online Arelle with privileged socket bypass — rejected for isolation.
