"""Structured Arelle error/warning capture with an explicit policy.

Every EDGAR filing must be extractable: engine data-quality diagnostics on
filed content (validation and transformation messages) never block extraction.
They are preserved with full multiplicity in evidence. Unknown error codes
fail closed: any error code outside the recognized non-blocking registry fails
the run and forces review, so new failure modes can never slip through.

A code enters RECOGNIZED_NONBLOCKING_CODES only with a written rationale
showing that (a) it diagnoses filed content, not the extraction process, and
(b) the affected structures remain present in Arelle's collections with
matching online/offline counts and stable document/relationship closure.
Slice 0 does not claim validated fact-value fidelity or complete fact
occurrence identities.
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
    # Arelle retains the facts in its fact collection; online/offline fact
    # counts and document/relationship closure remain stable.
    "ix11.10.1.2:invalidTransformation": (
        "legacy SEC transformation namespace unrecognized by the iXBRL 1.0 "
        "registry; facts remain present in Arelle's fact collection with "
        "matching online/offline counts and stable document/relationship closure"
    ),
    "ix11.11.1.2:invalidTransformation": (
        "legacy SEC transformation namespace unrecognized by the iXBRL 1.1 "
        "registry; facts remain present in Arelle's fact collection with "
        "matching online/offline counts and stable document/relationship closure"
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


def canonical_error_identity_records(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Canonical error identity for semantic comparison: code + document + multiplicity.

    Source line is excluded (evidence-only) to avoid depending on Arelle
    line-reporting consistency.
    """
    identity: dict[tuple[str, str | None], int] = {}
    for rec in errors:
        code = rec.get("code")
        if code is None:
            continue
        doc = rec.get("document_uri")
        key = (str(code), str(doc) if doc is not None else None)
        identity[key] = identity.get(key, 0) + int(rec.get("count") or 1)
    return [
        {"code": code, "document_uri": doc, "multiplicity": count}
        for (code, doc), count in sorted(identity.items())
    ]


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
    canonical_records = canonical_error_identity_records(errors)
    return {
        "arelle_error_policy_version": ARELLE_ERROR_POLICY_VERSION,
        "recognized_nonblocking_codes": sorted(recognized),
        "errors": errors,
        "warnings": warnings,
        "canonical_error_records": canonical_records,
        "error_count": sum(error_counts.values()),
        "warning_count": sum(warning_counts.values()),
        "recognized_nonblocking_error_count": sum(e["count"] for e in recognized_errors),
        "unrecognized_error_count": sum(e["count"] for e in unrecognized_errors),
        "policy_passed": not unrecognized_errors,
    }
