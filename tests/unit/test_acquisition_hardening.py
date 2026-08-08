"""Unit tests for acquisition/fetcher P2 hardening."""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from edgar.config import Settings
from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.domain.issues import QualityIssue
from edgar.domain.payload import compute_payload_hash
from edgar.ingestion.acquisition import AcquisitionService
from edgar.sec.client import ControlledFetcher, FetchHop, FetchTrace
from edgar.sec.limits import MaxBundleBytesExceeded, MaxFileBytesExceeded
from edgar.sec.ssrf import DestinationForbidden
from edgar.sec.submissions import AccessionMetadata, lookup_accession_metadata
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore, SizeLimitExceeded


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    data: dict[str, object] = {
        "SEC_USER_AGENT": "Test Agent email@example.com",
        "EDGAR_DATA_ROOT": tmp_path,
        "SEC_REQUESTS_PER_SECOND": 1000.0,
        "SEC_MAX_RETRIES": 1,
        "MAX_REDIRECTS": 5,
        "MAX_FILE_BYTES": 1_000,
        "MAX_BUNDLE_BYTES": 2_000,
    }
    data.update(overrides)
    return Settings(_env_file=None, **data)  # type: ignore[arg-type]


def _meta(*, discovery: dict | None = None) -> AccessionMetadata:
    return AccessionMetadata(
        cik="0001065088",
        accession="0001065088-24-000036",
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        accepted_at=None,
        report_period_end=None,
        primary_document="a.htm",
        is_inline_xbrl=False,
        is_xbrl=True,
        submissions_content_sha256="ab" * 32,
        discovery=discovery or {"accession": "0001065088-24-000036", "cik": "0001065088"},
    )


def _bundle(store: ObjectStore, data: bytes = b"x") -> FilingBundle:
    obj = store.put_bytes(data)
    art = BundleArtifact(
        logical_path="accession/a.xml",
        content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
        artifact_kind="attachment",
        required=True,
    )
    return FilingBundle(
        filing=FilingIdentity(
            cik="0001065088",
            accession="0001065088-24-000036",
            form_type="10-K",
            filing_date=date(2024, 1, 1),
            accepted_at=None,
            report_period_end=None,
            primary_document="a.htm",
        ),
        payload_hash=compute_payload_hash([art]),
        artifacts=(art,),
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/a.xml",)),),
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/a.xml",
                artifact_path="accession/a.xml",
                content_sha256=obj.sha256,
            ),
        ),
    )


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://www.sec.gov/x")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(f"{status_code}", request=request, response=response)


def _index_json_bytes(*names: str) -> bytes:
    items = [
        {
            "name": name,
            "last-modified": "01-01-2024",
            "size": "1",
            "type": "text/html",
        }
        for name in names
    ]
    return json.dumps({"directory": {"item": items}}).encode()


def test_trace_redirect_count_retries_only(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    traces: list[FetchTrace] = []
    fetcher = ControlledFetcher(
        "Test Agent email@example.com",
        max_retries=2,
        min_interval_seconds=0,
        observation_sink=traces.append,
    )
    attempts = {"n": 0}

    class Resp:
        headers: dict = {}
        extensions: dict = {}

        def __init__(self, status: int) -> None:
            self.status_code = status

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise _http_status_error(self.status_code)

        def iter_bytes(self):  # type: ignore[no-untyped-def]
            yield b"ok"

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_stream(method, url, **kwargs):  # type: ignore[no-untyped-def]
        attempts["n"] += 1
        if attempts["n"] < 3:
            return Resp(503)
        return Resp(200)

    try:
        with (
            patch.object(fetcher, "_pinned_request") as pinned,
            patch.object(fetcher._client, "stream", side_effect=fake_stream),
            patch("edgar.sec.client.validate_url_syntax", return_value=None),
            patch("edgar.sec.client.time.sleep", return_value=None),
        ):
            pinned.return_value = (
                "https://1.2.3.4/a",
                "example.com",
                443,
                "https",
                "1.2.3.4",
                ("1.2.3.4",),
            )
            result, _obj = fetcher.fetch_to_store("https://example.com/a", store, max_bytes=100)
    finally:
        fetcher.close()
    assert result.redirect_count == 0
    assert traces[0].redirect_count == 0
    assert traces[0].to_observation_dict()["redirect_count"] == 0


def test_trace_redirect_count_exact_with_retries(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    traces: list[FetchTrace] = []
    fetcher = ControlledFetcher(
        "Test Agent email@example.com",
        max_retries=1,
        max_redirects=5,
        min_interval_seconds=0,
        observation_sink=traces.append,
    )
    seq = {"i": 0}

    class Resp:
        extensions: dict = {}

        def __init__(self, status: int, location: str | None = None) -> None:
            self.status_code = status
            self.headers = {"Location": location} if location else {}

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise _http_status_error(self.status_code)

        def iter_bytes(self):  # type: ignore[no-untyped-def]
            yield b"ok"

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_stream(method, url, **kwargs):  # type: ignore[no-untyped-def]
        seq["i"] += 1
        if seq["i"] == 1:
            return Resp(503)
        if seq["i"] == 2:
            return Resp(302, "https://example.com/b")
        if seq["i"] == 3:
            return Resp(503)
        return Resp(200)

    try:
        with (
            patch.object(fetcher, "_pinned_request") as pinned,
            patch.object(fetcher._client, "stream", side_effect=fake_stream),
            patch("edgar.sec.client.validate_url_syntax", return_value=None),
            patch("edgar.sec.client.time.sleep", return_value=None),
        ):
            pinned.side_effect = lambda url: (
                url.replace("https://example.com", "https://1.2.3.4"),
                "example.com",
                443,
                "https",
                "1.2.3.4",
                ("1.2.3.4",),
            )
            result, _obj = fetcher.fetch_to_store(
                "https://example.com/start", store, max_bytes=1000
            )
    finally:
        fetcher.close()
    assert result.redirect_count == 1
    assert traces[0].redirect_count == 1
    assert len(traces[0].hops) > 2
    assert traces[0].to_observation_dict()["redirect_count"] == 1


def test_dns_resolution_once_per_physical_attempt(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fetcher = ControlledFetcher(
        "Test Agent email@example.com",
        max_retries=1,
        max_redirects=3,
        min_interval_seconds=0,
    )
    resolves: list[str] = []
    seq = {"i": 0}

    class Resp:
        extensions: dict = {}

        def __init__(self, status: int, location: str | None = None) -> None:
            self.status_code = status
            self.headers = {"Location": location} if location else {}

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self):  # type: ignore[no-untyped-def]
            yield b"ok"

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_stream(method, url, **kwargs):  # type: ignore[no-untyped-def]
        seq["i"] += 1
        if seq["i"] == 1:
            return Resp(503)
        if seq["i"] == 2:
            return Resp(302, "https://example.com/b")
        return Resp(200)

    def pinned(url: str):  # type: ignore[no-untyped-def]
        resolves.append(url)
        return (
            url.replace("https://example.com", "https://1.2.3.4"),
            "example.com",
            443,
            "https",
            "1.2.3.4",
            ("1.2.3.4",),
        )

    try:
        with (
            patch.object(fetcher, "_pinned_request", side_effect=pinned),
            patch.object(fetcher._client, "stream", side_effect=fake_stream),
            patch("edgar.sec.client.validate_url_syntax", return_value=None),
            patch("edgar.sec.client.time.sleep", return_value=None),
        ):
            fetcher.fetch_to_store("https://example.com/a", store, max_bytes=100)
    finally:
        fetcher.close()
    assert resolves == [
        "https://example.com/a",
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_proxy_env_ignored_pinned_request_target(tmp_path: Path) -> None:
    prior_http = os.environ.get("HTTP_PROXY")
    prior_https = os.environ.get("HTTPS_PROXY")
    os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"
    os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
    store = ObjectStore(tmp_path)
    seen: dict[str, object] = {}
    try:
        fetcher = ControlledFetcher(
            "Test Agent email@example.com",
            max_retries=0,
            min_interval_seconds=0,
        )
        assert fetcher._client.trust_env is False

        class Resp:
            status_code = 200
            headers: dict = {}
            extensions: dict = {}

            def raise_for_status(self) -> None:
                return None

            def iter_bytes(self):  # type: ignore[no-untyped-def]
                yield b"ok"

            def __enter__(self):  # type: ignore[no-untyped-def]
                return self

            def __exit__(self, *args: object) -> None:
                return None

        def fake_stream(method, url, **kwargs):  # type: ignore[no-untyped-def]
            seen["url"] = url
            seen["headers"] = kwargs.get("headers")
            seen["extensions"] = kwargs.get("extensions")
            return Resp()

        with (
            patch.object(fetcher, "_pinned_request") as pinned,
            patch.object(fetcher._client, "stream", side_effect=fake_stream),
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
            fetcher.fetch_to_store("https://example.com/a", store, max_bytes=100)
        assert seen["url"] == "https://1.2.3.4/a"
        assert seen["headers"] == {"Host": "example.com"}
        assert seen["extensions"] == {"sni_hostname": "example.com"}
        fetcher.close()
    finally:
        if prior_http is None:
            os.environ.pop("HTTP_PROXY", None)
        else:
            os.environ["HTTP_PROXY"] = prior_http
        if prior_https is None:
            os.environ.pop("HTTPS_PROXY", None)
        else:
            os.environ["HTTPS_PROXY"] = prior_https


def test_optional_404_is_warning_only(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = ObjectStore(tmp_path)
    fetcher = MagicMock()
    service = AcquisitionService(settings, fetcher=fetcher, store=store)
    issues: list[QualityIssue] = []

    def side_effect(url, store, *, max_bytes: int):  # type: ignore[no-untyped-def]
        if "index.json" in url:
            return MagicMock(status_code=200), store.put_bytes(_index_json_bytes())
        if url.endswith("-index.html"):
            return MagicMock(status_code=200), store.put_bytes(b"<html></html>")
        if "index-headers" in url or url.endswith("-index.htm"):
            raise _http_status_error(404)
        raise AssertionError(url)

    fetcher.fetch_to_store.side_effect = side_effect
    with (
        patch(
            "edgar.ingestion.acquisition.lookup_accession_metadata",
            return_value=(_meta(), []),
        ),
        pytest.raises(RuntimeError, match="fatal acquisition completeness"),
    ):
        service._acquire_body("0001065088-24-000036", attempt_id="t", issues=issues)
    assert any(i.code == "OPTIONAL_ARTIFACT_MISSING" and i.severity == "warning" for i in issues)


def test_optional_403_is_fatal(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = ObjectStore(tmp_path)
    issues: list[QualityIssue] = []
    fetcher = MagicMock()
    service = AcquisitionService(settings, fetcher=fetcher, store=store)

    def side_effect(url, store, *, max_bytes: int):  # type: ignore[no-untyped-def]
        if "index.json" in url:
            return MagicMock(status_code=200), store.put_bytes(_index_json_bytes())
        if url.endswith("-index.html"):
            return MagicMock(status_code=200), store.put_bytes(b"<html></html>")
        if "index-headers" in url:
            raise _http_status_error(403)
        if url.endswith("-index.htm"):
            raise _http_status_error(404)
        raise AssertionError(url)

    fetcher.fetch_to_store.side_effect = side_effect
    with (
        patch(
            "edgar.ingestion.acquisition.lookup_accession_metadata",
            return_value=(_meta(), []),
        ),
        pytest.raises(httpx.HTTPStatusError),
    ):
        service._acquire_body("0001065088-24-000036", attempt_id="t", issues=issues)
    assert not any(i.code == "OPTIONAL_ARTIFACT_MISSING" for i in issues)


def test_optional_exhausted_5xx_is_fatal(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = ObjectStore(tmp_path)
    issues: list[QualityIssue] = []
    fetcher = MagicMock()
    service = AcquisitionService(settings, fetcher=fetcher, store=store)

    def side_effect(url, store, *, max_bytes: int):  # type: ignore[no-untyped-def]
        if "index.json" in url:
            return MagicMock(status_code=200), store.put_bytes(_index_json_bytes())
        if url.endswith("-index.html"):
            return MagicMock(status_code=200), store.put_bytes(b"<html></html>")
        if "index-headers" in url:
            raise _http_status_error(503)
        if url.endswith("-index.htm"):
            raise _http_status_error(404)
        raise AssertionError(url)

    fetcher.fetch_to_store.side_effect = side_effect
    with (
        patch(
            "edgar.ingestion.acquisition.lookup_accession_metadata",
            return_value=(_meta(), []),
        ),
        pytest.raises(httpx.HTTPStatusError),
    ):
        service._acquire_body("0001065088-24-000036", attempt_id="t", issues=issues)
    assert not any(i.code == "OPTIONAL_ARTIFACT_MISSING" for i in issues)


def test_missing_filer_not_applied_for_safeguards(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = ObjectStore(tmp_path)
    issues: list[QualityIssue] = []
    fetcher = MagicMock()
    service = AcquisitionService(settings, fetcher=fetcher, store=store)

    def side_effect(url, store, *, max_bytes: int):  # type: ignore[no-untyped-def]
        if "index.json" in url:
            return MagicMock(status_code=200), store.put_bytes(_index_json_bytes("a.htm"))
        if url.endswith("-index.html"):
            return MagicMock(status_code=200), store.put_bytes(b"<html></html>")
        if url.endswith("a.htm"):
            raise DestinationForbidden("blocked")
        if "index-headers" in url or url.endswith("-index.htm"):
            raise _http_status_error(404)
        raise AssertionError(url)

    fetcher.fetch_to_store.side_effect = side_effect
    with (
        patch(
            "edgar.ingestion.acquisition.lookup_accession_metadata",
            return_value=(_meta(), []),
        ),
        patch(
            "edgar.ingestion.acquisition.classify_source_and_role",
            return_value=("filer_submitted", "primary_document"),
        ),
        pytest.raises(DestinationForbidden),
    ):
        service._acquire_body("0001065088-24-000036", attempt_id="t", issues=issues)
    assert not any(i.code == "MISSING_FILER_SUBMITTED_ATTACHMENT" for i in issues)


def test_missing_filer_on_ordinary_http_miss(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = ObjectStore(tmp_path)
    issues: list[QualityIssue] = []
    fetcher = MagicMock()
    service = AcquisitionService(settings, fetcher=fetcher, store=store)

    def side_effect(url, store, *, max_bytes: int):  # type: ignore[no-untyped-def]
        if "index.json" in url:
            return MagicMock(status_code=200), store.put_bytes(_index_json_bytes("a.htm"))
        if url.endswith("-index.html"):
            return MagicMock(status_code=200), store.put_bytes(b"<html></html>")
        if url.endswith("a.htm"):
            raise _http_status_error(404)
        if "index-headers" in url or url.endswith("-index.htm"):
            raise _http_status_error(404)
        raise AssertionError(url)

    fetcher.fetch_to_store.side_effect = side_effect
    with (
        patch(
            "edgar.ingestion.acquisition.lookup_accession_metadata",
            return_value=(_meta(), []),
        ),
        patch(
            "edgar.ingestion.acquisition.classify_source_and_role",
            return_value=("filer_submitted", "primary_document"),
        ),
        pytest.raises(httpx.HTTPStatusError),
    ):
        service._acquire_body("0001065088-24-000036", attempt_id="t", issues=issues)
    assert any(i.code == "MISSING_FILER_SUBMITTED_ATTACHMENT" for i in issues)


def test_discovery_json_max_file_vs_bundle(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    issues: list[QualityIssue] = []
    settings_file = _settings(tmp_path, MAX_FILE_BYTES=10, MAX_BUNDLE_BYTES=10_000)
    service = AcquisitionService(settings_file, fetcher=MagicMock(), store=store)
    with (
        patch(
            "edgar.ingestion.acquisition.lookup_accession_metadata",
            return_value=(_meta(discovery={"pad": "x" * 50}), []),
        ),
        pytest.raises(MaxFileBytesExceeded),
    ):
        service._acquire_body("0001065088-24-000036", attempt_id="t", issues=issues)

    settings_bundle = _settings(tmp_path, MAX_FILE_BYTES=10_000, MAX_BUNDLE_BYTES=30)
    service2 = AcquisitionService(settings_bundle, fetcher=MagicMock(), store=ObjectStore(tmp_path))
    with (
        patch(
            "edgar.ingestion.acquisition.lookup_accession_metadata",
            return_value=(_meta(discovery={"pad": "y" * 40}), []),
        ),
        pytest.raises(MaxBundleBytesExceeded),
    ):
        service2._acquire_body("0001065088-24-000036", attempt_id="t", issues=[])


def test_submissions_current_and_historical_traces_retained(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    traces: list[FetchTrace] = []
    fetcher = MagicMock()
    fetcher.observation_sink = traces.append

    current = {
        "filings": {
            "recent": {"accessionNumber": []},
            "files": [{"name": "CIK0001065088-submissions-001.json"}],
        }
    }
    historical = {
        "accessionNumber": ["0001065088-24-000036"],
        "form": ["10-K"],
        "filingDate": ["2024-01-01"],
        "acceptanceDateTime": ["20240101120000"],
        "reportDate": ["2023-12-31"],
        "primaryDocument": ["a.htm"],
        "isInlineXBRL": [0],
        "isXBRL": [1],
    }

    def side_effect(url, store, *, max_bytes: int):  # type: ignore[no-untyped-def]
        data = json.dumps(current if url.endswith("CIK0001065088.json") else historical).encode()
        obj = store.put_bytes(data)
        observed_at = datetime.now(UTC)
        trace = FetchTrace(
            requested_uri=url,
            hops=(
                FetchHop(
                    uri=url,
                    resolved_candidates=("1.2.3.4",),
                    pinned_ip="1.2.3.4",
                    peer_ip="1.2.3.4",
                    http_status=200,
                    error=None,
                    observed_at=observed_at,
                ),
            ),
            final_uri=url,
            content_sha256=obj.sha256,
            byte_size=obj.byte_size,
            redirect_count=0,
        )
        traces.append(trace)
        result = MagicMock()
        result.to_observation_dict.return_value = trace.to_observation_dict()
        return result, obj

    fetcher.fetch_to_store.side_effect = side_effect
    meta, _issues = lookup_accession_metadata(
        fetcher, store, "0001065088-24-000036", max_bytes=100_000
    )
    assert meta.accession == "0001065088-24-000036"
    assert len(traces) == 2
    assert traces[0].requested_uri.endswith("CIK0001065088.json")
    assert "submissions-001.json" in traces[1].requested_uri


def test_early_failure_writes_one_failed_attempt(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    fetcher = MagicMock()
    fetcher.observation_sink = None
    service = AcquisitionService(settings, fetcher=fetcher, store=ObjectStore(tmp_path))
    with (
        patch(
            "edgar.ingestion.acquisition.lookup_accession_metadata",
            side_effect=DestinationForbidden("nope"),
        ),
        pytest.raises(DestinationForbidden),
    ):
        service.acquire("0001065088-24-000036")
    attempts = list((tmp_path / "acquisition-attempts").iterdir())
    assert len(attempts) == 1
    payload = json.loads((attempts[0] / "result.json").read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["terminal_error"]["exception_type"] == "DestinationForbidden"


def test_budget_enforced_on_metadata_fetch(tmp_path: Path) -> None:
    settings = _settings(tmp_path, MAX_FILE_BYTES=100, MAX_BUNDLE_BYTES=50)
    store = ObjectStore(tmp_path)
    fetcher = MagicMock()
    service = AcquisitionService(settings, fetcher=fetcher, store=store)

    def side_effect(url, store, *, max_bytes: int):  # type: ignore[no-untyped-def]
        assert max_bytes <= 50
        raise SizeLimitExceeded("too big")

    fetcher.fetch_to_store.side_effect = side_effect
    with (
        patch(
            "edgar.ingestion.acquisition.lookup_accession_metadata",
            return_value=(_meta(discovery={"a": 1}), []),
        ),
        pytest.raises(MaxBundleBytesExceeded),
    ):
        service._acquire_body("0001065088-24-000036", attempt_id="t", issues=[])


def test_concurrent_publish_one_uuid_one_reuse(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    repo = BundleRepository(tmp_path, store)
    bundle = _bundle(store)
    results: list[object] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            results.append(repo.publish(bundle))
        except BaseException as exc:  # noqa: BLE001 - collect for assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    assert len(results) == 2
    reused = sorted(r.reused for r in results)  # type: ignore[attr-defined]
    assert reused == [False, True]
    ids = {r.opaque_id for r in results}  # type: ignore[attr-defined]
    assert len(ids) == 1
