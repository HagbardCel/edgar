"""Network denial guard for offline Arelle loads."""

from __future__ import annotations

import socket
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class NetworkAttempt:
    host: str
    port: int | None
    order: int
    timestamp: str
    stack_summary: str
    method: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "order": self.order,
            "timestamp": self.timestamp,
            "stack_summary": self.stack_summary,
            "method": self.method,
        }


@dataclass
class NetworkGuard:
    attempts: list[NetworkAttempt] = field(default_factory=list)
    enabled: bool = False

    def record(self, method: str, host: str, port: int | None) -> None:
        stack = "".join(traceback.format_stack(limit=12)[:-1])
        self.attempts.append(
            NetworkAttempt(
                host=str(host),
                port=port,
                order=len(self.attempts) + 1,
                timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                stack_summary=stack[-2000:],
                method=method,
            )
        )

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


class NetworkDeniedError(RuntimeError):
    def __init__(self, attempt: NetworkAttempt) -> None:
        self.attempt = attempt
        super().__init__(
            f"network denied during offline load: {attempt.method} {attempt.host}:{attempt.port}"
        )


@contextmanager
def network_denied(guard: NetworkGuard) -> Iterator[NetworkGuard]:
    """Deny TCP connects and record every attempt.

    Intercepts socket.create_connection, socket.socket.connect, and connect_ex.
    """
    guard.enabled = True
    original_create = socket.create_connection
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def _deny_create(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else str(address)
        port = address[1] if isinstance(address, tuple) and len(address) > 1 else None
        guard.record("create_connection", str(host), port if isinstance(port, int) else None)
        raise NetworkDeniedError(guard.attempts[-1])

    def _deny_connect(self, address):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else str(address)
        port = address[1] if isinstance(address, tuple) and len(address) > 1 else None
        guard.record("connect", str(host), port if isinstance(port, int) else None)
        raise NetworkDeniedError(guard.attempts[-1])

    def _deny_connect_ex(self, address):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else str(address)
        port = address[1] if isinstance(address, tuple) and len(address) > 1 else None
        guard.record("connect_ex", str(host), port if isinstance(port, int) else None)
        return 111  # ECONNREFUSED

    socket.create_connection = _deny_create  # type: ignore[assignment]
    socket.socket.connect = _deny_connect  # type: ignore[method-assign, assignment]
    socket.socket.connect_ex = _deny_connect_ex  # type: ignore[method-assign, assignment]
    try:
        yield guard
    finally:
        socket.create_connection = original_create  # type: ignore[assignment]
        socket.socket.connect = original_connect  # type: ignore[method-assign, assignment]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign, assignment]
        guard.enabled = False
