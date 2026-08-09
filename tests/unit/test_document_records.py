"""Unit tests for document config and records."""

from __future__ import annotations

from edgar.parsing.config import (
    DOCUMENT_PROJECTION_VERSION,
    SECTION_EXTRACTOR_VERSION,
    build_document_config,
    document_config_fingerprint,
)
from edgar.parsing.records import (
    DocumentBlockRecord,
    DocumentIssueRecord,
    DocumentProjectionData,
    FilingSectionRecord,
    document_projection_equality_state,
)


def test_config_fingerprint_stable() -> None:
    a = build_document_config(lxml_version="5.0.0", libxml2_version="2.12.0")
    b = build_document_config(lxml_version="5.0.0", libxml2_version="2.12.0")
    assert document_config_fingerprint(a) == document_config_fingerprint(b)
    assert len(document_config_fingerprint(a)) == 64


def test_config_fingerprint_changes_with_runtime() -> None:
    a = build_document_config(lxml_version="5.0.0", libxml2_version="2.12.0")
    b = build_document_config(lxml_version="5.1.0", libxml2_version="2.12.0")
    assert document_config_fingerprint(a) != document_config_fingerprint(b)


def test_equality_excludes_issue_message() -> None:
    blocks = (
        DocumentBlockRecord(
            ordinal=0,
            kind="paragraph",
            text="Hello",
            source_locator_value="/html/body/p",
        ),
    )
    issues_a = (
        DocumentIssueRecord(
            severity="warning",
            code="SECTION_NOT_FOUND",
            message="wording A",
            context={"section_key": "part_1.item_1.business"},
        ),
    )
    issues_b = (
        DocumentIssueRecord(
            severity="warning",
            code="SECTION_NOT_FOUND",
            message="wording B",
            context={"section_key": "part_1.item_1.business"},
        ),
    )
    data_a = DocumentProjectionData(
        parser_version=DOCUMENT_PROJECTION_VERSION,
        config_fingerprint="a" * 64,
        blocks=blocks,
        sections=(),
        issues=issues_a,
    )
    data_b = DocumentProjectionData(
        parser_version=DOCUMENT_PROJECTION_VERSION,
        config_fingerprint="a" * 64,
        blocks=blocks,
        sections=(),
        issues=issues_b,
    )
    cfg = {"parser_version": DOCUMENT_PROJECTION_VERSION}
    assert document_projection_equality_state(
        data_a, status="complete", parser_config=cfg
    ) == document_projection_equality_state(data_b, status="complete", parser_config=cfg)


def test_section_range_validation() -> None:
    section = FilingSectionRecord(
        section_key="part_1.item_1.business",
        start_block_ordinal=0,
        end_block_ordinal_exclusive=2,
        method=SECTION_EXTRACTOR_VERSION,
        confidence_score=80,
    )
    assert section.end_block_ordinal_exclusive == 2
