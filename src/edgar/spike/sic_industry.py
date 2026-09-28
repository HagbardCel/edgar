"""Map SEC SIC codes to coarse P2 industry buckets (not economic equivalence)."""

from __future__ import annotations

# P2 plan buckets: retail, technology, manufacturing, healthcare, banking, energy.
# Beverages roll into manufacturing for stratification unless SIC is explicitly beverage.


def industry_bucket_from_sic(sic: str | None) -> str:
    """Derive the P2 stratification bucket from a filed SIC code."""
    if not sic:
        return "unknown"
    digits = "".join(ch for ch in sic if ch.isdigit())
    if not digits:
        return "unknown"
    code = int(digits[:4].ljust(4, "0")[:4])
    if 6000 <= code <= 6799:
        return "banking"
    if 2800 <= code <= 2899 or 8000 <= code <= 8099:
        return "healthcare"
    if 1300 <= code <= 1399 or 2900 <= code <= 2999:
        return "energy"
    if 3570 <= code <= 3579 or 3670 <= code <= 3679 or 7370 <= code <= 7379:
        return "technology"
    if 5200 <= code <= 5999 or 5300 <= code <= 5399 or 5400 <= code <= 5499:
        return "retail"
    if 2080 <= code <= 2089:
        return "beverages"
    if 2000 <= code <= 3999:
        return "manufacturing"
    return "other"
