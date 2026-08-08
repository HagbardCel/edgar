"""Unit tests for SSRF destination policy."""

from __future__ import annotations

import pytest

from edgar.sec.ssrf import DestinationForbidden, resolve_destination, validate_url_syntax


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
    scheme, host, port, _path = validate_url_syntax("https://data.sec.gov/submissions/CIK0001065088.json")
    assert scheme == "https"
    assert host == "data.sec.gov"
    assert port == 443
    scheme, host, port, _path = validate_url_syntax(
        "https://www.sec.gov/Archives/edgar/data/1065088/000106508824000036/index.json"
    )
    assert host == "www.sec.gov"
