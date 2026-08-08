"""URI identity normalization (uri-identity-v1) per ADR 0009."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

URI_IDENTITY_VERSION = "uri-identity-v1"
ALLOWED_SCHEMES = ("http", "https")
_DEFAULT_PORTS = {"http": 80, "https": 443}
_UNRESERVED = re.compile(r"^[A-Za-z0-9\-._~]$")
_PERCENT = re.compile(r"%[0-9A-Fa-f]{2}")


class UriIdentityError(ValueError):
    """Raised when a URI cannot be normalized under uri-identity-v1."""


def _uppercase_percent_escapes(value: str) -> str:
    return _PERCENT.sub(lambda m: m.group(0).upper(), value)


def _decode_unreserved_percents(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "%" and i + 2 < len(value):
            esc = value[i : i + 3]
            try:
                raw = bytes.fromhex(esc[1:])
                ch = raw.decode("ascii")
            except (ValueError, UnicodeDecodeError):
                out.append(esc.upper())
                i += 3
                continue
            if _UNRESERVED.fullmatch(ch):
                out.append(ch)
            else:
                out.append(esc.upper())
            i += 3
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 §5.2.4 remove_dot_segments."""
    input_buffer = path
    output: list[str] = []
    while input_buffer:
        if input_buffer.startswith("../"):
            input_buffer = input_buffer[3:]
        elif input_buffer.startswith("./"):
            input_buffer = input_buffer[2:]
        elif input_buffer.startswith("/./"):
            input_buffer = "/" + input_buffer[3:]
        elif input_buffer == "/.":
            input_buffer = "/"
        elif input_buffer.startswith("/../"):
            input_buffer = "/" + input_buffer[4:]
            if output:
                output.pop()
        elif input_buffer == "/..":
            input_buffer = "/"
            if output:
                output.pop()
        elif input_buffer in {".", ".."}:
            input_buffer = ""
        else:
            if input_buffer.startswith("/"):
                slash, rest = "/", input_buffer[1:]
            else:
                slash, rest = "", input_buffer
            if "/" in rest:
                seg, input_buffer = rest.split("/", 1)
                input_buffer = "/" + input_buffer
            else:
                seg, input_buffer = rest, ""
            output.append(slash + seg)
    return "".join(output)


def _normalize_component(value: str) -> str:
    return _decode_unreserved_percents(_uppercase_percent_escapes(value))


def normalize_uri(uri: str, *, allowed_schemes: tuple[str, ...] = ALLOWED_SCHEMES) -> str:
    """Normalize an absolute URI under uri-identity-v1."""
    if not isinstance(uri, str):
        raise UriIdentityError(f"URI must be a string, got {type(uri).__name__}")
    if uri != uri.strip() or any(ch.isspace() for ch in uri):
        raise UriIdentityError(f"URI contains whitespace: {uri!r}")
    split = urlsplit(uri, allow_fragments=True)
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
    if not host.isascii():
        raise UriIdentityError(f"non-ASCII hostname unsupported in {URI_IDENTITY_VERSION}: {uri!r}")
    # Phase 1: reject IPv6-literal hosts (bracket serialization not supported).
    if ":" in host:
        raise UriIdentityError(f"IPv6-literal hosts unsupported in {URI_IDENTITY_VERSION}: {uri!r}")
    host = host.lower()
    netloc = host
    port = split.port
    if port is not None and port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"
    # Preserve whether the original had an empty query ("?") vs no query.
    has_query = "?" in uri.split("#", 1)[0]
    path = split.path
    path = _normalize_component(path)
    if path == "":
        path = "/"
    path = _remove_dot_segments(path)
    query = _normalize_component(split.query) if (split.query or has_query) else ""
    # urlsplit drops distinguishing empty query; rebuild carefully.
    result = urlunsplit((scheme, netloc, path, query if (split.query or has_query) else "", ""))
    if has_query and split.query == "" and "?" not in result.split("#", 1)[0]:
        # urlunsplit omits empty query; force preservation.
        head, _, frag = result.partition("#")
        result = head + "?" + (("#" + frag) if frag else "")
    return result


def resolve_document_uri(base_uri: str, reference: str) -> str:
    """Resolve a reference against a canonical base, then normalize."""
    base = normalize_uri(base_uri)
    joined = urljoin(base, reference)
    return normalize_uri(joined)


def assert_serialized_binding_uri(uri: str) -> str:
    normalized = normalize_uri(uri)
    if normalized != uri:
        raise UriIdentityError(
            f"serialized binding URI is not canonical under {URI_IDENTITY_VERSION}: {uri!r}"
        )
    return uri


def sha256_of_uri(uri: str) -> str:
    import hashlib

    return hashlib.sha256(uri.encode("utf-8")).hexdigest()
