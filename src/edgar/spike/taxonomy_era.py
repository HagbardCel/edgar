"""Classify US-GAAP release tokens (path segments) into P2 era buckets."""

from __future__ import annotations

import re

_RELEASE_YEAR = re.compile(r"(20\d{2}|19\d{2})")


def release_token_calendar_year(token: str) -> int | None:
    """Parse a calendar year from a release token such as ``2024`` or ``2009-01-31``."""
    text = token.strip()
    if not text or text == "mixed":
        return None
    match = _RELEASE_YEAR.search(text)
    if match is None:
        return None
    return int(match.group(1))


def era_flags_from_release_tokens(tokens: set[str]) -> dict[str, bool]:
    """Map distinct ``filing_taxonomy_release`` tokens to P2 stratification eras."""
    years = {year for token in tokens if (year := release_token_calendar_year(token)) is not None}
    return {
        "xbrl_us_2009_era": any(year <= 2009 for year in years)
        or any("2009" in token for token in tokens),
        "transition_2011_era": any(year == 2011 for year in years)
        or any("2011" in token for token in tokens),
        "modern_release_2018_plus": any(year >= 2018 for year in years),
    }
