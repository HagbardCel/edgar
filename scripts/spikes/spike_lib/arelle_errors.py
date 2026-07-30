"""Structured Arelle error/warning capture with an explicit policy.

Every EDGAR filing must be extractable: engine data-quality diagnostics on
filed content (validation and transformation messages) never block extraction.
They are preserved with full multiplicity in evidence. Unknown error codes
fail closed: any error code outside the recognized non-blocking registry fails
the run and forces review, so new failure modes can never slip through.

A code enters RECOGNIZED_NONBLOCKING_CODES only with a written rationale
showing that (a) it diagnoses filed content, not the extraction process, and
(b) the affected structures are still extracted and occurrence-identified.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from spike_lib import ARELLE_ERROR_POLICY_VERSION

UNSTRUCTURED_CODE = "UNSTRUCTURED"

# Recognized engine data-quality diagnostics that never block extraction.
# Each entry must cite why the diagnostic cannot hide an extraction failure.
RECOGNIZED_NONBLOCKING_CODES: dict[str, str] = {
    # eBay 10-K (and many EDGAR filings) use the legacy SEC inline XBRL
    # transformation namespace http://www.sec.gov/inlineXBRL/transformation/2015-08-31,
    # which Arelle's iXBRL 1.1 transformation registry does not recognize.
    # Arelle retains the facts; fact counts and closure are unaffected.
    "ix11.10.1.2:invalidTransformation": (
        "legacy SEC transformation namespace unrecognized by the iXBRL 1.0 "
        "registry; facts are retained and occurrence-identified"
    ),
    "ix11.11.1.2:invalidTransformation": (
        "legacy SEC transformation namespace unrecognized by the iXBRL 1.1 "
        "registry; facts are retained and occurrence-identified"
    ),
}


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
    records: list[StructuredError],
    *,
    recognized_nonblocking: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Deterministic structured summary with explicit multiplicity.

    Fails closed: policy passes only when every error code is recognized as a
    non-blocking engine data-quality diagnostic. Warnings never fail the run;
    they are reported with full multiplicity.
    """
    recognized = (
        RECOGNIZED_NONBLOCKING_CODES if recognized_nonblocking is None else recognized_nonblocking
    )
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
    recognized_errors = [e for e in errors if e["code"] in recognized]
    unrecognized_errors = [e for e in errors if e["code"] not in recognized]
    return {
        "arelle_error_policy_version": ARELLE_ERROR_POLICY_VERSION,
        "recognized_nonblocking_codes": sorted(recognized),
        "errors": errors,
        "warnings": warnings,
        "error_count": sum(error_counts.values()),
        "warning_count": sum(warning_counts.values()),
        "recognized_nonblocking_error_count": sum(e["count"] for e in recognized_errors),
        "unrecognized_error_count": sum(e["count"] for e in unrecognized_errors),
        "policy_passed": not unrecognized_errors,
    }
