"""Domain records for offline document projection (no database ids)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

IssueSeverity = Literal["fatal", "warning", "info"]
DocumentBlockKind = Literal[
    "heading",
    "paragraph",
    "list",
    "list_item",
    "table",
    "footnote",
    "signature",
    "other",
]
SOURCE_LOCATOR_SCHEME = "html-xpath-v1"


@dataclass(frozen=True)
class DocumentIssueRecord:
    severity: IssueSeverity
    code: str
    message: str
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "context": dict(self.context),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DocumentIssueRecord:
        return cls(
            severity=raw["severity"],  # type: ignore[arg-type]
            code=str(raw["code"]),
            message=str(raw["message"]),
            context=dict(raw.get("context") or {}),
        )


@dataclass(frozen=True)
class DocumentBlockRecord:
    ordinal: int
    kind: DocumentBlockKind
    text: str | None
    source_locator_value: str
    parent_ordinal: int | None = None
    heading_level: int | None = None
    source_locator_scheme: str = SOURCE_LOCATOR_SCHEME

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("ordinal must be >= 0")
        if self.parent_ordinal is not None and self.parent_ordinal >= self.ordinal:
            raise ValueError("parent_ordinal must precede ordinal")
        if self.kind == "heading":
            if self.heading_level is None or not (1 <= self.heading_level <= 6):
                raise ValueError("heading blocks require heading_level 1..6")
        elif self.heading_level is not None:
            raise ValueError("non-heading blocks must have heading_level=None")
        if self.text is not None and self.text == "":
            raise ValueError("empty string text is forbidden; use NULL for structural blocks")
        if self.source_locator_scheme != SOURCE_LOCATOR_SCHEME:
            raise ValueError(f"unsupported locator scheme: {self.source_locator_scheme}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "parent_ordinal": self.parent_ordinal,
            "kind": self.kind,
            "text": self.text,
            "heading_level": self.heading_level,
            "source_locator_scheme": self.source_locator_scheme,
            "source_locator_value": self.source_locator_value,
        }


@dataclass(frozen=True)
class FilingSectionRecord:
    section_key: str
    start_block_ordinal: int
    end_block_ordinal_exclusive: int
    method: str
    confidence_score: int = 0

    def __post_init__(self) -> None:
        if not (0 <= self.start_block_ordinal < self.end_block_ordinal_exclusive):
            raise ValueError("invalid section range")
        if not (0 <= self.confidence_score <= 100):
            raise ValueError("confidence_score must be 0..100")

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_key": self.section_key,
            "start_block_ordinal": self.start_block_ordinal,
            "end_block_ordinal_exclusive": self.end_block_ordinal_exclusive,
            "method": self.method,
            "confidence_score": self.confidence_score,
        }


@dataclass(frozen=True)
class SectionSignal:
    """Ephemeral DOM cues for section scoring; not persisted."""

    block_ordinal: int
    source_xpath: str
    tag: str
    heading_level: int | None
    is_bold_like: bool
    anchor_id: str | None
    internal_link_count: int
    link_text_chars: int
    total_text_chars: int
    normalized_candidate_text: str


@dataclass(frozen=True)
class ParsedDocument:
    blocks: tuple[DocumentBlockRecord, ...]
    section_signals: tuple[SectionSignal, ...]
    issues: tuple[DocumentIssueRecord, ...]


@dataclass(frozen=True)
class ParsedDocumentData:
    """Persisted interpretation payload (no DB ids)."""

    parser_version: str
    config_fingerprint: str
    blocks: tuple[DocumentBlockRecord, ...]
    sections: tuple[FilingSectionRecord, ...]
    issues: tuple[DocumentIssueRecord, ...]

    def __post_init__(self) -> None:
        ordinals = [block.ordinal for block in self.blocks]
        if ordinals != list(range(len(ordinals))):
            raise ValueError("block ordinals must be contiguous from 0")
        block_count = len(self.blocks)
        for section in self.sections:
            if section.end_block_ordinal_exclusive > block_count:
                raise ValueError(
                    f"section {section.section_key} end exceeds block_count={block_count}"
                )


class DocumentParseError(RuntimeError):
    """Fatal document parse failure; caller records a failed attempt."""

    def __init__(self, message: str, *, issues: Sequence[DocumentIssueRecord]) -> None:
        super().__init__(message)
        self.issues = tuple(issues)


def stable_issue_context(issue: DocumentIssueRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in sorted(issue.context.items())
        if key not in {"message", "path", "workspace", "tmp"}
    }


def issue_equality_representation(issue: DocumentIssueRecord) -> dict[str, Any]:
    return {
        "severity": issue.severity,
        "code": issue.code,
        "context": stable_issue_context(issue),
    }


def document_equality_state(
    data: ParsedDocumentData,
    *,
    status: str,
    parser_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalized comparable projection state (multiplicity-preserving)."""
    issues = [issue_equality_representation(issue) for issue in data.issues]
    return {
        "status": status,
        "parser_config": dict(parser_config),
        "parser_version": data.parser_version,
        "config_fingerprint": data.config_fingerprint,
        "blocks": [block.to_dict() for block in data.blocks],
        "sections": [section.to_dict() for section in data.sections],
        "issues": issues,
    }
