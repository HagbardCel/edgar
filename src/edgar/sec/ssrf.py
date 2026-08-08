"""SSRF / destination safety for controlled HTTP fetches."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

ALLOWED_SCHEMES = frozenset({"http", "https"})


class DestinationForbidden(ValueError):
    """Raised when a URL fails the SSRF / destination policy."""


@dataclass(frozen=True)
class ResolvedDestination:
    hostname: str
    port: int
    scheme: str
    pinned_ip: str
    candidate_ips: tuple[str, ...]


def _is_forbidden_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def is_forbidden_ip(ip: str) -> bool:
    """Return True only for IP literals in forbidden ranges.

    Non-IP hostnames return False; callers that need DNS resolution must
    resolve first and then filter the resulting addresses.
    """
    try:
        return _is_forbidden_ip(ip)
    except ValueError:
        return False


def validate_url_syntax(url: str) -> tuple[str, str, int, str]:
    """Return (scheme, hostname, port, path_query) or raise DestinationForbidden."""
    if not isinstance(url, str) or not url.strip():
        raise DestinationForbidden("empty URL")
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise DestinationForbidden(f"disallowed scheme: {scheme!r}")
    if parsed.username is not None or parsed.password is not None:
        raise DestinationForbidden("URL credentials are forbidden")
    hostname = parsed.hostname
    if not hostname:
        raise DestinationForbidden("URL missing hostname")
    if not hostname.isascii():
        raise DestinationForbidden("non-ASCII hostname unsupported")
    # Reject literal forbidden IPs in the URL host (not DNS names).
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if is_forbidden_ip(hostname):
            raise DestinationForbidden(f"forbidden destination address: {hostname}")
    default_port = 443 if scheme == "https" else 80
    port = parsed.port or default_port
    # Rebuild path+query+fragment for request target (fragment unused for fetch).
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    elif url.rstrip("#").endswith("?") or ("?" in url.split("#", 1)[0] and not parsed.query):
        path = f"{path}?"
    return scheme, hostname.lower(), port, path


def resolve_public_ips(hostname: str, port: int) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DestinationForbidden(f"DNS resolution failed for {hostname}: {exc}") from exc
    ips: list[str] = []
    seen: set[str] = set()
    for info in infos:
        raw_ip = info[4][0]
        ip = str(raw_ip)
        if ip in seen:
            continue
        seen.add(ip)
        if is_forbidden_ip(ip):
            continue
        ips.append(ip)
    if not ips:
        raise DestinationForbidden(f"no public addresses for host {hostname}")
    return tuple(ips)


def resolve_destination(url: str) -> ResolvedDestination:
    scheme, hostname, port, _path = validate_url_syntax(url)
    # If hostname is already an IP literal, it was validated above.
    try:
        ipaddress.ip_address(hostname)
        candidates = (hostname,)
        if is_forbidden_ip(hostname):
            raise DestinationForbidden(f"forbidden destination address: {hostname}")
    except ValueError:
        candidates = resolve_public_ips(hostname, port)
    return ResolvedDestination(
        hostname=hostname,
        port=port,
        scheme=scheme,
        pinned_ip=candidates[0],
        candidate_ips=candidates,
    )


def join_redirect(current_url: str, location: str) -> str:
    return urljoin(current_url, location)
