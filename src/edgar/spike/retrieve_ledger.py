"""Cumulative P2 retrieval report across bounded batch runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar.storage.objects import write_json_atomic

TERMINAL_SUCCESS = "retrieved"
TERMINAL_SKIP_PUBLISHED = "skipped_existing"
TERMINAL_FAIL = "failed"
TERMINAL_NOT_ATTEMPTED = "not_attempted_limit"
TERMINAL_KNOWN_FAIL = "skipped_known_failure"


@dataclass(frozen=True)
class LedgerRow:
    accession: str
    status: str
    failure_class: str | None = None
    failure_message: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "accession": self.accession,
            "status": self.status,
            "failure_class": self.failure_class,
            "failure_message": self.failure_message,
        }


def load_ledger(path: Path) -> dict[str, LedgerRow]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("accessions") or []
    if not isinstance(rows, list):
        raise ValueError(f"retrieve report accessions must be a list: {path}")
    ledger: dict[str, LedgerRow] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        accession = str(raw.get("accession") or "").strip()
        if not accession:
            continue
        ledger[accession] = LedgerRow(
            accession=accession,
            status=str(raw.get("status") or ""),
            failure_class=_optional_str(raw.get("failure_class")),
            failure_message=_optional_str(raw.get("failure_message")),
        )
    return ledger


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def merge_ledger(
    existing: dict[str, LedgerRow], updates: dict[str, LedgerRow]
) -> dict[str, LedgerRow]:
    merged = dict(existing)
    for accession, row in updates.items():
        merged[accession] = row
    return merged


def summarize_ledger(ledger: dict[str, LedgerRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in ledger.values():
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "cumulative_retrieved": counts.get(TERMINAL_SUCCESS, 0),
        "cumulative_failed": counts.get(TERMINAL_FAIL, 0),
        "cumulative_skipped_existing": counts.get(TERMINAL_SKIP_PUBLISHED, 0),
        "cumulative_not_attempted": counts.get(TERMINAL_NOT_ATTEMPTED, 0),
        "cumulative_skipped_known_failure": counts.get(TERMINAL_KNOWN_FAIL, 0),
        "ledger_rows": len(ledger),
    }


def write_ledger_report(
    path: Path,
    ledger: dict[str, LedgerRow],
    *,
    batch_attempted_new: int,
    batch_retrieved: int,
    batch_failed: int,
) -> None:
    summary = summarize_ledger(ledger)
    ordered = sorted(ledger.values(), key=lambda row: row.accession)
    payload: dict[str, Any] = {
        "attempted_new": batch_attempted_new,
        "retrieved": batch_retrieved,
        "failed": batch_failed,
        **summary,
        "accessions": [row.to_dict() for row in ordered],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)
