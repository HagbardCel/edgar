"""Cumulative P2 retrieval ledger."""

from __future__ import annotations

import json
from pathlib import Path

from edgar.spike.retrieve_ledger import (
    TERMINAL_FAIL,
    TERMINAL_SUCCESS,
    LedgerRow,
    load_ledger,
    merge_ledger,
    summarize_ledger,
    write_ledger_report,
)


def test_cumulative_retrieved_across_batch_writes(tmp_path: Path) -> None:
    path = tmp_path / "p2-retrieve.json"
    ledger = {
        "0000000001-24-000001": LedgerRow("0000000001-24-000001", TERMINAL_SUCCESS),
    }
    write_ledger_report(path, ledger, batch_attempted_new=1, batch_retrieved=1, batch_failed=0)
    ledger = merge_ledger(
        load_ledger(path),
        {
            "0000000002-24-000001": LedgerRow("0000000002-24-000001", TERMINAL_SUCCESS),
        },
    )
    write_ledger_report(path, ledger, batch_attempted_new=1, batch_retrieved=1, batch_failed=0)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["retrieved"] == 1
    assert payload["cumulative_retrieved"] == 2


def test_summarize_ledger_counts_failures(tmp_path: Path) -> None:
    ledger = {
        "a": LedgerRow("a", TERMINAL_SUCCESS),
        "b": LedgerRow("b", TERMINAL_FAIL),
    }
    summary = summarize_ledger(ledger)
    assert summary["cumulative_retrieved"] == 1
    assert summary["cumulative_failed"] == 1
