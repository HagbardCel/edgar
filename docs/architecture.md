# Architecture

**Status:** Phase 2B V2 source cutover (post Phase 2A registry).

## Mission

Preserve immutable SEC filing evidence, extract deterministic document structure
and XBRL semantics into `source.*`, and enable offline replay. Canonical metric
observations remain deferred (Phase 2C+). Curated metric definitions and mapping
rules are Git-authoritative ([ADR 0010](adr/0010-curated-semantic-registry.md)).

Persistence detail: [`docs/data-model.md`](data-model.md). Source extraction
decision: [ADR 0011](adr/0011-source-extraction.md). Historical Phase-1 projection
ADR: [ADR 0008](adr/0008-lean-xbrl-semantic-projection.md) (superseded).

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

The **immutable FilingBundle** is the offline boundary; PostgreSQL holds
**`source.*` only** after extract:

```text
SEC → Acquisition → Immutable FilingBundle (filesystem)
         └─ offline ─┬─ Arelle worker (operation=extract) ─┐
                     └─ Document parser ───────────────────┤
                                      ↓
                         source.* catalog + extraction
                                      ↓
                    metrics/mappings (Git registry; explain on source.*)
```

Rules at the offline boundary:

- Parsers get **no HTTP client**.
- Arelle uses a **bundle-backed resolver** and isolated worker IPC.
- External networking is denied.
- Offline parsing may **not** consult an ambient Arelle cache, prior run state,
  or undeclared local taxonomy resources ([ADR 0007](adr/0007-manifest-only-replay-uri-bindings.md)).
- An XBRL report load input may be **one or more** URI bindings (ordinary
  instance or IXDS).

Live CLI path: `edgar filings retrieve` → `catalog` / `extract` →
`metrics` / `mappings`. Phase-1 `xbrl project` / `documents project` commands
are removed.

## Storage

Laptop-first design ([ADR 0001](adr/0001-postgres-and-filesystem.md),
[ADR 0002](adr/0002-immutable-raw-layer.md)):

| Concern | Choice |
| --- | --- |
| Structured evidence | Local PostgreSQL schema `source` |
| Immutable bytes | Content-addressed filesystem (`objects/sha256/{aa}/{sha256}`) |
| Payload snapshot | `payload_hash` under the applicable payload-hash contract |
| Replay contract | Explicit canonical URI → bundle artifact bindings |
| Metric registry | Git `semantic-registry/` |

Phase-1 public-schema catalog/projection tables are **not** created by
`alembic upgrade head`. Existing Phase-1 databases must be recreated
(baseline revision `0001_source_v2`).

## Acquisition outline

```text
CIK + accession
 → SEC directory / index enumeration
 → download accession files and capture DTS closure (online)
 → content-addressed objects
 → immutable FilingBundle (artifacts, report inputs, URI bindings)
 → offline extract (Arelle + documents) with networking disabled
 → persist into source.*
```

## Related docs

- [`data-model.md`](data-model.md) — `source.*` grains
- [`data-quality.md`](data-quality.md) — quality / fail-closed posture
- [`development.md`](development.md) — local DB, migrations, tests
- [`fixture-policy.md`](fixture-policy.md)
- [`metric-semantics.md`](metric-semantics.md)
