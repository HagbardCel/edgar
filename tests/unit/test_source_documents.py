"""Unit tests for Phase 2B document extraction into source DTOs."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.ingestion.payload import compute_payload_hash
from edgar.parsing.config import DOCUMENT_PROJECTION_VERSION
from edgar.storage.objects import ObjectStore
from edgar.xbrl.source_documents import extract_documents_for_filing
from tests.helpers.document_fixtures import RICH_10K_HTML


def _html_bundle(store: ObjectStore, *, exhibit: bytes | None = None) -> FilingBundle:
    primary = store.put_bytes(RICH_10K_HTML)
    artifacts: list[BundleArtifact] = [
        BundleArtifact(
            logical_path="accession/primary.htm",
            content=ContentObject(sha256=primary.sha256, byte_size=primary.byte_size),
            artifact_kind="primary_document",
            required=True,
        )
    ]
    bindings: list[UriBinding] = [
        UriBinding(
            document_uri="https://example.com/primary.htm",
            artifact_path="accession/primary.htm",
            content_sha256=primary.sha256,
        )
    ]
    if exhibit is not None:
        exh = store.put_bytes(exhibit)
        artifacts.append(
            BundleArtifact(
                logical_path="accession/exhibit.htm",
                content=ContentObject(sha256=exh.sha256, byte_size=exh.byte_size),
                artifact_kind="attachment",
                required=True,
            )
        )
        bindings.append(
            UriBinding(
                document_uri="https://example.com/exhibit.htm",
                artifact_path="accession/exhibit.htm",
                content_sha256=exh.sha256,
            )
        )
    filing = FilingIdentity(
        cik="0001065088",
        accession="0001065088-24-000036",
        form_type="10-K",
        filing_date=date(2024, 2, 28),
        accepted_at=None,
        report_period_end=date(2023, 12, 31),
        primary_document="primary.htm",
    )
    artifact_tuple = tuple(artifacts)
    return FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash(artifact_tuple),
        artifacts=artifact_tuple,
        report_inputs=(InstanceReportInput(document_uris=(bindings[0].document_uri,)),),
        uri_bindings=tuple(bindings),
    )


def test_extract_documents_primary_blocks_and_sections(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    bundle = _html_bundle(store)
    blocks, sections, issues = extract_documents_for_filing(bundle, store)
    assert blocks
    assert all(b.document_relative_path == "accession/primary.htm" for b in blocks)
    assert all(b.parser_version == DOCUMENT_PROJECTION_VERSION for b in blocks)
    assert all(b.source_locator["scheme"] == "html-xpath-v1" for b in blocks)
    assert all(
        isinstance(b.source_locator["value"], str) and b.source_locator["value"] for b in blocks
    )
    headings = [b for b in blocks if b.block_type == "heading"]
    assert headings
    assert all(b.heading_level is not None for b in headings)
    assert sections
    assert all(s.document_relative_path == "accession/primary.htm" for s in sections)
    assert any("item_1" in s.section_key for s in sections)
    assert all(0 <= s.confidence_score <= 100 for s in sections)
    assert all(i.component == "document" for i in issues)


def test_extract_documents_attachment_blocks_without_sections(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    exhibit = b"<html><body><p>Exhibit only.</p></body></html>"
    bundle = _html_bundle(store, exhibit=exhibit)
    blocks, sections, _issues = extract_documents_for_filing(bundle, store)
    primary_blocks = [b for b in blocks if b.document_relative_path == "accession/primary.htm"]
    exhibit_blocks = [b for b in blocks if b.document_relative_path == "accession/exhibit.htm"]
    assert primary_blocks
    assert exhibit_blocks
    assert all(s.document_relative_path == "accession/primary.htm" for s in sections)
    assert not any(s.document_relative_path == "accession/exhibit.htm" for s in sections)
