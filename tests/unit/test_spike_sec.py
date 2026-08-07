"""Unit tests for spike SEC helpers (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib.sec import (  # noqa: E402
    SizeLimitExceeded,
    assert_cik_accession_consistent,
    assert_path_under,
    classify_source_and_role,
    validate_accession,
    validate_cik,
)
from spike_lib.storage import ObjectStore  # noqa: E402


def test_validate_accession_accepts_canonical() -> None:
    assert validate_accession("0001065088-24-000036") == "0001065088-24-000036"


def test_validate_accession_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        validate_accession("../../other-directory")
    with pytest.raises(ValueError):
        validate_accession("0001065088-24-000036/../x")


def test_validate_cik_normalizes_and_rejects_junk() -> None:
    assert validate_cik("1065088") == "0001065088"
    assert validate_cik("0001065088") == "0001065088"
    with pytest.raises(ValueError):
        validate_cik("-1")
    with pytest.raises(ValueError):
        validate_cik("../etc")
    with pytest.raises(ValueError):
        validate_cik(" 1065088 ")


def test_cik_accession_consistency() -> None:
    assert_cik_accession_consistent("0001065088", "0001065088-24-000036")
    with pytest.raises(ValueError):
        assert_cik_accession_consistent("0000104169", "0001065088-24-000036")


def test_assert_path_under_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "spikes"
    root.mkdir()
    target = root / "0001065088-24-000036"
    target.mkdir()
    assert assert_path_under(target, root) == target.resolve()
    outside = tmp_path / "other"
    outside.mkdir()
    with pytest.raises(ValueError):
        assert_path_under(outside, root)
    with pytest.raises(ValueError):
        assert_path_under(root, root)


def test_classify_sec_generated_and_unknown() -> None:
    acc = "0001065088-24-000036"
    assert classify_source_and_role("FilingSummary.xml", accession=acc)[0] == (
        "sec_generated_rendering"
    )
    assert classify_source_and_role("MetaLinks.json", accession=acc)[0] == (
        "sec_generated_rendering"
    )
    assert classify_source_and_role("R1.htm", accession=acc)[0] == "sec_generated_rendering"
    assert classify_source_and_role("Show.js", accession=acc)[0] == "sec_generated_rendering"
    assert classify_source_and_role("mystery.bin", accession=acc) == ("unknown", "unknown")
    assert classify_source_and_role(f"{acc}.txt", accession=acc)[1] == "complete_submission"


def test_fetch_to_store_enforces_byte_limit(tmp_path: Path) -> None:
    from spike_lib.sec import SecClient

    store = ObjectStore(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1000)

    transport = httpx.MockTransport(handler)
    client = SecClient("Test test@example.com", min_interval_seconds=0)
    client._client = httpx.Client(transport=transport, follow_redirects=False)

    with pytest.raises(SizeLimitExceeded):
        client.fetch_to_store("https://example.com/big", store, max_bytes=100)
    client.close()


def test_fetch_to_store_writes_object(tmp_path: Path) -> None:
    from spike_lib.hashing import sha256_hex
    from spike_lib.sec import SecClient

    store = ObjectStore(tmp_path)
    body = b"hello-edgar"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/plain"})

    client = SecClient("Test test@example.com", min_interval_seconds=0)
    client._client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    fetched, obj = client.fetch_to_store("https://example.com/a", store, max_bytes=1000)
    assert obj.sha256 == sha256_hex(body)
    assert fetched.byte_size == len(body)
    assert store.open_bytes(obj.sha256) == body
    client.close()
