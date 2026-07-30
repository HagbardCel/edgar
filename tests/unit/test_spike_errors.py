"""Unit tests for the structured Arelle error policy (no network)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib import ARELLE_ERROR_POLICY_VERSION  # noqa: E402
from spike_lib.arelle_errors import (  # noqa: E402
    UNSTRUCTURED_CODE,
    ErrorCapture,
    StructuredError,
    summarize_errors,
)


def test_capture_extracts_code_doc_line() -> None:
    capture = ErrorCapture()
    logger = logging.getLogger("test-arelle-capture")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(capture)
    try:
        record = logger.makeRecord(
            logger.name,
            logging.ERROR,
            __file__,
            10,
            "bad thing",
            args=(),
            exc_info=None,
        )
        record.messageCode = "xmlSchema:requiredAttribute"
        record.refs = [{"href": "https://example.com/a.xsd", "sourceLine": "42"}]
        capture.emit(record)
    finally:
        logger.removeHandler(capture)
    assert len(capture.records) == 1
    rec = capture.records[0]
    assert rec.severity == "error"
    assert rec.code == "xmlSchema:requiredAttribute"
    assert rec.document_uri == "https://example.com/a.xsd"
    assert rec.source_line == 42


def test_capture_unstructured_code_and_info_ignored() -> None:
    capture = ErrorCapture()
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "info", (), None)
    capture.emit(record)
    assert capture.records == []

    warn = logging.LogRecord("x", logging.WARNING, __file__, 1, "warn", (), None)
    capture.emit(warn)
    assert capture.records[0].code == UNSTRUCTURED_CODE
    assert capture.records[0].severity == "warning"


def test_summarize_multiplicity_deterministic() -> None:
    records = [
        StructuredError("error", "a", "https://x/d.xsd", 1),
        StructuredError("error", "a", "https://x/d.xsd", 1),
        StructuredError("warning", "b", None, None),
    ]
    summary1 = summarize_errors(records)
    summary2 = summarize_errors(list(reversed(records)))
    assert summary1 == summary2
    error_entries = summary1["errors"]
    assert error_entries == [
        {"code": "a", "document_uri": "https://x/d.xsd", "source_line": 1, "count": 2}
    ]
    assert summary1["error_count"] == 2
    assert summary1["warning_count"] == 1
    assert summary1["unallowlisted_error_count"] == 2
    assert summary1["unallowlisted_warning_count"] == 1
    assert summary1["policy_passed"] is False
    assert summary1["arelle_error_policy_version"] == ARELLE_ERROR_POLICY_VERSION


def test_summarize_empty_allowlist_is_strict_default() -> None:
    records = [StructuredError("error", "arelle:whatever", None, None)]
    summary = summarize_errors(records, allowed_codes=frozenset())
    assert summary["policy_passed"] is False
    summary_ok = summarize_errors(records, allowed_codes=frozenset({"arelle:whatever"}))
    assert summary_ok["policy_passed"] is True
    assert summary_ok["unallowlisted_error_count"] == 0
