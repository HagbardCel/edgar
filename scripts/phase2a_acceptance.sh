#!/usr/bin/env bash
# Phase 2A real-corpus acceptance gate (local; not ordinary CI).
# Catalog and project corpus filings, then sync the Git registry and audit mappings.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== Phase 2A real-corpus acceptance =="

uv run edgar db check

# Example corpus workflow — extend for every accession cited in mapping-rules.json.
CORPUS=(
  "0001065088:0001065088-24-000036"
  "0000019617:0000019617-24-000453"
  "0000104169:0000104169-24-000056"
)

for entry in "${CORPUS[@]}"; do
  cik="${entry%%:*}"
  accession="${entry##*:}"
  bundle_dir=$(find "${EDGAR_DATA_ROOT:-var}/bundles/${cik}/${accession}" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1 || true)
  if [[ -z "${bundle_dir}" ]]; then
    echo "SKIP: no bundle at var/bundles/${cik}/${accession}/<opaque_id> — retrieve and catalog first"
    continue
  fi
  echo "Catalog + project ${accession} (${bundle_dir})"
  uv run edgar filings catalog --bundle-dir "$bundle_dir" --json
  uv run edgar xbrl project --bundle-dir "$bundle_dir" --json
done

echo "Sync Git metric registry"
uv run edgar metrics sync --json

echo "Explain each mapping rule"
uv run edgar mappings list --json | uv run python -c "
import json, subprocess, sys
rows = json.load(sys.stdin)
for row in rows:
    key = row['rule']['rule_key'] if isinstance(row.get('rule'), dict) else row.get('rule_key')
    if not key:
        continue
    subprocess.run(['uv', 'run', 'edgar', 'mappings', 'explain', key, '--json'], check=True)
"

echo "Export audit report"
uv run edgar mappings export --format json > /tmp/edgar-phase2a-mappings-audit.json

echo "OK: Phase 2A real-corpus acceptance completed"
