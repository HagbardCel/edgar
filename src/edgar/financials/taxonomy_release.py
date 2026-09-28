"""US-GAAP release token helpers for namespace URIs.

P2 quality reporting derives the filing release from captured taxonomy XSD
``targetNamespace`` values, not from bounded ``source.concept_declaration``
rows or selected observations.
"""

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

    Callers pass US-GAAP namespace URIs from the evidence they are summarizing.
    No namespaces yields ``unknown``; more than one release token yields
    ``mixed``.
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
