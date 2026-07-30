# Spike 0001: Arelle offline closure

**Status:** Implementation complete; live SEC run pending `SEC_USER_AGENT`.

## Objective

Validate deterministic accession mirroring, DTS closure capture, and offline Arelle reload before locking the Phase 1 schema.

## Selected accession

| Field | Value |
| --- | --- |
| Company | eBay Inc. |
| CIK | `0001065088` |
| Accession | `0001065088-24-000036` |
| Form | 10-K |
| Filed | 2024-02-28 |
| Period end | 2023-12-31 |

Reason: modern Inline XBRL annual report that also anchors the micro-corpus amendment pair (`0001065088-24-000094`).

## How to run

```bash
cp .env.example .env
# Set SEC_USER_AGENT="Name email@example.com"

uv sync --extra dev
uv run python scripts/spikes/arelle_offline_closure.py \
  --cik 0001065088 \
  --accession 0001065088-24-000036 \
  --clean
```

Optional idempotency check:

```bash
uv run python scripts/spikes/arelle_offline_closure.py \
  --cik 0001065088 \
  --accession 0001065088-24-000036 \
  --repeat
```

Outputs (gitignored):

```text
var/spikes/0001065088-24-000036/
  objects/sha256/...
  working/
  cache/online/
  cache/offline/
  offline-catalog.xml
  manifest.json
  inspection.json
  quality_issues.json
```

## Environment recorded at implementation time

| Item | Value |
| --- | --- |
| Python | 3.12 (uv) |
| arelle-release | 2.43.1 |
| Spike script | `scripts/spikes/arelle_offline_closure.py` |
| Acquisition policy | `acq-v0-spike` |
| Catalog generator | `catalog-v0-spike` |

## Live run results

*Not yet executed — blocked on identifying `SEC_USER_AGENT`.*

After a successful run, fill in:

- Online vs offline document / concept / context / unit / fact / relationship counts
- Closure hash
- Payload hash
- Inspection hash
- URI-resolution behavior notes
- Fact locator fields available from Arelle (`id`, `sourceline`, `elementXpath`, …)
- Discrepancies and decisions changed by the experiment
- Whether ADR 0004 can move from Proposed → Accepted

## Success criteria checklist

1. Accession directory fully enumerated
2. Required accession files downloaded and verified
3. Complete-submission inventory reconciles with index
4. Online Arelle load without unresolved required documents
5. Every loaded external URI maps to a captured content object
6. Offline load with network disabled
7. Online/offline counts and document sets match
8. Closure hash matches
9. Repeat yields identical payload and inspection hashes
10. Differences explicitly explained

## Design notes confirmed in code

- `metadata/discovery.json` is payload-included; raw submissions JSON is not
- Complete submission kept only under `accession/{dashless}.txt`
- Offline catalog stored and hashed but excluded from `payload_hash`
- Inspection JSON uses sorted keys, decimal strings, canonical URIs
- Closure hash uses exact NUL/LF byte serialization
