"""Issuer seed identity checks against submissions JSON."""

from __future__ import annotations

import pytest

from edgar.spike.seed_validation import SeedValidationError, validate_seed_identity


def test_validate_seed_identity_substring_match() -> None:
    validate_seed_identity(
        {"name": "AMAZON COM INC"},
        cik="0001018724",
        expected_name="Amazon",
    )


def test_validate_seed_identity_mismatch_raises() -> None:
    with pytest.raises(SeedValidationError, match="expected entity name"):
        validate_seed_identity(
            {"name": "EXXON MOBIL CORP"},
            cik="0001018724",
            expected_name="Amazon",
        )
