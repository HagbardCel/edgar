"""Namespace family and origin classification for standard vs issuer taxonomies.

``origin`` uses a host-prefix heuristic until taxonomy-package provenance replaces
it in a later phase. ``issuer`` does not prove filer ownership; it means the
namespace was not classified as a known standard host.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

SemanticFamily = Literal["us-gaap", "dei", "srt", "other"]
TaxonomyOrigin = Literal["standard", "issuer"]

_US_GAAP_PREFIXES = (
    "http://xbrl.us/us-gaap/",
    "http://fasb.org/us-gaap/",
    "https://xbrl.us/us-gaap/",
    "https://fasb.org/us-gaap/",
)
_DEI_PREFIXES = (
    "http://xbrl.us/dei/",
    "http://xbrl.sec.gov/dei/",
    "https://xbrl.us/dei/",
    "https://xbrl.sec.gov/dei/",
)
_SRT_PREFIXES = (
    "http://fasb.org/srt/",
    "https://fasb.org/srt/",
)
_STANDARD_HOSTS = frozenset({"xbrl.sec.gov", "fasb.org", "xbrl.us"})


@dataclass(frozen=True)
class TaxonomyClassification:
    semantic_family: SemanticFamily
    origin: TaxonomyOrigin


def _semantic_family(namespace_uri: str) -> SemanticFamily:
    for prefix in _US_GAAP_PREFIXES:
        if namespace_uri.startswith(prefix):
            return "us-gaap"
    for prefix in _DEI_PREFIXES:
        if namespace_uri.startswith(prefix):
            return "dei"
    for prefix in _SRT_PREFIXES:
        if namespace_uri.startswith(prefix):
            return "srt"
    return "other"


def _standard_host(namespace_uri: str) -> bool:
    parsed = urlparse(namespace_uri)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    return host in _STANDARD_HOSTS if host is not None else False


def classify(namespace_uri: str | None) -> TaxonomyClassification:
    """Classify a concept namespace URI into family and standard/issuer origin."""
    if not namespace_uri:
        return TaxonomyClassification(semantic_family="other", origin="issuer")
    family = _semantic_family(namespace_uri)
    if family in ("us-gaap", "dei", "srt"):
        return TaxonomyClassification(semantic_family=family, origin="standard")
    if _standard_host(namespace_uri):
        return TaxonomyClassification(semantic_family="other", origin="standard")
    return TaxonomyClassification(semantic_family="other", origin="issuer")
