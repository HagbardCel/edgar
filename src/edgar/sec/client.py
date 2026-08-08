"""Controlled SSRF-safe HTTP client (sole network I/O component)."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from edgar.sec.limits import MaxRedirectsExceeded
from edgar.sec.ssrf import (
    DestinationForbidden,
    join_redirect,
    peer_from_response,
    peers_match,
    resolve_destination,
    validate_url_syntax,
)
from edgar.storage.objects import ObjectStore, SizeLimitExceeded, StoredObject

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class FetchHop:
    uri: str
    resolved_candidates: tuple[str, ...]
    pinned_ip: str | None
    peer_ip: str | None
    http_status: int | None
    error: str | None
    observed_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "resolved_candidates": list(self.resolved_candidates),
            "pinned_ip": self.pinned_ip,
            "peer_ip": self.peer_ip,
            "http_status": self.http_status,
            "error": self.error,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass(frozen=True)
class FetchTrace:
    requested_uri: str
    hops: tuple[FetchHop, ...]
    final_uri: str | None = None
    content_sha256: str | None = None
    byte_size: int | None = None
    error: str | None = None

    def to_observation_dict(self) -> dict[str, Any]:
        return {
            "requested_uri": self.requested_uri,
            "final_uri": self.final_uri,
            "content_sha256": self.content_sha256,
            "byte_size": self.byte_size,
            "error": self.error,
            "hops": [h.to_dict() for h in self.hops],
            "redirect_count": max(0, len(self.hops) - 1) if self.hops else 0,
            "pinned_ip": next((h.pinned_ip for h in reversed(self.hops) if h.pinned_ip), None),
            "peer_ip": next((h.peer_ip for h in reversed(self.hops) if h.peer_ip), None),
            "status_code": next(
                (h.http_status for h in reversed(self.hops) if h.http_status is not None), None
            ),
            "observed_at": self.hops[-1].observed_at.isoformat() if self.hops else None,
        }


@dataclass(frozen=True)
class FetchResult:
    requested_uri: str
    final_uri: str
    status_code: int
    headers: dict[str, str]
    redirect_count: int
    sha256: str
    byte_size: int
    pinned_ip: str
    observed_at: datetime
    peer_ip: str | None
    trace: FetchTrace

    def to_observation_dict(self) -> dict[str, Any]:
        return self.trace.to_observation_dict()


ObservationSink = Callable[[FetchTrace], None]


@dataclass
class _TraceBuilder:
    requested_uri: str
    hops: list[FetchHop] = field(default_factory=list)
    final_uri: str | None = None
    content_sha256: str | None = None
    byte_size: int | None = None
    error: str | None = None
    emitted: bool = False

    def finish(self) -> FetchTrace:
        return FetchTrace(
            requested_uri=self.requested_uri,
            hops=tuple(self.hops),
            final_uri=self.final_uri,
            content_sha256=self.content_sha256,
            byte_size=self.byte_size,
            error=self.error,
        )


def _host_header(hostname: str, port: int, scheme: str) -> str:
    default_port = 443 if scheme == "https" else 80
    if port != default_port:
        return f"{hostname}:{port}"
    return hostname


class ControlledFetcher:
    """Parent-process HTTP client with destination pinning and CAS streaming."""

    def __init__(
        self,
        user_agent: str,
        *,
        min_interval_seconds: float = 0.2,
        max_redirects: int = 5,
        timeout_seconds: float = 60.0,
        max_retries: int = 4,
        observation_sink: ObservationSink | None = None,
    ) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "SEC_USER_AGENT must identify the requester, e.g. 'Name email@example.com'"
            )
        self.user_agent = user_agent
        self.min_interval_seconds = min_interval_seconds
        self.max_redirects = max_redirects
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.observation_sink = observation_sink
        self._last_request_at = 0.0
        self._limits = httpx.Limits(max_keepalive_connections=0)
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            limits=self._limits,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ControlledFetcher:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _emit(self, builder: _TraceBuilder) -> FetchTrace:
        trace = builder.finish()
        if not builder.emitted and self.observation_sink is not None:
            self.observation_sink(trace)
            builder.emitted = True
        return trace

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _pinned_request(self, url: str) -> tuple[str, str, int, str, str, tuple[str, ...]]:
        """Return request_url, hostname, port, scheme, pinned_ip, candidates."""
        dest = resolve_destination(url)
        parsed = urlparse(url)
        if ":" in dest.pinned_ip and not dest.pinned_ip.startswith("["):
            ip_netloc = f"[{dest.pinned_ip}]"
        else:
            ip_netloc = dest.pinned_ip
        default_port = 443 if dest.scheme == "https" else 80
        if dest.port != default_port:
            ip_netloc = f"{ip_netloc}:{dest.port}"
        request_url = urlunparse(
            (dest.scheme, ip_netloc, parsed.path or "/", parsed.params, parsed.query, "")
        )
        return (
            request_url,
            dest.hostname,
            dest.port,
            dest.scheme,
            dest.pinned_ip,
            dest.candidate_ips,
        )

    def fetch_to_store(
        self,
        url: str,
        store: ObjectStore,
        *,
        max_bytes: int,
    ) -> tuple[FetchResult, StoredObject]:
        builder = _TraceBuilder(requested_uri=url)
        current = url
        redirect_count = 0
        try:
            while True:
                # Outer loop: redirect hops. Each hop has its own retry budget.
                hop_error: str | None = None
                for attempt in range(self.max_retries + 1):
                    observed_at = datetime.now(UTC)
                    candidates: tuple[str, ...] = ()
                    pinned_ip: str | None = None
                    peer_ip: str | None = None
                    http_status: int | None = None
                    try:
                        validate_url_syntax(current)
                        request_url, hostname, port, scheme, pinned_ip, candidates = (
                            self._pinned_request(current)
                        )
                        self._throttle()
                        self._last_request_at = time.monotonic()
                        with self._client.stream(
                            "GET",
                            request_url,
                            headers={"Host": _host_header(hostname, port, scheme)},
                            extensions={"sni_hostname": hostname},
                        ) as response:
                            http_status = response.status_code
                            peer_ip = peer_from_response(response)
                            if (
                                peer_ip is not None
                                and pinned_ip is not None
                                and not peers_match(pinned_ip, peer_ip)
                            ):
                                raise DestinationForbidden(
                                    f"peer {peer_ip} differs from pinned {pinned_ip}"
                                )
                            if response.status_code in REDIRECT_STATUS:
                                location = response.headers.get("Location")
                                if not location:
                                    raise RuntimeError(f"redirect without Location from {current}")
                                builder.hops.append(
                                    FetchHop(
                                        uri=current,
                                        resolved_candidates=candidates,
                                        pinned_ip=pinned_ip,
                                        peer_ip=peer_ip,
                                        http_status=http_status,
                                        error=None,
                                        observed_at=observed_at,
                                    )
                                )
                                redirect_count += 1
                                if redirect_count > self.max_redirects:
                                    raise MaxRedirectsExceeded(
                                        f"exceeded MAX_REDIRECTS={self.max_redirects} "
                                        f"resolving {url}"
                                    )
                                current = join_redirect(current, location)
                                break  # next redirect hop (new retry budget)
                            if response.status_code in RETRY_STATUS and attempt < self.max_retries:
                                builder.hops.append(
                                    FetchHop(
                                        uri=current,
                                        resolved_candidates=candidates,
                                        pinned_ip=pinned_ip,
                                        peer_ip=peer_ip,
                                        http_status=http_status,
                                        error=f"retryable_status_{response.status_code}",
                                        observed_at=observed_at,
                                    )
                                )
                                time.sleep((2**attempt) + random.uniform(0, 0.25))
                                continue
                            response.raise_for_status()
                            cl = response.headers.get("Content-Length")
                            if cl is not None:
                                try:
                                    if int(cl) > max_bytes:
                                        raise SizeLimitExceeded(
                                            f"Content-Length {cl} exceeds max_bytes={max_bytes}"
                                        )
                                except ValueError:
                                    pass

                            def chunks() -> Iterator[bytes]:
                                yield from response.iter_bytes()

                            obj = store.put_stream(chunks(), max_bytes=max_bytes)
                            builder.hops.append(
                                FetchHop(
                                    uri=current,
                                    resolved_candidates=candidates,
                                    pinned_ip=pinned_ip,
                                    peer_ip=peer_ip,
                                    http_status=http_status,
                                    error=None,
                                    observed_at=observed_at,
                                )
                            )
                            builder.final_uri = current
                            builder.content_sha256 = obj.sha256
                            builder.byte_size = obj.byte_size
                            trace = self._emit(builder)
                            assert pinned_ip is not None
                            result = FetchResult(
                                requested_uri=url,
                                final_uri=current,
                                status_code=response.status_code,
                                headers={k: v for k, v in response.headers.items()},
                                redirect_count=redirect_count,
                                sha256=obj.sha256,
                                byte_size=obj.byte_size,
                                pinned_ip=pinned_ip,
                                observed_at=observed_at,
                                peer_ip=peer_ip,
                                trace=trace,
                            )
                            return result, obj
                    except SizeLimitExceeded as exc:
                        hop_error = f"{type(exc).__name__}: {exc}"
                        builder.hops.append(
                            FetchHop(
                                uri=current,
                                resolved_candidates=candidates,
                                pinned_ip=pinned_ip,
                                peer_ip=peer_ip,
                                http_status=http_status,
                                error=hop_error,
                                observed_at=observed_at,
                            )
                        )
                        builder.error = hop_error
                        self._emit(builder)
                        raise
                    except MaxRedirectsExceeded as exc:
                        hop_error = f"{type(exc).__name__}: {exc}"
                        builder.hops.append(
                            FetchHop(
                                uri=current,
                                resolved_candidates=candidates,
                                pinned_ip=pinned_ip,
                                peer_ip=peer_ip,
                                http_status=http_status,
                                error=hop_error,
                                observed_at=observed_at,
                            )
                        )
                        builder.error = hop_error
                        self._emit(builder)
                        raise
                    except DestinationForbidden as exc:
                        hop_error = f"{type(exc).__name__}: {exc}"
                        builder.hops.append(
                            FetchHop(
                                uri=current,
                                resolved_candidates=candidates,
                                pinned_ip=pinned_ip,
                                peer_ip=peer_ip,
                                http_status=http_status,
                                error=hop_error,
                                observed_at=observed_at,
                            )
                        )
                        builder.error = hop_error
                        self._emit(builder)
                        raise
                    except httpx.HTTPStatusError as exc:
                        hop_error = f"{type(exc).__name__}: {exc}"
                        builder.hops.append(
                            FetchHop(
                                uri=current,
                                resolved_candidates=candidates,
                                pinned_ip=pinned_ip,
                                peer_ip=peer_ip,
                                http_status=getattr(exc.response, "status_code", http_status),
                                error=hop_error,
                                observed_at=observed_at,
                            )
                        )
                        # Non-retryable HTTP errors (after retry loop exhausted for 5xx)
                        if attempt >= self.max_retries or (
                            exc.response is not None
                            and exc.response.status_code not in RETRY_STATUS
                        ):
                            builder.error = hop_error
                            self._emit(builder)
                            raise
                        time.sleep((2**attempt) + random.uniform(0, 0.25))
                    except Exception as exc:
                        hop_error = f"{type(exc).__name__}: {exc}"
                        builder.hops.append(
                            FetchHop(
                                uri=current,
                                resolved_candidates=candidates,
                                pinned_ip=pinned_ip,
                                peer_ip=peer_ip,
                                http_status=http_status,
                                error=hop_error,
                                observed_at=observed_at,
                            )
                        )
                        if attempt >= self.max_retries:
                            builder.error = hop_error
                            self._emit(builder)
                            raise
                        time.sleep((2**attempt) + random.uniform(0, 0.25))
                else:
                    # retry loop exhausted without return or break-to-redirect
                    if hop_error is None:
                        hop_error = f"failed to fetch {url} after retries"
                    builder.error = hop_error
                    self._emit(builder)
                    raise RuntimeError(hop_error)
                # continued via redirect break
        except Exception as exc:
            if not builder.emitted:
                if builder.error is None:
                    builder.error = f"{type(exc).__name__}: {exc}"
                if not builder.hops:
                    builder.hops.append(
                        FetchHop(
                            uri=url,
                            resolved_candidates=(),
                            pinned_ip=None,
                            peer_ip=None,
                            http_status=None,
                            error=builder.error,
                            observed_at=datetime.now(UTC),
                        )
                    )
                self._emit(builder)
            raise


# Backwards-compatible alias used by acquisition layer naming in the plan.
SecClient = ControlledFetcher
