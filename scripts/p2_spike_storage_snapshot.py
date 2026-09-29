"""Snapshot object-store and PostgreSQL bytes for P2.3 / P2.7 storage ADR inputs.

Run once before P2.3 retrieval (after accession-list build if needed) and again
after extract. Pass both JSON files to ``p2_spike_summarize_extract.py``.

Usage:
  uv run python scripts/p2_spike_storage_snapshot.py --label pre-retrieval \\
    --output var/reports/p2-storage-pre.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import text

from edgar.config import Settings
from edgar.db.engine import create_db_engine
from edgar.storage.objects import write_json_atomic


def object_store_bytes(data_root: Path) -> int:
    objects_dir = data_root / "objects"
    if not objects_dir.is_dir():
        return 0
    total = 0
    for path in objects_dir.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def postgres_source_registry_bytes(database_url: str) -> int:
    engine = create_db_engine(database_url)
    query = text(
        """
        SELECT COALESCE(
            SUM(pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename))),
            0
        )::bigint
        FROM pg_tables
        WHERE schemaname IN ('source', 'registry')
        """,
    )
    with engine.connect() as conn:
        row = conn.execute(query).one()
    return int(row[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="P2 storage byte snapshot")
    parser.add_argument("--label", required=True, help="e.g. pre-retrieval or post-extract")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("var/reports/p2-storage-snapshot.json"),
    )
    args = parser.parse_args()
    settings = Settings()
    payload = {
        "label": args.label,
        "object_store_bytes": object_store_bytes(Path(settings.edgar_data_root)),
        "postgres_source_registry_bytes": postgres_source_registry_bytes(
            settings.require_database_url(),
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(args.output, payload)
    import json

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
