"""Companyfacts cache population stays off the build path and dedupes CIKs."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from edgar.cli import app
from edgar.config import Settings
from edgar.financials.companyfacts_cache import (
    cache_companyfacts_for_accessions,
    distinct_ciks,
)
from edgar.storage.objects import StoredObject

_EBAY_A = "0001065088-23-000006"
_EBAY_B = "0001065088-24-000036"
_WALMART = "0000104169-24-000056"


def test_distinct_ciks_preserve_first_seen_order() -> None:
    assert distinct_ciks((_EBAY_B, _EBAY_A, _WALMART, _EBAY_A)) == (
        "0001065088",
        "0000104169",
    )


def test_cache_uses_one_fetcher_for_each_distinct_cik(tmp_path: Path) -> None:
    class StubFetcher:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def fetch_to_store(
            self,
            url: str,
            store: object,
            *,
            max_bytes: int,
        ) -> tuple[None, StoredObject]:
            self.urls.append(url)
            digest = f"{len(self.urls):064x}"
            return None, StoredObject(sha256=digest, byte_size=1, storage_path=tmp_path / digest)

    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    fetcher = StubFetcher()
    stored = cache_companyfacts_for_accessions(
        settings,
        (_EBAY_A, _EBAY_B, _WALMART),
        fetcher,  # type: ignore[arg-type]
    )
    assert len(stored) == 2
    assert len(fetcher.urls) == 2
    assert fetcher.urls[0].endswith("CIK0001065088.json")
    assert fetcher.urls[1].endswith("CIK0000104169.json")
    assert (tmp_path / "companyfacts" / "CIK0001065088.sha256").is_file()
    assert (tmp_path / "companyfacts" / "CIK0000104169.sha256").is_file()


def test_companyfacts_command_refuses_to_fetch_without_a_user_agent(
    tmp_path: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "")
    accessions = tmp_path / "accessions.txt"
    accessions.write_text(f"{_EBAY_A}\n{_EBAY_B}\n", encoding="utf-8")

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("companyfacts command must not construct a fetcher")

    monkeypatch.setattr("edgar.sec.client.ControlledFetcher", fail_if_called)
    result = CliRunner().invoke(
        app,
        ["filings", "companyfacts", "--accessions-file", str(accessions)],
    )
    assert result.exit_code == 1
    assert "SEC_USER_AGENT" in result.stderr


def test_companyfacts_command_uses_a_single_fetcher(
    tmp_path: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "Review review@example.com")
    accessions = tmp_path / "accessions.txt"
    accessions.write_text(f"{_EBAY_A}\n{_EBAY_B}\n{_WALMART}\n", encoding="utf-8")
    constructed: list[object] = []

    class FakeFetcher:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            constructed.append(self)

        def __enter__(self) -> FakeFetcher:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_cache(settings: Settings, rows: tuple[str, ...], fetcher: FakeFetcher) -> tuple:
        assert fetcher is constructed[0]
        assert rows == (_EBAY_A, _EBAY_B, _WALMART)
        assert settings.edgar_data_root == tmp_path
        return ()

    monkeypatch.setattr("edgar.sec.client.ControlledFetcher", FakeFetcher)
    monkeypatch.setattr(
        "edgar.financials.companyfacts_cache.cache_companyfacts_for_accessions",
        fake_cache,
    )
    result = CliRunner().invoke(
        app,
        [
            "filings",
            "companyfacts",
            "--accessions-file",
            str(accessions),
            "--data-root",
            str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert len(constructed) == 1
    assert "0001065088" in result.stdout
    assert "0000104169" in result.stdout
