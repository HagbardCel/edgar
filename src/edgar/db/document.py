"""SQL adapter: persist and reconstruct document projections (caller owns the transaction)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from edgar.db import schema as tables
from edgar.parsing.config import DOCUMENT_CONFIG_SCHEMA
from edgar.parsing.records import (
    DocumentBlockRecord,
    DocumentIssueRecord,
    DocumentProjectionData,
    FilingSectionRecord,
    document_projection_equality_state,
)


class DocumentProjectionConflict(RuntimeError):
    """Persisted document state conflicts with the incoming projection."""


@dataclass(frozen=True)
class DocumentProjectionResult:
    projection_id: int
    attempt_id: int
    status: str
    reused: bool
    counts: dict[str, int]


@dataclass(frozen=True)
class DocumentFailureResult:
    attempt_id: int
    status: str = "failed"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _verify_fingerprint(config: Mapping[str, Any], fingerprint: str) -> None:
    envelope = {"config": dict(config), "schema": DOCUMENT_CONFIG_SCHEMA}
    digest = hashlib.sha256(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    if digest != fingerprint:
        raise DocumentProjectionConflict(
            "parser_config fingerprint does not match canonicalize(parser_config)"
        )


def _issue_kind(issue: DocumentIssueRecord) -> str:
    code = issue.code
    if code in {
        "HTML_PARSE_FAILED",
        "DOCUMENT_NO_MEANINGFUL_BLOCKS",
        "DOCUMENT_PROJECTION_CONFLICT",
    }:
        return "fatal"
    if code.startswith("SECTION_"):
        return "section"
    return "extraction"


def ensure_filing_document(conn: Connection, bundle_artifact_id: int) -> int:
    """Return filing_document.id for the artifact, inserting if needed."""
    existing = conn.execute(
        select(tables.filing_document.c.id).where(
            tables.filing_document.c.bundle_artifact_id == bundle_artifact_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        return int(existing)
    return int(
        conn.execute(
            insert(tables.filing_document)
            .values(bundle_artifact_id=bundle_artifact_id)
            .returning(tables.filing_document.c.id)
        ).scalar_one()
    )


def record_document_projection_failure(
    conn: Connection,
    *,
    filing_document_id: int,
    parser_version: str,
    parser_config: Mapping[str, Any],
    config_fingerprint: str,
    started_at: datetime,
    completed_at: datetime,
    issues: Sequence[DocumentIssueRecord] | Sequence[Mapping[str, Any]],
) -> DocumentFailureResult:
    """Persist a failed attempt and attempt-scoped issues. No projection rows."""
    _verify_fingerprint(parser_config, config_fingerprint)
    attempt_id = int(
        conn.execute(
            insert(tables.document_projection_attempt)
            .values(
                filing_document_id=filing_document_id,
                parser_version=parser_version,
                parser_config_fingerprint=config_fingerprint,
                parser_config=dict(parser_config),
                started_at=started_at,
                completed_at=completed_at,
                status="failed",
                document_projection_id=None,
            )
            .returning(tables.document_projection_attempt.c.id)
        ).scalar_one()
    )
    parsed_issues: list[DocumentIssueRecord] = []
    for raw in issues:
        if isinstance(raw, DocumentIssueRecord):
            parsed_issues.append(raw)
        else:
            parsed_issues.append(DocumentIssueRecord.from_dict(dict(raw)))
    if parsed_issues:
        conn.execute(
            insert(tables.document_issue),
            [
                {
                    "document_projection_id": None,
                    "document_projection_attempt_id": attempt_id,
                    "kind": _issue_kind(issue),
                    "severity": issue.severity,
                    "code": issue.code,
                    "message": issue.message,
                    "context": dict(issue.context),
                }
                for issue in parsed_issues
            ],
        )
    return DocumentFailureResult(attempt_id=attempt_id)


def _select_projection_id(
    conn: Connection,
    *,
    filing_document_id: int,
    parser_version: str,
    fingerprint: str,
) -> int | None:
    row = conn.execute(
        select(tables.document_projection.c.id)
        .where(tables.document_projection.c.filing_document_id == filing_document_id)
        .where(tables.document_projection.c.parser_version == parser_version)
        .where(tables.document_projection.c.parser_config_fingerprint == fingerprint)
    ).scalar_one_or_none()
    return int(row) if row is not None else None


def load_document_projection(
    conn: Connection,
    projection_id: int,
) -> tuple[DocumentProjectionData, str]:
    """Load projection data and status."""
    row = (
        conn.execute(
            select(
                tables.document_projection.c.parser_version,
                tables.document_projection.c.parser_config_fingerprint,
                tables.document_projection.c.parser_config,
                tables.document_projection.c.status,
            ).where(tables.document_projection.c.id == projection_id)
        )
        .mappings()
        .one()
    )
    fingerprint = str(row["parser_config_fingerprint"])
    config = dict(row["parser_config"])
    _verify_fingerprint(config, fingerprint)

    block_rows = (
        conn.execute(
            select(tables.document_block)
            .where(tables.document_block.c.document_projection_id == projection_id)
            .order_by(tables.document_block.c.ordinal)
        )
        .mappings()
        .all()
    )
    blocks = tuple(
        DocumentBlockRecord(
            ordinal=int(r["ordinal"]),
            parent_ordinal=None if r["parent_ordinal"] is None else int(r["parent_ordinal"]),
            kind=r["kind"],  # type: ignore[arg-type]
            text=r["text"],
            heading_level=None if r["heading_level"] is None else int(r["heading_level"]),
            source_locator_scheme=str(r["source_locator_scheme"]),
            source_locator_value=r["source_locator_value"]
            if isinstance(r["source_locator_value"], str)
            else str(r["source_locator_value"]),
        )
        for r in block_rows
    )

    section_rows = (
        conn.execute(
            select(tables.filing_section)
            .where(tables.filing_section.c.document_projection_id == projection_id)
            .order_by(
                tables.filing_section.c.start_block_ordinal, tables.filing_section.c.section_key
            )
        )
        .mappings()
        .all()
    )
    sections = tuple(
        FilingSectionRecord(
            section_key=str(r["section_key"]),
            start_block_ordinal=int(r["start_block_ordinal"]),
            end_block_ordinal_exclusive=int(r["end_block_ordinal_exclusive"]),
            method=str(r["method"]),
            confidence_score=int(r["confidence_score"]),
        )
        for r in section_rows
    )

    issue_rows = (
        conn.execute(
            select(tables.document_issue)
            .where(tables.document_issue.c.document_projection_id == projection_id)
            .order_by(tables.document_issue.c.id)
        )
        .mappings()
        .all()
    )
    issues = tuple(
        DocumentIssueRecord(
            severity=r["severity"],  # type: ignore[arg-type]
            code=str(r["code"]),
            message=str(r["message"]),
            context=dict(r["context"] or {}),
        )
        for r in issue_rows
    )

    data = DocumentProjectionData(
        parser_version=str(row["parser_version"]),
        config_fingerprint=fingerprint,
        blocks=blocks,
        sections=sections,
        issues=issues,
    )
    return data, str(row["status"])


def list_document_sections(conn: Connection, projection_id: int) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            select(tables.filing_section)
            .where(tables.filing_section.c.document_projection_id == projection_id)
            .order_by(
                tables.filing_section.c.start_block_ordinal, tables.filing_section.c.section_key
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "section_key": str(r["section_key"]),
            "start_block_ordinal": int(r["start_block_ordinal"]),
            "end_block_ordinal_exclusive": int(r["end_block_ordinal_exclusive"]),
            "method": str(r["method"]),
            "confidence_score": int(r["confidence_score"]),
        }
        for r in rows
    ]


def _insert_projection_tree(
    conn: Connection,
    *,
    projection_id: int,
    data: DocumentProjectionData,
) -> None:
    block_count = len(data.blocks)
    for section in data.sections:
        if section.end_block_ordinal_exclusive > block_count:
            raise DocumentProjectionConflict(
                "section end "
                f"{section.end_block_ordinal_exclusive} exceeds block_count {block_count}"
            )
    if data.blocks:
        conn.execute(
            insert(tables.document_block),
            [
                {
                    "document_projection_id": projection_id,
                    "ordinal": block.ordinal,
                    "parent_ordinal": block.parent_ordinal,
                    "kind": block.kind,
                    "text": block.text,
                    "heading_level": block.heading_level,
                    "source_locator_scheme": block.source_locator_scheme,
                    "source_locator_value": block.source_locator_value,
                }
                for block in data.blocks
            ],
        )
    if data.sections:
        conn.execute(
            insert(tables.filing_section),
            [
                {
                    "document_projection_id": projection_id,
                    "section_key": section.section_key,
                    "start_block_ordinal": section.start_block_ordinal,
                    "end_block_ordinal_exclusive": section.end_block_ordinal_exclusive,
                    "method": section.method,
                    "confidence_score": section.confidence_score,
                }
                for section in data.sections
            ],
        )
    if data.issues:
        conn.execute(
            insert(tables.document_issue),
            [
                {
                    "document_projection_id": projection_id,
                    "document_projection_attempt_id": None,
                    "kind": _issue_kind(issue),
                    "severity": issue.severity,
                    "code": issue.code,
                    "message": issue.message,
                    "context": dict(issue.context),
                }
                for issue in data.issues
            ],
        )


def catalog_document_projection(
    conn: Connection,
    *,
    filing_document_id: int,
    projection_data: DocumentProjectionData,
    status: str,
    parser_config: Mapping[str, Any],
    started_at: datetime,
    completed_at: datetime,
) -> DocumentProjectionResult:
    """Insert or verified-reuse one document projection; record a completed attempt."""
    if status not in {"complete", "incomplete"}:
        raise ValueError(f"invalid projection status: {status!r}")
    fingerprint = projection_data.config_fingerprint
    _verify_fingerprint(parser_config, fingerprint)
    if projection_data.parser_version != str(parser_config.get("parser_version", "")):
        # Allow parser_version field alignment with config.
        pass

    existing_id = _select_projection_id(
        conn,
        filing_document_id=filing_document_id,
        parser_version=projection_data.parser_version,
        fingerprint=fingerprint,
    )
    if existing_id is not None:
        loaded, loaded_status = load_document_projection(conn, existing_id)
        incoming = document_projection_equality_state(
            projection_data, status=status, parser_config=parser_config
        )
        loaded_config = conn.execute(
            select(tables.document_projection.c.parser_config).where(
                tables.document_projection.c.id == existing_id
            )
        ).scalar_one()
        existing_state = document_projection_equality_state(
            loaded, status=loaded_status, parser_config=dict(loaded_config)
        )
        if incoming != existing_state:
            raise DocumentProjectionConflict(
                "existing document projection state does not match incoming projection"
            )
        attempt_id = int(
            conn.execute(
                insert(tables.document_projection_attempt)
                .values(
                    filing_document_id=filing_document_id,
                    parser_version=projection_data.parser_version,
                    parser_config_fingerprint=fingerprint,
                    parser_config=dict(parser_config),
                    started_at=started_at,
                    completed_at=completed_at,
                    status="completed",
                    document_projection_id=existing_id,
                )
                .returning(tables.document_projection_attempt.c.id)
            ).scalar_one()
        )
        return DocumentProjectionResult(
            projection_id=existing_id,
            attempt_id=attempt_id,
            status=loaded_status,
            reused=True,
            counts={
                "blocks": len(loaded.blocks),
                "sections": len(loaded.sections),
                "issues": len(loaded.issues),
            },
        )

    projection_id = int(
        conn.execute(
            insert(tables.document_projection)
            .values(
                filing_document_id=filing_document_id,
                parser_version=projection_data.parser_version,
                parser_config_fingerprint=fingerprint,
                parser_config=dict(parser_config),
                status=status,
                created_at=_utcnow(),
            )
            .returning(tables.document_projection.c.id)
        ).scalar_one()
    )
    _insert_projection_tree(conn, projection_id=projection_id, data=projection_data)
    attempt_id = int(
        conn.execute(
            insert(tables.document_projection_attempt)
            .values(
                filing_document_id=filing_document_id,
                parser_version=projection_data.parser_version,
                parser_config_fingerprint=fingerprint,
                parser_config=dict(parser_config),
                started_at=started_at,
                completed_at=completed_at,
                status="completed",
                document_projection_id=projection_id,
            )
            .returning(tables.document_projection_attempt.c.id)
        ).scalar_one()
    )
    # Validate completed attempt identity matches projection.
    proj_row = (
        conn.execute(
            select(
                tables.document_projection.c.filing_document_id,
                tables.document_projection.c.parser_version,
                tables.document_projection.c.parser_config_fingerprint,
            ).where(tables.document_projection.c.id == projection_id)
        )
        .mappings()
        .one()
    )
    if (
        int(proj_row["filing_document_id"]) != filing_document_id
        or str(proj_row["parser_version"]) != projection_data.parser_version
        or str(proj_row["parser_config_fingerprint"]) != fingerprint
    ):
        raise DocumentProjectionConflict("completed attempt/projection identity mismatch")

    return DocumentProjectionResult(
        projection_id=projection_id,
        attempt_id=attempt_id,
        status=status,
        reused=False,
        counts={
            "blocks": len(projection_data.blocks),
            "sections": len(projection_data.sections),
            "issues": len(projection_data.issues),
        },
    )


__all__ = [
    "DocumentFailureResult",
    "DocumentProjectionConflict",
    "DocumentProjectionResult",
    "catalog_document_projection",
    "ensure_filing_document",
    "list_document_sections",
    "load_document_projection",
    "record_document_projection_failure",
]
