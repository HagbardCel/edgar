# ADR 0001: PostgreSQL and filesystem

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

Phase 1 needs durable metadata, relational XBRL evidence, and immutable source bytes. The target environment is a developer laptop, not cloud infrastructure.

## Decision

Use **local PostgreSQL** for metadata and structured parser outputs, and a **content-addressed local filesystem** for immutable artifact bytes (`objects/sha256/{first_two}/{sha256}`).

Do not introduce an object-storage service, distributed queue, or cloud dependency in Phase 1.

## Consequences

- Schema changes go through Alembic.
- Bytes are deduplicated by SHA-256; logical presence in a bundle is modeled separately (`artifact`).
- Offline replay reads local objects only.
- Operational simplicity stays high for laptop-first development.

## Alternatives considered

- SQLite for everything — weaker concurrency and NUMERIC/JSON ergonomics for this domain.
- S3-compatible object storage — unnecessary complexity for Phase 1.
- Store all bytes in PostgreSQL BYTEA — bloats the database and complicates large taxonomy closures.
