"""Report-set validation (M1A-3)."""

from __future__ import annotations

import pytest

from edgar.xbrl.report_set import ReportSetError, assert_unique_report_keys, validate_outcome_keys


def test_duplicate_expected_keys_fatal() -> None:
    with pytest.raises(ReportSetError, match="duplicate expected"):
        assert_unique_report_keys(("a", "a"))


def test_duplicate_outcomes_before_dict_index() -> None:
    outcomes = [("k1", 1), ("k1", 2)]
    with pytest.raises(ReportSetError, match="duplicate worker"):
        validate_outcome_keys(
            frozenset({"k1"}),
            outcomes,
            key_of=lambda o: o[0],
            label="worker",
        )


def test_missing_outcome_key() -> None:
    with pytest.raises(ReportSetError, match="missing"):
        validate_outcome_keys(
            frozenset({"a", "b"}),
            [("a", 1)],
            key_of=lambda o: o[0],
            label="inventory",
        )
