# Architecture

**Status:** Phase 1 production architecture (post–Slice 0).

## Mission

Preserve immutable SEC filing evidence, parse deterministic document structure and XBRL semantics, and enable offline replay. Canonical metric mapping is deferred to Phase 2.

Persistence detail lives in [`docs/data-model.md`](data-model.md) and [ADR 0008](adr/0008-lean-xbrl-semantic-projection.md).

## Layering

```text
CLI / orchestration
 ↓
application services
 ↓
domain models and protocols
 ↓
adapters: SEC HTTP, filesystem, PostgreSQL, Arelle, optional LLM
```

Rules:

- Domain modules do not import CLI code.
- Parsing code does not access the network.
- SEC HTTP code does not write directly to database tables.
- Filesystem writes go through the storage abstraction.
- SQLAlchemy models are not the universal domain API.
- Arelle objects stay inside the XBRL adapter.
- Canonical ingestion/parsing modules do not import LLM implementations.
- Production modules must not import from `scripts/spikes/`.

## Production flow

The **immutable FilingBundle** is the offline boundary:

```text
SEC → Acquisition service → Immutable FilingBundle
         ├─ offline ─┬─ Arelle adapter → resolved semantic records ─┐
         │           └─ Document parser → document records ─────────┤
         └─────────────────── Application persistence ──────────────┘
                                      ↓
                             PostgreSQL repository
```

Rules at the offline boundary:

- Parsers get **no HTTP client**.
- Arelle uses a **bundle-backed resolver**.
- External networking is denied.
- Offline parsing may **not** consult an ambient Arelle cache, prior run state, or undeclared local taxonomy resources. Network denial alone is insufficient ([ADR 0007](adr/0007-manifest-only-replay-uri-bindings.md)).
- An XBRL report load input may be **one or more** URI bindings: an ordinary instance or an Inline XBRL Document Set (IXDS). Production must not assume one report ≡ one source document URI.

## Storage

Laptop-first design ([ADR 0001](adr/0001-postgres-and-filesystem.md), [ADR 0002](adr/0002-immutable-raw-layer.md)):

| Concern | Choice |
| --- | --- |
| Metadata and structured evidence | Local PostgreSQL |
| Immutable bytes | Content-addressed filesystem (`objects/sha256/{aa}/{sha256}`) |
| Payload content identity | `payload_hash` over deterministic payload artifact contents |
| Replay contract | Explicit canonical URI → bundle artifact bindings (separate from `payload_hash`) |

No object-storage service is required in Phase 1. `payload_hash` identifies payload contents; it is not a complete FilingBundle identity by itself (see [`docs/data-model.md`](data-model.md)).

## Acquisition outline

```text
CIK + accession
 → SEC directory / index enumeration
 → download accession files and capture DTS closure (online)
 → content-addressed objects
 → immutable FilingBundle (artifacts, report inputs, URI bindings)
 → offline Arelle / document parsing with networking disabled
 → application persistence → PostgreSQL
```

Filesystem-first durable acquisition is the next implementation step (Phase 1A / PR #4). Database/catalog foundation follows; thin Arelle and document projections come after that.

## Slice 0 → production commitments

Slice 0 proved replay and semantic requirements. Production preserves the requirements, not the spike's wire formats or ceremony ([spike conclusions](spikes/0001-arelle-offline-closure.md)):

| Carry forward | Do not carry forward as production API/model |
| --- | --- |
| Arelle as authoritative XBRL semantic engine | Replication of `ModelXbrl` / the entire loaded DTS in PostgreSQL |
| Effective presentation, calculation, and definition relationships | Raw XLink locator/arc/linkbase tables |
| Immutable filing bundle and deterministic offline replay | Every Slice 0 hash and serialization version |
| Explicit URI → artifact resolution for replay-required documents | `uri-bindings-v2` as a permanent application API |
| **Atomic visibility/publication of verified immutable bundle state** | **Slice-0 staged promotion ceremony and pre-promotion semantic gate** |
| Unknown Arelle diagnostics must not silently yield a clean/successful extraction | `semantic-run-v2` error-identity hashing frameworks |
| Arelle-exposed labels and references as mapping inputs | Generic graph-edge persistence for resource relationships |
| Source locators for provenance and occurrence semantics | Multi-projection occurrence-hash framework as mandatory runtime |
| Semantic fixture assertions | Giant inspection snapshots as the normal fixture pattern |

## Phase 1 implementation order

Post–architecture implementation dependency (GitHub PR sequencing):

```text
1A Filesystem acquisition (PR #4)
 → DB / catalog foundation (PR #5)
 → 1B Thin Arelle semantic projection (PR #6)
 → 1C Document blocks / sections (PR #7)
 → 1D Acceptance; retire Slice-0 executable machinery (PR #8)
```

Capability experiments (metrics after 1B, text after 1C) may begin once the corresponding evidence exists. Metric mapping remains Phase 2.
