"""Filing-level US-GAAP release, computed from declarations before selection."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

from edgar.xbrl.taxonomy_family import classify


def namespace_release_token(namespace_uri: str) -> str | None:
    """Last path segment of a namespace URI (``2024``, ``2009-01-31``)."""
    path = urlparse(namespace_uri).path.strip("/")
    if not path:
        return None
    token = path.split("/")[-1]
    return token or None


def us_gaap_release_token(namespace_uri: str) -> str | None:
    if classify(namespace_uri).semantic_family != "us-gaap":
        return None
    return namespace_release_token(namespace_uri)


def filing_taxonomy_release(namespace_uris: Iterable[str]) -> str:
    """One US-GAAP release token, ``unknown``, or ``mixed``.

    The selected observation is not an input. A filing with no US-GAAP
    declaration is ``unknown``. Two release tokens are ``mixed``.
    """
    tokens = {
        token
        for namespace in namespace_uris
        if (token := us_gaap_release_token(namespace)) is not None
    }
    if not tokens:
        return "unknown"
    if len(tokens) > 1:
        return "mixed"
    return next(iter(tokens))
