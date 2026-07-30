"""URI identity normalization (uri-identity-v1).

Conservative rules: absolute URI required; fragment removed; query retained;
scheme and ASCII host lowercased; standard default ports removed; path and
query octets otherwise preserved. No percent-decoding/re-encoding, no
trailing-slash alteration. Over-normalization is dangerous: different
retrieval identities can legitimately serve different bytes.
"""

from __future__ import annotations

from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

from spike_lib import URI_IDENTITY_VERSION

ALLOWED_SCHEMES = ("http", "https")
_DEFAULT_PORTS = {"http": 80, "https": 443}


class UriIdentityError(ValueError):
    """Raised when a URI cannot be normalized under uri-identity-v1."""


def strip_fragment(uri: str) -> str:
    base, _frag = urldefrag(uri)
    return base


def is_http_uri(uri: str) -> bool:
    return urlsplit(uri).scheme.lower() in ALLOWED_SCHEMES


def normalize_uri(uri: str, *, allowed_schemes: tuple[str, ...] = ALLOWED_SCHEMES) -> str:
    """Normalize an absolute URI under uri-identity-v1.

    Rejects relative references, credentials, whitespace and disallowed schemes.
    """
    if not isinstance(uri, str):
        raise UriIdentityError(f"URI must be a string, got {type(uri).__name__}")
    if uri != uri.strip() or any(ch.isspace() for ch in uri):
        raise UriIdentityError(f"URI contains whitespace: {uri!r}")
    split = urlsplit(uri)
    scheme = split.scheme.lower()
    if not scheme:
        raise UriIdentityError(f"relative URI rejected (resolve against base first): {uri!r}")
    if scheme not in allowed_schemes:
        raise UriIdentityError(f"disallowed URI scheme {scheme!r} in {uri!r}")
    if split.username is not None or split.password is not None:
        raise UriIdentityError(f"credentials rejected in URI: {uri!r}")
    host = split.hostname
    if not host:
        raise UriIdentityError(f"URI without host rejected: {uri!r}")
    host = host.lower()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UriIdentityError(f"host cannot be IDNA-encoded: {uri!r}") from exc
    netloc = host
    port = split.port
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"
    # Path and query octets preserved exactly; fragment removed.
    return urlunsplit((scheme, netloc, split.path, split.query, ""))


def resolve_document_uri(base_uri: str, reference: str) -> str:
    """Resolve a (possibly relative, possibly fragment-bearing) reference
    against a source document base URI, then normalize under uri-identity-v1.

    URI identity normalization itself never invents a base URI.
    """
    joined = urljoin(base_uri, reference)
    return normalize_uri(strip_fragment(joined))


def assert_serialized_binding_uri(uri: str) -> str:
    """Validate a URI that appears inside a serialized binding record.

    Writers must normalize before serialization: a literal fragment in a
    serialized document_uri or replay_alias is rejected.
    """
    normalized = normalize_uri(uri)
    if normalized != uri:
        raise UriIdentityError(
            f"serialized binding URI is not canonical under {URI_IDENTITY_VERSION}: {uri!r}"
        )
    return uri
