"""Structured Arelle error capture and error policy (arelle-error-policy-v1).

A logging handler attached to the Arelle controller logger captures structured
records instead of parsing the rendered log buffer. Missing or unstructured
codes are represented explicitly as ``UNSTRUCTURED``; they never disappear.

Policy:
- allowlist empty by default
- every non-allowlisted error fails the run
- every non-allowlisted warning is reported, deterministic, and not silently
  fatal (raw warning text is excluded from semantic identity)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from spike_lib import ARELLE_ERROR_POLICY_VERSION

UNSTRUCTURED_CODE = "UNSTRUCTURED"


@dataclass(frozen=True)
class StructuredError:
    severity: str  # "error" | "warning"
    code: str
    document_uri: str | None
    source_line: int | None

    def key(self) -> tuple[str, str, str | None, int | None]:
        return (self.severity, self.code, self.document_uri, self.source_line)


@dataclass(eq=False)
class ErrorCapture(logging.Handler):
    """Logging handler that captures structured Arelle log records."""

    records: list[StructuredError] = field(default_factory=list)

    def __init__(self) -> None:
        logging.Handler.__init__(self)
        self.records = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        severity = "error" if record.levelno >= logging.ERROR else "warning"
        code = getattr(record, "messageCode", None) or UNSTRUCTURED_CODE
        if isinstance(code, (tuple, list)):
            code = ",".join(str(c) for c in code) or UNSTRUCTURED_CODE
        document_uri: str | None = None
        source_line: int | None = None
        refs = getattr(record, "refs", None) or []
        if isinstance(refs, list) and refs:
            first = refs[0] if isinstance(refs[0], dict) else {}
            href = first.get("href")
            if isinstance(href, str) and href:
                document_uri = href
            raw_line = first.get("sourceLine")
            if raw_line is not None:
                try:
                    source_line = int(raw_line)
                except (TypeError, ValueError):
                    source_line = None
        self.records.append(
            StructuredError(
                severity=severity,
                code=str(code),
                document_uri=document_uri,
                source_line=source_line,
            )
        )


def summarize_errors(
    records: list[StructuredError], *, allowed_codes: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Deterministic structured summary with explicit multiplicity."""
    error_counts: dict[tuple[str, str | None, int | None], int] = {}
    warning_counts: dict[tuple[str, str | None, int | None], int] = {}
    for record in records:
        bucket = error_counts if record.severity == "error" else warning_counts
        key = (record.code, record.document_uri, record.source_line)
        bucket[key] = bucket.get(key, 0) + 1

    def project(counts: dict[tuple[str, str | None, int | None], int]) -> list[dict[str, Any]]:
        return [
            {
                "code": code,
                "document_uri": doc_uri,
                "source_line": line,
                "count": counts[key],
            }
            for key in sorted(
                counts, key=lambda k: (k[0], k[1] or "", k[2] if k[2] is not None else -1)
            )
            for code, doc_uri, line in [key]
        ]

    errors = project(error_counts)
    warnings = project(warning_counts)
    unallowlisted_errors = [e for e in errors if e["code"] not in allowed_codes]
    unallowlisted_warnings = [w for w in warnings if w["code"] not in allowed_codes]
    return {
        "arelle_error_policy_version": ARELLE_ERROR_POLICY_VERSION,
        "allowed_codes": sorted(allowed_codes),
        "errors": errors,
        "warnings": warnings,
        "error_count": sum(error_counts.values()),
        "warning_count": sum(warning_counts.values()),
        "unallowlisted_error_count": sum(e["count"] for e in unallowlisted_errors),
        "unallowlisted_warning_count": sum(w["count"] for w in unallowlisted_warnings),
        "policy_passed": not unallowlisted_errors,
    }
