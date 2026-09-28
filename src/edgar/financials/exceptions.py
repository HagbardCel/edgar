"""Financial build errors."""

from __future__ import annotations


class RequiredPeriodError(ValueError):
    """Required DEI reporting period could not be determined for a 10-K filing."""
