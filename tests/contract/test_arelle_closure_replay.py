"""Contract tests for Arelle worker isolation and closure/replay."""

from __future__ import annotations

import socket
from datetime import date
from pathlib import Path

import pytest

from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.domain.identifiers import validate_cik
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.objects import ObjectStore
from edgar.xbrl.closure import run_online_closure
from edgar.xbrl.network_guard import NetworkDeniedError, NetworkGuard, deny_inet_sockets
from edgar.xbrl.replay import validate_offline_replay
from edgar.xbrl.uri import normalize_uri

MINIMAL_SCHEMA = b"""<?xml version="1.0"?>
<schema xmlns="http://www.w3.org/2001/XMLSchema"
        targetNamespace="http://example.com/test"
        elementFormDefault="qualified">
  <element name="Assets" type="string"/>
</schema>
"""

MINIMAL_INSTANCE = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:t="http://example.com/test">
  <link:schemaRef xlink:type="simple" xlink:href="https://example.com/test.xsd"/>
  <xbrli:context id="c1">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <t:Assets contextRef="c1">1</t:Assets>
</xbrli:xbrl>
"""


class FakeFetcher:
    def __init__(self, mapping: dict[str, bytes]) -> None:
        self.mapping = {normalize_uri(k): v for k, v in mapping.items()}
        self.calls: list[str] = []

    def fetch_to_store(self, url, store, *, max_bytes: int):  # type: ignore[no-untyped-def]
        from datetime import UTC, datetime

        from edgar.sec.client import FetchResult

        canonical = normalize_uri(url)
        self.calls.append(canonical)
        data = self.mapping[canonical]
        obj = store.put_bytes(data)
        result = FetchResult(
            requested_uri=url,
            final_uri=canonical,
            status_code=200,
            headers={},
            redirect_count=0,
            sha256=obj.sha256,
            byte_size=obj.byte_size,
            pinned_ip="1.2.3.4",
            observed_at=datetime.now(UTC),
            peer_ip="1.2.3.4",
        )
        return result, obj


def test_network_guard_blocks_inet() -> None:
    guard = NetworkGuard()
    with deny_inet_sockets(guard), pytest.raises(NetworkDeniedError):
        socket.create_connection(("example.com", 80), timeout=0.1)
    assert guard.attempt_count >= 1


def test_online_closure_and_offline_replay(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    schema_uri = "https://example.com/test.xsd"
    instance_uri = "https://www.sec.gov/Archives/edgar/data/1/0000000001000001/a.xml"
    store.put_bytes(MINIMAL_SCHEMA)
    instance_obj = store.put_bytes(MINIMAL_INSTANCE)
    accession_map = {
        normalize_uri(instance_uri): (instance_obj.sha256, "accession/a.xml"),
    }
    fetcher = FakeFetcher({schema_uri: MINIMAL_SCHEMA})
    report = InstanceReportInput(document_uris=(normalize_uri(instance_uri),))
    discovery = run_online_closure(
        report,
        accession_uri_map=accession_map,
        store=store,
        fetcher=fetcher,  # type: ignore[arg-type]
        max_file_bytes=1_000_000,
    )
    assert discovery.load_completed
    assert discovery.uri_bindings
    # Schema should have been fetched once via parent.
    assert normalize_uri(schema_uri) in fetcher.calls

    artifacts = [
        BundleArtifact(
            logical_path="accession/a.xml",
            content=ContentObject(sha256=instance_obj.sha256, byte_size=instance_obj.byte_size),
            artifact_kind="attachment",
            required=True,
        ),
    ]
    for binding in discovery.uri_bindings:
        if binding.artifact_path.startswith("external/"):
            artifacts.append(
                BundleArtifact(
                    logical_path=binding.artifact_path,
                    content=ContentObject(
                        sha256=binding.content_sha256,
                        byte_size=len(store.open_bytes(binding.content_sha256)),
                    ),
                    artifact_kind="external",
                    required=True,
                )
            )
    filing = FilingIdentity(
        cik=validate_cik("1"),
        accession="0000000001-00-000001",
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        accepted_at=None,
        report_period_end=None,
        primary_document="a.xml",
    )
    bundle = FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash(artifacts),
        artifacts=tuple(artifacts),
        report_inputs=(report,),
        uri_bindings=tuple(discovery.uri_bindings),
    )
    replay = validate_offline_replay(bundle, store)
    assert replay.replay_faithful, (replay.errors, replay.unresolved_documents, replay.diagnostics)


def test_unrelated_cas_object_trap(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    schema_obj = store.put_bytes(MINIMAL_SCHEMA)
    instance_obj = store.put_bytes(MINIMAL_INSTANCE)
    instance_uri = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000001/a.xml")
    # Bundle binds only the instance — schema exists in CAS but is not bound.
    art = BundleArtifact(
        logical_path="accession/a.xml",
        content=ContentObject(sha256=instance_obj.sha256, byte_size=instance_obj.byte_size),
        artifact_kind="attachment",
        required=True,
    )
    bundle = FilingBundle(
        filing=FilingIdentity(
            cik=validate_cik("1"),
            accession="0000000001-00-000001",
            form_type="10-K",
            filing_date=date(2024, 1, 1),
            accepted_at=None,
            report_period_end=None,
            primary_document="a.xml",
        ),
        payload_hash=compute_payload_hash([art]),
        artifacts=(art,),
        report_inputs=(InstanceReportInput(document_uris=(instance_uri,)),),
        uri_bindings=(
            UriBinding(
                document_uri=instance_uri,
                artifact_path="accession/a.xml",
                content_sha256=instance_obj.sha256,
            ),
        ),
    )
    assert store.exists(schema_obj.sha256)
    replay = validate_offline_replay(bundle, store)
    assert not replay.replay_faithful
