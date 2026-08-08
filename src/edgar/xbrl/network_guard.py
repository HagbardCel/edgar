"""Socket-level network denial for the isolated Arelle worker (ADR 0009).

The worker subprocess must never open an ``AF_INET`` / ``AF_INET6`` connection.
Every remote byte reaches the worker through the parent-mediated IPC channel,
so any outbound connect attempt is a contract violation. The guard denies the
attempt and records it as evidence for the projection/replay result.
"""

from __future__ import annotations

import errno
import socket
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

DENIED_FAMILIES = frozenset({socket.AF_INET, socket.AF_INET6})

_STACK_FRAME_LIMIT = 12
_STACK_CHAR_LIMIT = 2000


@dataclass(frozen=True)
class NetworkAttempt:
    """A denied outbound network attempt observed inside the worker."""

    method: str
    host: str
    port: int | None
    order: int
    attempted_at: datetime
    stack_summary: str

    def __post_init__(self) -> None:
        if self.attempted_at.tzinfo is None:
            raise ValueError("attempted_at must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "host": self.host,
            "port": self.port,
            "order": self.order,
            "attempted_at": self.attempted_at.isoformat(),
            "stack_summary": self.stack_summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkAttempt:
        return cls(
            method=data["method"],
            host=data["host"],
            port=data.get("port"),
            order=int(data["order"]),
            attempted_at=datetime.fromisoformat(data["attempted_at"]),
            stack_summary=data.get("stack_summary", ""),
        )


class NetworkDeniedError(RuntimeError):
    """Raised when denied code attempts an outbound INET connection."""

    def __init__(self, attempt: NetworkAttempt) -> None:
        self.attempt = attempt
        super().__init__(
            f"network denied in isolated worker: {attempt.method} {attempt.host}:{attempt.port}"
        )


@dataclass
class NetworkGuard:
    """Ordered record of denied network attempts."""

    attempts: list[NetworkAttempt] = field(default_factory=list)
    active: bool = False

    def record(self, method: str, host: str, port: int | None) -> NetworkAttempt:
        frames = traceback.format_stack(limit=_STACK_FRAME_LIMIT)[:-1]
        attempt = NetworkAttempt(
            method=method,
            host=host,
            port=port,
            order=len(self.attempts) + 1,
            attempted_at=datetime.now(UTC),
            stack_summary="".join(frames)[-_STACK_CHAR_LIMIT:],
        )
        self.attempts.append(attempt)
        return attempt

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    def to_dicts(self) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self.attempts]


def address_parts(address: object) -> tuple[str, int | None]:
    """Best-effort ``(host, port)`` extraction from a socket address."""
    if isinstance(address, tuple) and address:
        host = str(address[0])
        port = address[1] if len(address) > 1 and isinstance(address[1], int) else None
        return host, port
    return str(address), None


@contextmanager
def deny_inet_sockets(guard: NetworkGuard) -> Iterator[NetworkGuard]:
    """Deny ``AF_INET``/``AF_INET6`` connects, recording every attempt.

    ``AF_UNIX`` and other local families stay usable so that ordinary process
    plumbing keeps working.
    """
    original_create_connection = socket.create_connection
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def denied_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        host, port = address_parts(address)
        raise NetworkDeniedError(guard.record("create_connection", host, port))

    def denied_connect(self: socket.socket, address: Any) -> Any:
        if self.family not in DENIED_FAMILIES:
            return original_connect(self, address)
        host, port = address_parts(address)
        raise NetworkDeniedError(guard.record("socket.connect", host, port))

    def denied_connect_ex(self: socket.socket, address: Any) -> int:
        if self.family not in DENIED_FAMILIES:
            return original_connect_ex(self, address)
        host, port = address_parts(address)
        guard.record("socket.connect_ex", host, port)
        return errno.ECONNREFUSED

    guard.active = True
    socket.create_connection = denied_create_connection  # type: ignore[assignment]
    socket.socket.connect = denied_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = denied_connect_ex  # type: ignore[method-assign]
    try:
        yield guard
    finally:
        socket.create_connection = original_create_connection  # type: ignore[assignment]
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]
        guard.active = False
