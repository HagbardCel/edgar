"""Taxonomy release token era classification."""

from __future__ import annotations

from edgar.spike.taxonomy_era import era_flags_from_release_tokens, release_token_calendar_year


def test_release_token_calendar_year() -> None:
    assert release_token_calendar_year("2024") == 2024
    assert release_token_calendar_year("2009-01-31") == 2009
    assert release_token_calendar_year("mixed") is None


def test_era_flags_from_typical_spike_tokens() -> None:
    tokens = {"2009-01-31", "2011-01-31", "2019", "2024"}
    flags = era_flags_from_release_tokens(tokens)
    assert flags["xbrl_us_2009_era"] is True
    assert flags["transition_2011_era"] is True
    assert flags["modern_release_2018_plus"] is True
