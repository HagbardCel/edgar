"""edgar.sec package."""

from edgar.sec.client import ControlledFetcher, FetchResult, SecClient
from edgar.sec.ssrf import DestinationForbidden, resolve_destination, validate_url_syntax

__all__ = [
    "ControlledFetcher",
    "DestinationForbidden",
    "FetchResult",
    "SecClient",
    "resolve_destination",
    "validate_url_syntax",
]
