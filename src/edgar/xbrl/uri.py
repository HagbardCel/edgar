"""Re-export uri-identity-v1 from the domain module (FilingBundle contract)."""

from __future__ import annotations

from edgar.domain.uri import (
    ALLOWED_SCHEMES,
    URI_IDENTITY_VERSION,
    UriIdentityError,
    assert_serialized_binding_uri,
    normalize_uri,
    resolve_document_uri,
    sha256_of_uri,
)

__all__ = [
    "ALLOWED_SCHEMES",
    "URI_IDENTITY_VERSION",
    "UriIdentityError",
    "assert_serialized_binding_uri",
    "normalize_uri",
    "resolve_document_uri",
    "sha256_of_uri",
]
