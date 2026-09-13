"""Offline document block/section extraction for Phase 2B source snapshots.

Reuses Phase-1 HTML and section heuristics from ``edgar.parsing`` without
projection identity. Primary HTML documents get regulatory sections; other
eligible HTML attachments get blocks only (same Phase-1 rule).
"""

from __future__ import annotations

from edgar.domain.bundle import BundleArtifact, FilingBundle
from edgar.parsing.config import DOCUMENT_PROJECTION_VERSION
from edgar.parsing.html import parse_html_document
from edgar.parsing.records import DocumentBlockRecord as ParsedBlock
from edgar.parsing.records import DocumentIssueRecord as ParsedIssue
from edgar.parsing.records import (
    DocumentParseError,
)
from edgar.parsing.records import FilingSectionRecord as ParsedSection
from edgar.parsing.sections import extract_filing_sections
from edgar.storage.objects import ObjectStore
from edgar.xbrl.source_records import (
    DocumentBlockRecord,
    ExtractionIssueRecord,
    FilingSectionRecord,
)

__all__ = [
    "extract_documents_for_filing",
]


def _is_html_path(logical_path: str) -> bool:
    lower = logical_path.lower()
    return lower.endswith(".htm") or lower.endswith(".html")


def _eligible_html_artifacts(bundle: FilingBundle) -> list[tuple[BundleArtifact, bool]]:
    """Return (artifact, is_primary) for HTML primary/attachment documents.

    Order: primary first (if HTML), then other HTML attachments by logical_path.
    """
    primary_path = f"accession/{bundle.filing.primary_document}"
    selected: list[tuple[BundleArtifact, bool]] = []
    primary: BundleArtifact | None = None
    attachments: list[BundleArtifact] = []
    for artifact in bundle.artifacts:
        if artifact.artifact_kind not in {"primary_document", "attachment"}:
            continue
        if not _is_html_path(artifact.logical_path):
            continue
        if artifact.logical_path == primary_path and artifact.artifact_kind == "primary_document":
            primary = artifact
        else:
            attachments.append(artifact)
    if primary is not None:
        selected.append((primary, True))
    for artifact in sorted(attachments, key=lambda a: a.logical_path):
        selected.append((artifact, False))
    return selected


def _adapt_block(
    block: ParsedBlock,
    *,
    document_relative_path: str,
) -> DocumentBlockRecord:
    return DocumentBlockRecord(
        document_relative_path=document_relative_path,
        ordinal=block.ordinal,
        block_type=block.kind,
        text=block.text,
        parent_ordinal=block.parent_ordinal,
        heading_level=block.heading_level,
        source_locator={
            "scheme": block.source_locator_scheme,
            "value": block.source_locator_value,
        },
        parser_version=DOCUMENT_PROJECTION_VERSION,
    )


def _adapt_section(
    section: ParsedSection,
    *,
    document_relative_path: str,
) -> FilingSectionRecord:
    return FilingSectionRecord(
        document_relative_path=document_relative_path,
        section_key=section.section_key,
        start_block_ordinal=section.start_block_ordinal,
        end_block_ordinal_exclusive=section.end_block_ordinal_exclusive,
        method=section.method,
        confidence_score=section.confidence_score,
    )


def _adapt_issue(
    issue: ParsedIssue,
    *,
    document_relative_path: str | None,
) -> ExtractionIssueRecord:
    return ExtractionIssueRecord(
        component="document",
        code=issue.code,
        severity=issue.severity,
        message=issue.message,
        details=dict(issue.context),
        source_document_relative_path=document_relative_path,
    )


def extract_documents_for_filing(
    bundle: FilingBundle,
    store: ObjectStore,
) -> tuple[
    tuple[DocumentBlockRecord, ...],
    tuple[FilingSectionRecord, ...],
    tuple[ExtractionIssueRecord, ...],
]:
    """Parse eligible HTML documents into source DTOs.

    Raises ``DocumentParseError`` on fatal HTML parse failure (caller must not
    replace the prior extraction snapshot).
    """
    blocks: list[DocumentBlockRecord] = []
    sections: list[FilingSectionRecord] = []
    issues: list[ExtractionIssueRecord] = []

    for artifact, is_primary in _eligible_html_artifacts(bundle):
        path = artifact.logical_path
        html_bytes = store.open_bytes(artifact.content.sha256)
        try:
            parsed = parse_html_document(html_bytes)
        except DocumentParseError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalize unexpected parse failures
            raise DocumentParseError(
                f"document parse failed for {path}: {exc}",
                issues=(
                    ParsedIssue(
                        severity="fatal",
                        code="DOCUMENT_PARSE_FAILED",
                        message=str(exc),
                        context={"document_relative_path": path},
                    ),
                ),
            ) from exc

        for block in parsed.blocks:
            blocks.append(_adapt_block(block, document_relative_path=path))
        for issue in parsed.issues:
            issues.append(_adapt_issue(issue, document_relative_path=path))

        parsed_sections, section_issues, _status, _terminal = extract_filing_sections(
            parsed,
            form_type=bundle.filing.form_type,
            extract_regulatory_sections=is_primary,
        )
        for section in parsed_sections:
            sections.append(_adapt_section(section, document_relative_path=path))
        for issue in section_issues:
            issues.append(_adapt_issue(issue, document_relative_path=path))

    return tuple(blocks), tuple(sections), tuple(issues)
