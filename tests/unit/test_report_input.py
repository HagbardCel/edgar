"""Unit tests for report-input identification and structural classifiers."""

from __future__ import annotations

import pytest

from edgar.ingestion.report_input import (
    UnsupportedReportInput,
    build_submitted_attachments,
    identify_report_input,
    is_inline_xbrl,
    is_xbrl_instance,
)
from edgar.sec.accession import SgmlDocument, SubmittedDocumentRow

INSTANCE_XML = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">
</xbrli:xbrl>
"""

INLINE_HTML = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
  <body><ix:nonNumeric name="dei:EntityRegistrantName">Acme</ix:nonNumeric></body>
</html>
"""

PLAIN_HTML = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><p>exhibit</p></body></html>
"""


def test_structural_classifiers() -> None:
    assert is_xbrl_instance(INSTANCE_XML)
    assert not is_inline_xbrl(INSTANCE_XML)
    assert is_inline_xbrl(INLINE_HTML)
    assert not is_xbrl_instance(INLINE_HTML)
    assert not is_inline_xbrl(PLAIN_HTML)


def test_complete_submission_not_ixds_member() -> None:
    """Embedded iXBRL markup in .txt must not create an IXDS member."""
    accession = "0001065088-24-000036"
    container = b"<DOCUMENT>\n<FILENAME>a.htm\n" + INLINE_HTML + b"\n</DOCUMENT>\n"
    html_rows = [
        SubmittedDocumentRow("1", "10-K", "a.htm", "10-K", "https://example.com/a.htm"),
        SubmittedDocumentRow("2", "EXHIBIT", "ex99.htm", "EX-99", "https://example.com/ex99.htm"),
    ]
    sgml = [
        SgmlDocument("1", "a.htm", "10-K", "10-K", 0),
        SgmlDocument("2", "ex99.htm", "EX-99", "EXHIBIT", 1),
    ]
    artifact_bytes = {
        "accession/a.htm": INLINE_HTML,
        "accession/ex99.htm": INLINE_HTML,
        f"accession/{accession}.txt": container,
    }
    digests = {k: "ab" * 32 for k in artifact_bytes}
    attachments = build_submitted_attachments(
        accession=accession,
        html_rows=html_rows,
        sgml_docs=sgml,
        artifact_bytes=artifact_bytes,
        artifact_digests=digests,
    )
    names = {a.filename for a in attachments}
    assert accession + ".txt" not in names
    assert "a.htm" in names


def test_ixds_primary_first_filename_order() -> None:
    accession = "0001065088-24-000036"
    html_rows = [
        SubmittedDocumentRow("1", "10-K", "primary.htm", "10-K", "u"),
        SubmittedDocumentRow("2", "EX-99", "z-ex.htm", "EX-99", "u"),
        SubmittedDocumentRow("3", "EX-99", "a-ex.htm", "EX-99", "u"),
    ]
    sgml = [
        SgmlDocument("1", "primary.htm", "10-K", None, 0),
        SgmlDocument("2", "z-ex.htm", "EX-99", None, 1),
        SgmlDocument("3", "a-ex.htm", "EX-99", None, 2),
    ]
    artifact_bytes = {
        "accession/primary.htm": INLINE_HTML,
        "accession/z-ex.htm": INLINE_HTML,
        "accession/a-ex.htm": INLINE_HTML,
    }
    digests = {k: "cd" * 32 for k in artifact_bytes}
    report, _ = identify_report_input(
        cik="0001065088",
        accession=accession,
        form_type="10-K",
        primary_document="primary.htm",
        html_rows=html_rows,
        sgml_docs=sgml,
        artifact_bytes=artifact_bytes,
        artifact_digests=digests,
    )
    assert report.kind == "ixds"
    assert report.target == "default"  # type: ignore[union-attr]
    uris = report.document_uris
    assert uris[0].endswith("/primary.htm")
    assert uris[1].endswith("/a-ex.htm")
    assert uris[2].endswith("/z-ex.htm")


def test_legacy_ex101_ins_path() -> None:
    accession = "0001065088-14-000001"
    html_rows = [
        SubmittedDocumentRow("1", "10-K", "primary.htm", "10-K", "u"),
        SubmittedDocumentRow("2", "XBRL INSTANCE", "fve.xml", "EX-101.INS", "u"),
    ]
    sgml = [
        SgmlDocument("1", "primary.htm", "10-K", None, 0),
        SgmlDocument("2", "fve.xml", "EX-101.INS", None, 1),
    ]
    artifact_bytes = {
        "accession/primary.htm": PLAIN_HTML,
        "accession/fve.xml": INSTANCE_XML,
        "accession/fve_htm.xml": INSTANCE_XML,  # generated companion must be ignored
    }
    digests = {k: "ef" * 32 for k in artifact_bytes}
    # Generated companion is not a submitted attachment without HTML/SGML row.
    report, _ = identify_report_input(
        cik="0001065088",
        accession=accession,
        form_type="10-K",
        primary_document="primary.htm",
        html_rows=html_rows,
        sgml_docs=sgml,
        artifact_bytes=artifact_bytes,
        artifact_digests=digests,
    )
    assert report.kind == "instance"
    assert report.document_uris[0].endswith("/fve.xml")


def test_primary_conflict() -> None:
    accession = "0001065088-24-000036"
    html_rows = [
        SubmittedDocumentRow("1", "10-K", "other.htm", "10-K", "u"),
    ]
    sgml = [SgmlDocument("1", "primary.htm", "10-K", None, 0)]
    artifact_bytes = {"accession/primary.htm": INLINE_HTML}
    digests = {"accession/primary.htm": "11" * 32}
    with pytest.raises(UnsupportedReportInput):
        identify_report_input(
            cik="0001065088",
            accession=accession,
            form_type="10-K",
            primary_document="primary.htm",
            html_rows=html_rows,
            sgml_docs=sgml,
            artifact_bytes=artifact_bytes,
            artifact_digests=digests,
        )
