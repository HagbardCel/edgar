# M0 restore report

Captured: 2026-09-07T07:23:20Z (UTC)

## Target safety

| Check | Result |
|---|---|
| Parsed `EDGAR_TEST_DATABASE_URL` database name | `edgar_test` |
| Assert `database == edgar_test` before destructive ops | **passed** |
| Working DB (`edgar`) touched by restore | **no** |
| `registry sync` performed | **no** |

SQLAlchemy URL was converted to libpq form via `make_url(...).set(drivername="postgresql").render_as_string(hide_password=False)` for `pg_restore` only.

## Procedure

1. Read-only inventory and full custom-format dump of working DB `edgar` → `var/m0-backups/m0-working-edgar.dump`.
2. Terminate backends on `edgar_test`.
3. `DROP DATABASE IF EXISTS edgar_test;` / `CREATE DATABASE edgar_test OWNER edgar;` on admin DB `postgres`.
4. `pg_restore -d <libpq edgar_test url> --no-owner --no-acl` from the dump.
5. Read-only verification queries only.

## Restore result

| Field | Value |
|---|---|
| `pg_restore` exit code | 0 |
| Dump bytes | 10,369,660 |
| Dump SHA-256 | `b06381a4cf7b7a76a8cfb7ce1e8e3fe1cc0a11afaaa89c1cbefc52f44c24f017` |
| Restored `current_database()` | `edgar_test` |
| Alembic revision after restore | `0001_source_v2` |
| Schemas | `source` (no `registry`) |
| `source.filing` count | 6 |
| `source.xbrl_report` count | 6 |
| `source.fact` count | 15,019 |

## Verification (read-only)

- Counts match the working-DB inventory snapshot for the dumped source corpus.
- No Git registry sync, no mapping propose/accept/reject, and no writes beyond the restore itself.
- Git-authored `registry/metrics.yml` was not applied into this restored DB (schema absent at dump time).

## Follow-on (benchmark env)

After this proof, `edgar_test` was reset again, migrated to Alembic head (`0002_registry`), and used for six-filing corpus acceptance with `EDGAR_DATABASE_URL=$EDGAR_TEST_DATABASE_URL`.

### Corpus acceptance

| Field | Value |
|---|---|
| Command | `make corpus-acceptance` (with test DB URL) |
| Result | exit 0 |
| `phase1d_readiness.all_filings_extracted_and_idempotent` | true |
| `phase1d_readiness.class_a_met` | true |
| Log (local) | `var/m0-backups/corpus-acceptance.log` |
