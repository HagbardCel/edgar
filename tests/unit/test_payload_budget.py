"""Unit tests for LogicalPayloadBudget and acquisition safeguard mapping."""

from __future__ import annotations

import pytest

from edgar.ingestion.acquisition import LogicalPayloadBudget
from edgar.sec.limits import LogicalPathConflict, MaxBundleBytesExceeded


def test_budget_charges_logical_members() -> None:
    budget = LogicalPayloadBudget(100)
    budget.register("accession/a", "aa" * 32, 40)
    budget.register("accession/b", "bb" * 32, 40)
    assert budget.committed == 80
    assert budget.remaining == 20


def test_budget_idempotent_same_member() -> None:
    budget = LogicalPayloadBudget(100)
    budget.register("accession/a", "aa" * 32, 40)
    budget.register("accession/a", "aa" * 32, 40)
    assert budget.committed == 40


def test_budget_conflict_on_path_reuse() -> None:
    budget = LogicalPayloadBudget(100)
    budget.register("accession/a", "aa" * 32, 40)
    with pytest.raises(LogicalPathConflict):
        budget.register("accession/a", "bb" * 32, 40)


def test_budget_exceeded() -> None:
    budget = LogicalPayloadBudget(50)
    budget.register("accession/a", "aa" * 32, 40)
    with pytest.raises(MaxBundleBytesExceeded):
        budget.register("accession/b", "bb" * 32, 20)
