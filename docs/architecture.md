# Architecture

**Status:** Working draft for Slice 0. Finalize after the Arelle offline-closure spike.

## Mission

Preserve immutable SEC filing evidence, parse deterministic document structure and XBRL semantics, and enable offline replay. Canonical metric mapping is deferred to Phase 2.

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

## Storage

Laptop-first design:

| Concern | Choice |
| --- | --- |
| Metadata and structured evidence | Local PostgreSQL |
| Immutable bytes | Content-addressed filesystem (`objects/sha256/{aa}/{sha256}`) |
| Bundle identity | `payload_hash` over deterministic source files |
| Replay aid | Generated offline catalog (excluded from `payload_hash`) |

No object-storage service is required in Phase 1.

## Acquisition flow

```text
CIK + accession
 → SEC directory / index enumeration
 → download accession files
 → capture external DTS closure (first online Arelle load)
 → content-addressed objects + artifact rows
 → discovery.json (accession-specific, deterministic)
 → manifest (describes payload; not part of payload_hash)
 → offline catalog (regenerable; not part of payload_hash)
 → offline Arelle reload with network disabled
```

## Parallel Phase 1 tracks

```text
1A Acquisition ──┬──► 1B XBRL evidence ──┐
                 └──► 1C Document text ──┴──► 1D Acceptance
```

Metric experiments may begin after 1B. Text experiments may begin after 1C.

## Slice 0 boundary

Slice 0 validates attachment policy and offline Arelle closure **without PostgreSQL**. Evidence is retained under `var/spikes/`; spike code under `scripts/spikes/` has no compatibility guarantee.
