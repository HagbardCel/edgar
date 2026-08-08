"""Unit tests for SSRF destination policy and controlled fetcher hardening."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from edgar.sec.client import ControlledFetcher, FetchTrace
from edgar.sec.limits import MaxRedirectsExceeded
from edgar.sec.ssrf import (
    DestinationForbidden,
    peers_match,
    resolve_destination,
    resolve_public_ips,
    validate_url_syntax,
)
from edgar.storage.objects import ObjectStore


def test_rejects_file_and_credentials() -> None:
    with pytest.raises(DestinationForbidden):
        validate_url_syntax("file:///etc/passwd")
    with pytest.raises(DestinationForbidden):
        validate_url_syntax("https://user:pass@example.com/a")


def test_rejects_loopback_literal() -> None:
    with pytest.raises(DestinationForbidden):
        validate_url_syntax("http://127.0.0.1/secret")
    with pytest.raises(DestinationForbidden):
        validate_url_syntax("http://[::1]/")


def test_rejects_private_literal() -> None:
    with pytest.raises(DestinationForbidden):
        resolve_destination("http://192.168.1.1/x")
    with pytest.raises(DestinationForbidden):
        resolve_destination("http://10.0.0.1/x")


def test_allows_sec_hostnames() -> None:
    scheme, host, port, _path = validate_url_syntax(
        "https://data.sec.gov/submissions/CIK0001065088.json"
    )
    assert scheme == "https"
    assert host == "data.sec.gov"
    assert port == 443


def test_mixed_dns_fail_closed() -> None:
    infos = [
        (0, 0, 0, "", ("1.2.3.4", 443)),
        (0, 0, 0, "", ("10.0.0.1", 443)),
    ]
    with (
        patch("edgar.sec.ssrf.socket.getaddrinfo", return_value=infos),
        pytest.raises(DestinationForbidden, match="mixed or private"),
    ):
        resolve_public_ips("example.com", 443)


def test_peers_match_uses_ip_address() -> None:
    assert peers_match("1.2.3.4", "1.2.3.4")
    assert not peers_match("1.2.3.4", "1.2.3.5")


def test_client_trust_env_false_and_no_keepalive() -> None:
    fetcher = ControlledFetcher("Test Agent email@example.com")
    try:
        assert fetcher._client.trust_env is False
        assert fetcher._limits.max_keepalive_connections == 0
    finally:
        fetcher.close()


def test_fetch_emits_one_trace_on_pre_http_failure(tmp_path: Path) -> None:
    traces: list[FetchTrace] = []
    store = ObjectStore(tmp_path)
    fetcher = ControlledFetcher(
        "Test Agent email@example.com",
        observation_sink=traces.append,
        max_retries=0,
    )
    try:
        with pytest.raises(DestinationForbidden):
            fetcher.fetch_to_store("http://127.0.0.1/x", store, max_bytes=100)
    finally:
        fetcher.close()
    assert len(traces) == 1
    assert traces[0].error is not None
    assert traces[0].hops
    assert traces[0].hops[0].pinned_ip is None or traces[0].error


def test_redirect_budget_independent_of_retries(tmp_path: Path) -> None:
    """N redirects succeed with max_retries=0 (redirects do not consume retries)."""
    store = ObjectStore(tmp_path)
    traces: list[FetchTrace] = []
    fetcher = ControlledFetcher(
        "Test Agent email@example.com",
        max_retries=0,
        max_redirects=3,
        min_interval_seconds=0,
        observation_sink=traces.append,
    )

    hop = {"n": 0}

    def fake_stream(method, url, **kwargs):  # type: ignore[no-untyped-def]
        class Resp:
            status_code = 302
            headers = {"Location": f"https://example.com/next{hop['n']}"}
            extensions: dict = {}

            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self):  # type: ignore[no-untyped-def]
                yield b"ok"

            def __enter__(self):  # type: ignore[no-untyped-def]
                return self

            def __exit__(self, *args: object) -> None:
                return None

        class Final(Resp):
            status_code = 200
            headers = {}

        class CM:
            def __enter__(self):  # type: ignore[no-untyped-def]
                hop["n"] += 1
                if hop["n"] <= 2:
                    return Resp()
                return Final()

            def __exit__(self, *args: object) -> None:
                return None

        return CM()

    try:
        with (
            patch.object(fetcher, "_pinned_request") as pinned,
            patch.object(fetcher._client, "stream", side_effect=fake_stream),
        ):
            pinned.side_effect = lambda url: (
                url.replace("https://example.com", "https://1.2.3.4"),
                "example.com",
                443,
                "https",
                "1.2.3.4",
                ("1.2.3.4",),
            )
            with patch("edgar.sec.client.validate_url_syntax", return_value=None):
                result, obj = fetcher.fetch_to_store(
                    "https://example.com/start", store, max_bytes=1000
                )
        assert result.redirect_count == 2
        assert obj.byte_size == 2
        assert len(traces) == 1
    finally:
        fetcher.close()


def test_peer_mismatch_fails_closed(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    traces: list[FetchTrace] = []
    fetcher = ControlledFetcher(
        "Test Agent email@example.com",
        max_retries=0,
        min_interval_seconds=0,
        observation_sink=traces.append,
    )

    stream = MagicMock()
    stream.get_extra_info.return_value = ("9.9.9.9", 443)

    class Resp:
        status_code = 200
        headers: dict = {}
        extensions = {"network_stream": stream}

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):  # type: ignore[no-untyped-def]
            yield b"x"

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args: object) -> None:
            return None

    try:
        with (
            patch.object(fetcher, "_pinned_request") as pinned,
            patch.object(fetcher._client, "stream", return_value=Resp()),
            patch("edgar.sec.client.validate_url_syntax", return_value=None),
        ):
            pinned.return_value = (
                "https://1.2.3.4/a",
                "example.com",
                443,
                "https",
                "1.2.3.4",
                ("1.2.3.4",),
            )
            with pytest.raises(DestinationForbidden, match="peer"):
                fetcher.fetch_to_store("https://example.com/a", store, max_bytes=100)
    finally:
        fetcher.close()
    assert len(traces) == 1


def test_host_header_includes_non_default_port() -> None:
    from edgar.sec.client import _host_header

    assert _host_header("example.com", 8443, "https") == "example.com:8443"
    assert _host_header("example.com", 443, "https") == "example.com"


def test_max_redirects_typed(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fetcher = ControlledFetcher(
        "Test Agent email@example.com",
        max_retries=0,
        max_redirects=0,
        min_interval_seconds=0,
    )

    class Resp:
        status_code = 302
        headers = {"Location": "https://example.com/b"}
        extensions: dict = {}

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args: object) -> None:
            return None

    try:
        with (
            patch.object(fetcher, "_pinned_request") as pinned,
            patch.object(fetcher._client, "stream", return_value=Resp()),
            patch("edgar.sec.client.validate_url_syntax", return_value=None),
        ):
            pinned.return_value = (
                "https://1.2.3.4/a",
                "example.com",
                443,
                "https",
                "1.2.3.4",
                ("1.2.3.4",),
            )
            with pytest.raises(MaxRedirectsExceeded):
                fetcher.fetch_to_store("https://example.com/a", store, max_bytes=100)
    finally:
        fetcher.close()
