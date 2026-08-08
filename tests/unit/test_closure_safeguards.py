"""Unit tests for typed safeguard preservation across online closure IPC."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from edgar.domain.bundle import InstanceReportInput
from edgar.sec.limits import MaxExternalDependencyBytesExceeded, MaxRedirectsExceeded
from edgar.storage.objects import ObjectStore, SizeLimitExceeded
from edgar.xbrl.closure import run_online_closure
from edgar.xbrl.uri import normalize_uri


class RecordingFetcher:
    def __init__(self, *, fail_with: BaseException) -> None:
        self.fail_with = fail_with
        self.calls: list[str] = []

    def fetch_to_store(self, url, store, *, max_bytes: int):  # type: ignore[no-untyped-def]
        self.calls.append(normalize_uri(url))
        raise self.fail_with


def test_closure_preserves_redirect_safeguard(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    instance = store.put_bytes(b"<xbrl/>")
    instance_uri = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000001/a.xml")
    report = InstanceReportInput(document_uris=(instance_uri,))
    fetcher = RecordingFetcher(fail_with=MaxRedirectsExceeded("too many redirects"))

    def fake_worker(job, *, fetch_handler, **kwargs):  # type: ignore[no-untyped-def]
        # Ask for one external, then one more after failure should be blocked.
        fetch_handler("https://example.com/schema.xsd")
        second = fetch_handler("https://example.com/other.xsd")
        assert second["type"] == "fetch_error"
        assert "blocked" in second["error"]
        from edgar.xbrl.closure import WorkerRun

        return WorkerRun(
            result={
                "load_completed": False,
                "loaded_source_documents": [],
                "resolved_documents": [],
                "unresolved_documents": ["https://example.com/schema.xsd"],
                "network_attempts": [],
                "diagnostics": [],
                "errors": ["fetch failed"],
            },
            returncode=0,
            stderr="",
        )

    with patch("edgar.xbrl.closure.run_worker_process", side_effect=fake_worker):
        discovery = run_online_closure(
            report,
            accession_uri_map={instance_uri: (instance.sha256, "accession/a.xml")},
            store=store,
            fetcher=fetcher,  # type: ignore[arg-type]
            max_file_bytes=1_000_000,
            max_new_payload_bytes=1_000_000,
        )
    assert isinstance(discovery.fatal_safeguard, MaxRedirectsExceeded)
    assert len(fetcher.calls) == 1


def test_closure_maps_size_limit_to_external_code(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    instance = store.put_bytes(b"<xbrl/>")
    instance_uri = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000001/a.xml")
    report = InstanceReportInput(document_uris=(instance_uri,))
    fetcher = RecordingFetcher(fail_with=SizeLimitExceeded("too big"))

    def fake_worker(job, *, fetch_handler, **kwargs):  # type: ignore[no-untyped-def]
        fetch_handler("https://example.com/schema.xsd")
        from edgar.xbrl.closure import WorkerRun

        return WorkerRun(
            result={
                "load_completed": False,
                "loaded_source_documents": [],
                "resolved_documents": [],
                "unresolved_documents": [],
                "network_attempts": [],
                "diagnostics": [],
                "errors": [],
            },
            returncode=0,
            stderr="",
        )

    with patch("edgar.xbrl.closure.run_worker_process", side_effect=fake_worker):
        discovery = run_online_closure(
            report,
            accession_uri_map={instance_uri: (instance.sha256, "accession/a.xml")},
            store=store,
            fetcher=fetcher,  # type: ignore[arg-type]
            max_file_bytes=1_000_000,
            max_new_payload_bytes=1_000_000,
        )
    assert isinstance(discovery.fatal_safeguard, MaxExternalDependencyBytesExceeded)
