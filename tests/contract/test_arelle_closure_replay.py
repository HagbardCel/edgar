"""Contract tests for Arelle worker isolation and closure/replay."""

from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    IxdsReportInput,
    UriBinding,
)
from edgar.domain.identifiers import sanitize_basename, validate_cik
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.objects import ObjectStore
from edgar.xbrl.closure import run_online_closure
from edgar.xbrl.network_guard import NetworkDeniedError, NetworkGuard, deny_inet_sockets
from edgar.xbrl.replay import validate_offline_replay
from edgar.xbrl.uri import normalize_uri, sha256_of_uri

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

INLINE_XSD = b"""<?xml version="1.0"?>
<schema xmlns="http://www.w3.org/2001/XMLSchema"
        targetNamespace="http://www.xbrl.org/2013/inlineXBRL"
        elementFormDefault="qualified"/>
"""

INLINE_A = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:link="http://www.xbrl.org/2003/linkbase"
      xmlns:xlink="http://www.w3.org/1999/xlink"
      xmlns:t="http://example.com/test">
  <body>
    <ix:header>
      <ix:references>
        <link:schemaRef xlink:type="simple" xlink:href="https://example.com/test.xsd"/>
      </ix:references>
      <ix:resources>
        <xbrli:context id="c1">
          <xbrli:entity>
            <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
          </xbrli:entity>
          <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
        </xbrli:context>
      </ix:resources>
    </ix:header>
    <ix:nonNumeric name="t:Assets" contextRef="c1">1</ix:nonNumeric>
  </body>
</html>
"""

INLINE_B = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:t="http://example.com/test">
  <body>
    <ix:nonNumeric name="t:Assets" contextRef="c1">2</ix:nonNumeric>
  </body>
</html>
"""

SCHEMA_URI = normalize_uri("https://example.com/test.xsd")
INLINE_SCHEMA_URI = normalize_uri("http://www.xbrl.org/2013/inlineXBRL/xhtml-inlinexbrl-1_1.xsd")
INSTANCE_URI = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000001/a.xml")
INLINE_A_URI = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000001/a.htm")
INLINE_B_URI = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000001/b.htm")

# Relative external import must resolve against the parent's canonical HTTP(S) base.
PARENT_URI = normalize_uri("https://example.com/taxonomy/parent.xsd")
CHILD_URI = normalize_uri("https://example.com/taxonomy/child.xsd")

CHILD_SCHEMA = b"""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="urn:test:child"
           elementFormDefault="qualified">
  <xs:element name="Assets" type="xs:string"/>
</xs:schema>
"""

PARENT_SCHEMA = b"""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="urn:test:parent"
           elementFormDefault="qualified">
  <xs:import namespace="urn:test:child" schemaLocation="child.xsd"/>
</xs:schema>
"""

RELATIVE_IMPORT_INSTANCE = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:c="urn:test:child">
  <link:schemaRef xlink:type="simple" xlink:href="https://example.com/taxonomy/parent.xsd"/>
  <xbrli:context id="c1">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <c:Assets contextRef="c1">1</c:Assets>
</xbrli:xbrl>
"""


class FakeFetcher:
    def __init__(self, mapping: dict[str, bytes]) -> None:
        self.mapping = {normalize_uri(k): v for k, v in mapping.items()}
        self.calls: list[str] = []

    def fetch_to_store(self, url, store, *, max_bytes: int):  # type: ignore[no-untyped-def]
        from edgar.sec.client import FetchHop, FetchResult, FetchTrace

        canonical = normalize_uri(url)
        self.calls.append(canonical)
        data = self.mapping[canonical]
        if len(data) > max_bytes:
            from edgar.storage.objects import SizeLimitExceeded

            raise SizeLimitExceeded(f"exceeded max_bytes={max_bytes}")
        obj = store.put_bytes(data)
        observed_at = datetime.now(UTC)
        trace = FetchTrace(
            requested_uri=url,
            hops=(
                FetchHop(
                    uri=canonical,
                    resolved_candidates=("1.2.3.4",),
                    pinned_ip="1.2.3.4",
                    peer_ip="1.2.3.4",
                    http_status=200,
                    error=None,
                    observed_at=observed_at,
                ),
            ),
            final_uri=canonical,
            content_sha256=obj.sha256,
            byte_size=obj.byte_size,
        )
        result = FetchResult(
            requested_uri=url,
            final_uri=canonical,
            status_code=200,
            headers={},
            redirect_count=0,
            sha256=obj.sha256,
            byte_size=obj.byte_size,
            pinned_ip="1.2.3.4",
            observed_at=observed_at,
            peer_ip="1.2.3.4",
            trace=trace,
        )
        return result, obj


def _filing(*, primary: str = "a.xml") -> FilingIdentity:
    return FilingIdentity(
        cik=validate_cik("1"),
        accession="0000000001-00-000001",
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        accepted_at=None,
        report_period_end=None,
        primary_document=primary,
    )


def _external_path(uri: str, basename: str) -> str:
    return f"external/{sha256_of_uri(uri)}/{sanitize_basename(basename)}"


def _bundle_from_discovery(
    *,
    store: ObjectStore,
    report: InstanceReportInput | IxdsReportInput,
    discovery: object,
    accession_artifacts: list[BundleArtifact],
    primary: str,
) -> FilingBundle:
    artifacts = list(accession_artifacts)
    for binding in discovery.uri_bindings:  # type: ignore[attr-defined]
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
    return FilingBundle(
        filing=_filing(primary=primary),
        payload_hash=compute_payload_hash(artifacts),
        artifacts=tuple(artifacts),
        report_inputs=(report,),
        uri_bindings=tuple(discovery.uri_bindings),  # type: ignore[attr-defined]
    )


def _online_gate_failed(discovery: object) -> bool:
    return bool(
        not discovery.load_completed  # type: ignore[attr-defined]
        or discovery.errors  # type: ignore[attr-defined]
        or discovery.network_attempts  # type: ignore[attr-defined]
        or discovery.unresolved_documents  # type: ignore[attr-defined]
    )


def test_network_guard_blocks_inet() -> None:
    guard = NetworkGuard()
    with deny_inet_sockets(guard), pytest.raises(NetworkDeniedError):
        socket.create_connection(("example.com", 80), timeout=0.1)
    assert guard.attempt_count >= 1


def test_online_closure_and_offline_replay(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    store.put_bytes(MINIMAL_SCHEMA)
    instance_obj = store.put_bytes(MINIMAL_INSTANCE)
    accession_map = {
        INSTANCE_URI: (instance_obj.sha256, "accession/a.xml"),
    }
    fetcher = FakeFetcher({SCHEMA_URI: MINIMAL_SCHEMA})
    report = InstanceReportInput(document_uris=(INSTANCE_URI,))
    discovery = run_online_closure(
        report,
        accession_uri_map=accession_map,
        store=store,
        fetcher=fetcher,  # type: ignore[arg-type]
        max_file_bytes=1_000_000,
        max_new_payload_bytes=1_000_000,
    )
    assert discovery.load_completed
    assert discovery.uri_bindings
    assert SCHEMA_URI in fetcher.calls

    artifacts = [
        BundleArtifact(
            logical_path="accession/a.xml",
            content=ContentObject(sha256=instance_obj.sha256, byte_size=instance_obj.byte_size),
            artifact_kind="attachment",
            required=True,
        ),
    ]
    bundle = _bundle_from_discovery(
        store=store,
        report=report,
        discovery=discovery,
        accession_artifacts=artifacts,
        primary="a.xml",
    )
    replay = validate_offline_replay(bundle, store)
    assert replay.replay_faithful, (replay.errors, replay.unresolved_documents, replay.diagnostics)


def test_relative_external_import_preserves_canonical_http_base(tmp_path: Path) -> None:
    """Relative schemaLocation must resolve against the parent's canonical HTTP(S) URI."""
    store = ObjectStore(tmp_path)
    instance_obj = store.put_bytes(RELATIVE_IMPORT_INSTANCE)
    fetcher = FakeFetcher({PARENT_URI: PARENT_SCHEMA, CHILD_URI: CHILD_SCHEMA})
    report = InstanceReportInput(document_uris=(INSTANCE_URI,))
    discovery = run_online_closure(
        report,
        accession_uri_map={INSTANCE_URI: (instance_obj.sha256, "accession/a.xml")},
        store=store,
        fetcher=fetcher,  # type: ignore[arg-type]
        max_file_bytes=1_000_000,
        max_new_payload_bytes=1_000_000,
    )
    assert discovery.load_completed
    assert not discovery.errors
    assert not discovery.unresolved_documents
    assert not discovery.network_attempts
    assert PARENT_URI in fetcher.calls
    assert CHILD_URI in fetcher.calls

    bound_uris = {b.document_uri for b in discovery.uri_bindings}
    resolved_uris = {d.document_uri for d in discovery.resolved_documents}
    assert PARENT_URI in bound_uris
    assert CHILD_URI in bound_uris
    assert PARENT_URI in resolved_uris
    assert CHILD_URI in resolved_uris
    assert not any(uri.startswith("file:") for uri in bound_uris | resolved_uris)

    bundle = _bundle_from_discovery(
        store=store,
        report=report,
        discovery=discovery,
        accession_artifacts=[
            BundleArtifact(
                logical_path="accession/a.xml",
                content=ContentObject(sha256=instance_obj.sha256, byte_size=instance_obj.byte_size),
                artifact_kind="attachment",
                required=True,
            ),
        ],
        primary="a.xml",
    )
    replay = validate_offline_replay(bundle, store)
    assert replay.closure_equal is True
    assert replay.replay_faithful is True, (
        replay.errors,
        replay.unresolved_documents,
        replay.diagnostics,
    )
    replay_uris = {d.document_uri for d in replay.resolved_documents}
    assert CHILD_URI in replay_uris
    assert not any(uri.startswith("file:") for uri in replay_uris)


def test_single_doc_ixbrl_default_target(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    inline_obj = store.put_bytes(INLINE_A)
    report = IxdsReportInput(document_uris=(INLINE_A_URI,), target="default")
    fetcher = FakeFetcher({SCHEMA_URI: MINIMAL_SCHEMA, INLINE_SCHEMA_URI: INLINE_XSD})
    discovery = run_online_closure(
        report,
        accession_uri_map={INLINE_A_URI: (inline_obj.sha256, "accession/a.htm")},
        store=store,
        fetcher=fetcher,  # type: ignore[arg-type]
        max_file_bytes=1_000_000,
        max_new_payload_bytes=1_000_000,
    )
    assert discovery.load_completed
    assert not discovery.unresolved_documents
    bundle = _bundle_from_discovery(
        store=store,
        report=report,
        discovery=discovery,
        accession_artifacts=[
            BundleArtifact(
                logical_path="accession/a.htm",
                content=ContentObject(inline_obj.sha256, inline_obj.byte_size),
                artifact_kind="attachment",
                required=True,
            )
        ],
        primary="a.htm",
    )
    replay = validate_offline_replay(bundle, store)
    assert replay.replay_faithful, (replay.errors, replay.unresolved_documents, replay.diagnostics)


def test_multi_doc_ixds_report_input_order_and_load(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    a_obj = store.put_bytes(INLINE_A)
    b_obj = store.put_bytes(INLINE_B)
    report = IxdsReportInput(document_uris=(INLINE_A_URI, INLINE_B_URI), target="default")
    assert report.document_uris == (INLINE_A_URI, INLINE_B_URI)
    fetcher = FakeFetcher({SCHEMA_URI: MINIMAL_SCHEMA, INLINE_SCHEMA_URI: INLINE_XSD})
    discovery = run_online_closure(
        report,
        accession_uri_map={
            INLINE_A_URI: (a_obj.sha256, "accession/a.htm"),
            INLINE_B_URI: (b_obj.sha256, "accession/b.htm"),
        },
        store=store,
        fetcher=fetcher,  # type: ignore[arg-type]
        max_file_bytes=1_000_000,
        max_new_payload_bytes=1_000_000,
    )
    assert discovery.load_completed
    assert not discovery.unresolved_documents
    resolved = {d.document_uri for d in discovery.resolved_documents}
    assert INLINE_A_URI in resolved
    assert INLINE_B_URI in resolved
    bundle = _bundle_from_discovery(
        store=store,
        report=report,
        discovery=discovery,
        accession_artifacts=[
            BundleArtifact(
                "accession/a.htm",
                ContentObject(a_obj.sha256, a_obj.byte_size),
                "attachment",
                True,
            ),
            BundleArtifact(
                "accession/b.htm",
                ContentObject(b_obj.sha256, b_obj.byte_size),
                "attachment",
                True,
            ),
        ],
        primary="a.htm",
    )
    assert bundle.report_inputs[0].document_uris == (INLINE_A_URI, INLINE_B_URI)
    replay = validate_offline_replay(bundle, store)
    assert replay.replay_faithful, (replay.errors, replay.unresolved_documents, replay.diagnostics)
    replay_resolved = {d.document_uri for d in replay.resolved_documents}
    assert INLINE_A_URI in replay_resolved
    assert INLINE_B_URI in replay_resolved


def test_ambient_web_cache_trap_ignored(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "cas")
    schema_obj = store.put_bytes(MINIMAL_SCHEMA)
    instance_obj = store.put_bytes(MINIMAL_INSTANCE)
    ext = _external_path(SCHEMA_URI, "test.xsd")
    artifacts = [
        BundleArtifact(
            "accession/a.xml",
            ContentObject(instance_obj.sha256, instance_obj.byte_size),
            "attachment",
            True,
        ),
        BundleArtifact(
            ext, ContentObject(schema_obj.sha256, schema_obj.byte_size), "external", True
        ),
    ]
    bundle = FilingBundle(
        filing=_filing(),
        payload_hash=compute_payload_hash(artifacts),
        artifacts=tuple(artifacts),
        report_inputs=(InstanceReportInput(document_uris=(INSTANCE_URI,)),),
        uri_bindings=(
            UriBinding(INSTANCE_URI, "accession/a.xml", instance_obj.sha256),
            UriBinding(SCHEMA_URI, ext, schema_obj.sha256),
        ),
    )

    ambient = tmp_path / "ambient-xdg"
    cache_file = ambient / "arelle" / "cache" / "https" / "example.com" / "test.xsd"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"POISON-AMBIENT-WEB-CACHE")
    prior = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = str(ambient)
    try:
        replay = validate_offline_replay(bundle, store)
    finally:
        if prior is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = prior
    assert replay.replay_faithful, (replay.errors, replay.unresolved_documents, replay.diagnostics)
    schema_digests = {
        d.content_sha256 for d in replay.resolved_documents if d.document_uri == SCHEMA_URI
    }
    assert schema_digests == {schema_obj.sha256}
    assert hashlib.sha256(b"POISON-AMBIENT-WEB-CACHE").hexdigest() not in schema_digests


def test_ambient_catalog_trap_ignored(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "cas")
    schema_obj = store.put_bytes(MINIMAL_SCHEMA)
    instance_obj = store.put_bytes(MINIMAL_INSTANCE)
    ext = _external_path(SCHEMA_URI, "test.xsd")
    artifacts = [
        BundleArtifact(
            "accession/a.xml",
            ContentObject(instance_obj.sha256, instance_obj.byte_size),
            "attachment",
            True,
        ),
        BundleArtifact(
            ext, ContentObject(schema_obj.sha256, schema_obj.byte_size), "external", True
        ),
    ]
    bundle = FilingBundle(
        filing=_filing(),
        payload_hash=compute_payload_hash(artifacts),
        artifacts=tuple(artifacts),
        report_inputs=(InstanceReportInput(document_uris=(INSTANCE_URI,)),),
        uri_bindings=(
            UriBinding(INSTANCE_URI, "accession/a.xml", instance_obj.sha256),
            UriBinding(SCHEMA_URI, ext, schema_obj.sha256),
        ),
    )

    poison = tmp_path / "poison.xsd"
    poison.write_bytes(b"POISON-CATALOG-SCHEMA")
    catalog = tmp_path / "poison-catalog.xml"
    catalog.write_text(
        '<?xml version="1.0"?>\n'
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        f'  <uri name="{SCHEMA_URI}" uri="{poison.resolve().as_uri()}"/>\n'
        "</catalog>\n",
        encoding="utf-8",
    )
    prior = os.environ.get("XML_CATALOG_FILES")
    os.environ["XML_CATALOG_FILES"] = str(catalog.resolve())
    try:
        replay = validate_offline_replay(bundle, store)
    finally:
        if prior is None:
            os.environ.pop("XML_CATALOG_FILES", None)
        else:
            os.environ["XML_CATALOG_FILES"] = prior
    assert replay.replay_faithful, (replay.errors, replay.unresolved_documents, replay.diagnostics)
    schema_digests = {
        d.content_sha256 for d in replay.resolved_documents if d.document_uri == SCHEMA_URI
    }
    assert schema_digests == {schema_obj.sha256}


def test_ambient_taxonomy_package_trap_ignored(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "cas")
    schema_obj = store.put_bytes(MINIMAL_SCHEMA)
    instance_obj = store.put_bytes(MINIMAL_INSTANCE)
    ext = _external_path(SCHEMA_URI, "test.xsd")
    artifacts = [
        BundleArtifact(
            "accession/a.xml",
            ContentObject(instance_obj.sha256, instance_obj.byte_size),
            "attachment",
            True,
        ),
        BundleArtifact(
            ext, ContentObject(schema_obj.sha256, schema_obj.byte_size), "external", True
        ),
    ]
    bundle = FilingBundle(
        filing=_filing(),
        payload_hash=compute_payload_hash(artifacts),
        artifacts=tuple(artifacts),
        report_inputs=(InstanceReportInput(document_uris=(INSTANCE_URI,)),),
        uri_bindings=(
            UriBinding(INSTANCE_URI, "accession/a.xml", instance_obj.sha256),
            UriBinding(SCHEMA_URI, ext, schema_obj.sha256),
        ),
    )

    ambient = tmp_path / "ambient-packages"
    arelle_dir = ambient / "arelle"
    arelle_dir.mkdir(parents=True)
    poison = arelle_dir / "poison.xsd"
    poison.write_bytes(b"POISON-PACKAGE-SCHEMA")
    (arelle_dir / "taxonomyPackages.json").write_text(
        json.dumps(
            {
                "packages": [],
                "remappings": {SCHEMA_URI: str(poison.resolve())},
            }
        ),
        encoding="utf-8",
    )
    prior = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = str(ambient)
    try:
        replay = validate_offline_replay(bundle, store)
    finally:
        if prior is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = prior
    assert replay.replay_faithful, (replay.errors, replay.unresolved_documents, replay.diagnostics)
    schema_digests = {
        d.content_sha256 for d in replay.resolved_documents if d.document_uri == SCHEMA_URI
    }
    assert schema_digests == {schema_obj.sha256}


def test_file_escape_blocked_and_fails_publication_gate(tmp_path: Path) -> None:
    outside = tmp_path / "outside.xsd"
    outside.write_bytes(b"POISON-OUTSIDE-FILE")
    instance = f"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:t="http://example.com/test">
  <link:schemaRef xlink:type="simple" xlink:href="{outside.resolve().as_uri()}"/>
  <xbrli:context id="c1">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <t:Assets contextRef="c1">1</t:Assets>
</xbrli:xbrl>
""".encode()
    store = ObjectStore(tmp_path / "cas")
    instance_obj = store.put_bytes(instance)
    poison_digest = hashlib.sha256(b"POISON-OUTSIDE-FILE").hexdigest()
    report = InstanceReportInput(document_uris=(INSTANCE_URI,))
    discovery = run_online_closure(
        report,
        accession_uri_map={INSTANCE_URI: (instance_obj.sha256, "accession/a.xml")},
        store=store,
        fetcher=FakeFetcher({}),  # type: ignore[arg-type]
        max_file_bytes=1_000_000,
        max_new_payload_bytes=1_000_000,
    )
    assert outside.read_bytes() == b"POISON-OUTSIDE-FILE"
    assert not store.exists(poison_digest)
    assert _online_gate_failed(discovery)

    artifacts = [
        BundleArtifact(
            "accession/a.xml",
            ContentObject(instance_obj.sha256, instance_obj.byte_size),
            "attachment",
            True,
        )
    ]
    bundle = FilingBundle(
        filing=_filing(),
        payload_hash=compute_payload_hash(artifacts),
        artifacts=tuple(artifacts),
        report_inputs=(report,),
        uri_bindings=(UriBinding(INSTANCE_URI, "accession/a.xml", instance_obj.sha256),),
    )
    replay = validate_offline_replay(bundle, store)
    assert replay.replay_faithful is False
    assert outside.read_bytes() == b"POISON-OUTSIDE-FILE"
    assert not store.exists(poison_digest)


def test_alias_normalized_closure_equality(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    primary = SCHEMA_URI
    alias = normalize_uri("https://example.com/alias.xsd")
    instance = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:t="http://example.com/test">
  <link:schemaRef xlink:type="simple" xlink:href="https://example.com/alias.xsd"/>
  <xbrli:context id="c1">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <t:Assets contextRef="c1">1</t:Assets>
</xbrli:xbrl>
"""
    schema_obj = store.put_bytes(MINIMAL_SCHEMA)
    instance_obj = store.put_bytes(instance)
    ext = _external_path(primary, "test.xsd")
    artifacts = [
        BundleArtifact(
            "accession/a.xml",
            ContentObject(instance_obj.sha256, instance_obj.byte_size),
            "attachment",
            True,
        ),
        BundleArtifact(
            ext, ContentObject(schema_obj.sha256, schema_obj.byte_size), "external", True
        ),
    ]
    bundle = FilingBundle(
        filing=_filing(),
        payload_hash=compute_payload_hash(artifacts),
        artifacts=tuple(artifacts),
        report_inputs=(InstanceReportInput(document_uris=(INSTANCE_URI,)),),
        uri_bindings=(
            UriBinding(INSTANCE_URI, "accession/a.xml", instance_obj.sha256),
            UriBinding(primary, ext, schema_obj.sha256, replay_aliases=(alias,)),
        ),
    )
    replay = validate_offline_replay(bundle, store)
    assert replay.closure_equal is True
    assert replay.replay_faithful is True
    observed = {d.document_uri for d in replay.resolved_documents}
    assert alias in observed


def test_unrelated_cas_object_trap(tmp_path: Path) -> None:
    """Unbound CAS bytes must not satisfy a schemaRef; partial bindings stay unequal.

    The schema object exists in CAS but is not bound. The instance still references
    it, so replay cannot resolve it. A second published binding names a document
    that is never loaded, producing ``closure_equal is False`` (partial closure).
    """
    store = ObjectStore(tmp_path)
    schema_obj = store.put_bytes(MINIMAL_SCHEMA)
    instance_obj = store.put_bytes(MINIMAL_INSTANCE)
    phantom_obj = store.put_bytes(b"partial-closure-phantom")
    phantom_uri = normalize_uri("https://example.com/phantom.xsd")
    phantom_path = _external_path(phantom_uri, "phantom.xsd")
    art = BundleArtifact(
        logical_path="accession/a.xml",
        content=ContentObject(sha256=instance_obj.sha256, byte_size=instance_obj.byte_size),
        artifact_kind="attachment",
        required=True,
    )
    phantom_art = BundleArtifact(
        logical_path=phantom_path,
        content=ContentObject(sha256=phantom_obj.sha256, byte_size=phantom_obj.byte_size),
        artifact_kind="external",
        required=True,
    )
    bundle = FilingBundle(
        filing=_filing(),
        payload_hash=compute_payload_hash([art, phantom_art]),
        artifacts=(art, phantom_art),
        report_inputs=(InstanceReportInput(document_uris=(INSTANCE_URI,)),),
        uri_bindings=(
            UriBinding(
                document_uri=INSTANCE_URI,
                artifact_path="accession/a.xml",
                content_sha256=instance_obj.sha256,
            ),
            UriBinding(
                document_uri=phantom_uri,
                artifact_path=phantom_path,
                content_sha256=phantom_obj.sha256,
            ),
        ),
    )
    assert store.exists(schema_obj.sha256)
    replay = validate_offline_replay(bundle, store)
    assert replay.replay_faithful is False
    assert replay.closure_equal is False
    resolved_digests = {d.content_sha256 for d in replay.resolved_documents}
    assert schema_obj.sha256 not in resolved_digests
