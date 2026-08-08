"""Unit tests for CAS object store and bundle equality."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
    bundles_equivalent,
)
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.bundles import BundleRepository, BundleStorageError
from edgar.storage.objects import ObjectStore, SizeLimitExceeded


def test_object_store_put_and_reuse(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    first = store.put_bytes(b"hello")
    second = store.put_bytes(b"hello")
    assert first.sha256 == second.sha256
    assert store.open_bytes(first.sha256) == b"hello"


def test_object_store_collision(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    obj = store.put_bytes(b"hello")
    dest = store.path_for(obj.sha256)
    dest.write_bytes(b"HELLO!")
    with pytest.raises(ValueError, match="collision"):
        store.put_bytes(b"hello")


def test_object_store_stream_limit(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    with pytest.raises(SizeLimitExceeded):
        store.put_stream([b"abcd", b"efgh"], max_bytes=5)


def _sample_bundle(sha: str = "ab" * 32) -> FilingBundle:
    art = BundleArtifact(
        logical_path="accession/a.xml",
        content=ContentObject(sha256=sha, byte_size=1),
        artifact_kind="attachment",
        required=True,
    )
    filing = FilingIdentity(
        cik="0001065088",
        accession="0001065088-24-000036",
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        accepted_at=datetime(2024, 1, 2, tzinfo=UTC),
        report_period_end=date(2023, 12, 31),
        primary_document="a.htm",
    )
    return FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash([art]),
        artifacts=(art,),
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/a.xml",)),),
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/a.xml",
                artifact_path="accession/a.xml",
                content_sha256=sha,
            ),
        ),
    )


def test_same_payload_different_bindings_not_equivalent() -> None:
    left = _sample_bundle()
    right_art = left.artifacts[0]
    right = FilingBundle(
        filing=left.filing,
        payload_hash=left.payload_hash,
        artifacts=left.artifacts,
        report_inputs=left.report_inputs,
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/other.xml",
                artifact_path="accession/a.xml",
                content_sha256=right_art.content.sha256,
            ),
        ),
    )
    assert left.payload_hash == right.payload_hash
    assert not bundles_equivalent(left, right)


def test_bundle_publish_reuse(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    obj = store.put_bytes(b"x")
    bundle = _sample_bundle(obj.sha256)
    # Fix byte_size to match.
    art = BundleArtifact(
        logical_path="accession/a.xml",
        content=ContentObject(sha256=obj.sha256, byte_size=1),
        artifact_kind="attachment",
        required=True,
    )
    bundle = FilingBundle(
        filing=bundle.filing,
        payload_hash=compute_payload_hash([art]),
        artifacts=(art,),
        report_inputs=bundle.report_inputs,
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/a.xml",
                artifact_path="accession/a.xml",
                content_sha256=obj.sha256,
            ),
        ),
    )
    repo = BundleRepository(tmp_path, store)
    first = repo.publish(bundle)
    second = repo.publish(bundle)
    assert first.reused is False
    assert second.reused is True
    assert first.opaque_id == second.opaque_id


def test_corrupt_published_bundle_fails_closed(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    obj = store.put_bytes(b"x")
    art = BundleArtifact(
        logical_path="accession/a.xml",
        content=ContentObject(sha256=obj.sha256, byte_size=1),
        artifact_kind="attachment",
        required=True,
    )
    filing = FilingIdentity(
        cik="0001065088",
        accession="0001065088-24-000036",
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        accepted_at=None,
        report_period_end=None,
        primary_document="a.htm",
    )
    bundle = FilingBundle(
        filing=filing,
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
    repo = BundleRepository(tmp_path, store)
    published = repo.publish(bundle)
    (published.bundle_dir / "bundle.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(BundleStorageError, match="corrupt"):
        repo.list_published(filing.cik, filing.accession)
