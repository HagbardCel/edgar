# M0 inventory (working state)

Captured: 2026-09-07T07:22:35Z (UTC)

Role: working database (`EDGAR_DATABASE_URL` → database `edgar`) — **read-only** during inventory and backup.
Bundle filesystem root: `EDGAR_DATA_ROOT` → `${EDGAR_DATA_ROOT}` (local `var/` by default).

## Database (working)

| Field | Value |
|---|---|
| Database name | `edgar` |
| PostgreSQL | 16.14 (Debian container via OrbStack port forward) |
| Alembic revision | `0001_source_v2` |
| Schemas present | `public`, `source` |
| `registry` schema | **absent** |

### Counts

| Relation | Count |
|---|---|
| `source.issuer` | 4 |
| `source.filing` | 6 |
| `source.xbrl_report` | 6 |
| `source.fact` | 15,019 |
| `source.document` | 1,114 |
| `source.concept` | 56,217 |
| `source.context` | 4,006 |
| `source.unit` | 49 |
| `registry.canonical_metric` | n/a (schema absent) |
| `registry.mapping_assertion` | n/a (schema absent) |

### Filings catalogued

| Accession | Form | CIK | Filing date |
|---|---|---|---|
| 0000019617-24-000453 | 10-Q | 0000019617 | 2024-08-02 |
| 0000021344-24-000044 | 10-Q | 0000021344 | 2024-07-29 |
| 0000104169-24-000056 | 10-K | 0000104169 | 2024-03-15 |
| 0001065088-23-000006 | 10-K | 0001065088 | 2023-02-23 |
| 0001065088-24-000036 | 10-K | 0001065088 | 2024-02-28 |
| 0001065088-24-000094 | 10-K/A | 0001065088 | 2024-05-29 |

### Integrity notes

- Working DB matches the six-accession corpus set in `fixtures/corpus.toml`.
- Branch Alembic head is `0002_registry`, but this working DB has **not** been upgraded past `0001_source_v2`. No registry mirror or mapping ledger rows exist here.
- No `registry sync` was run against the working DB during M0.

## Bundles (filesystem)

All six corpus accessions were **present before M0** under `var/bundles/` (validated via `BundleRepository.list_published` / offline load). No benchmark bundles were acquired during M0.

| Accession | Opaque bundle id | Payload hash (prefix) | Artifacts | Acquisition class |
|---|---|---|---|---|
| 0001065088-23-000006 | `5afc286194184728930b372fdc602777` | `5ab98bd4…` | 218 | present_before_M0 |
| 0001065088-24-000036 | `87aa60a1382a41709ec8cbdfd5c83490` | `96ae41f1…` | 225 | present_before_M0 |
| 0001065088-24-000094 | `4928759a51134b689a184581c8fb0687` | `4e4e022e…` | 75 | present_before_M0 |
| 0000104169-24-000056 | `d77e7138fd9d434287fcc57a1f626217` | `67380495…` | 174 | present_before_M0 |
| 0000019617-24-000453 | `c6d6249a11d3480a840c5f5530a63733` | `54aadbdb…` | 262 | present_before_M0 |
| 0000021344-24-000044 | `9a4dda04384d41e49cc48d5c41255e33` | `66eaf4b0…` | 160 | present_before_M0 |

Offline replay spot-check: eBay `0001065088-24-000036` published bundle loads successfully (`load_completed=True`).

Raw machine-readable bundle listing was retained as local scratch under `${EDGAR_DATA_ROOT}` and is not committed.

## Backups (outside Git)

| Artifact | Location | SHA-256 |
|---|---|---|
| Working DB custom-format dump | `var/m0-backups/m0-working-edgar.dump` | `b06381a4cf7b7a76a8cfb7ce1e8e3fe1cc0a11afaaa89c1cbefc52f44c24f017` |
| Filing bundles + CAS tarball | `var/m0-backups/m0-filing-bundles.tar.gz` | `01ce3d9c047d08df0a6f141d5db5401248997d087f6d1ec4ac2296c5e1202193` |

`pg_dump` used SQLAlchemy URL → libpq URL conversion (`drivername="postgresql"`) against database `edgar` only.
