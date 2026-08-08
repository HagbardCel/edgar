"""Unit tests for SGML/HTML accession inventory reconciliation."""

from __future__ import annotations

from edgar.sec.accession import (
    SubmittedDocumentRow,
    reconcile_sgml_inventory,
)

ACCESSION = "0001065088-24-000036"


def test_html_filer_submitted_missing_from_directory_is_fatal() -> None:
    html_rows = [
        SubmittedDocumentRow("2", "Exhibit", "foo.htm", "EX-99", "https://example.com/foo.htm"),
    ]
    issues = reconcile_sgml_inventory(
        accession=ACCESSION,
        directory_names=set(),
        html_rows=html_rows,
        sgml_docs=[],
    )
    codes = {i.code for i in issues}
    assert "INDEX_FILER_SUBMITTED_MISSING_FROM_DIRECTORY" in codes
    assert "INDEX_SUBMITTED_ABSENT_FROM_SGML" in codes
    fatal = [i for i in issues if i.code == "INDEX_FILER_SUBMITTED_MISSING_FROM_DIRECTORY"]
    assert len(fatal) == 1
    assert fatal[0].severity == "fatal"
    assert fatal[0].context == {"filename": "foo.htm"}


def test_sec_generated_html_row_absent_from_directory_is_not_fatal() -> None:
    html_rows = [
        SubmittedDocumentRow("99", "Rendering", "R1.htm", "XML", "https://example.com/R1.htm"),
    ]
    issues = reconcile_sgml_inventory(
        accession=ACCESSION,
        directory_names=set(),
        html_rows=html_rows,
        sgml_docs=[],
    )
    assert not any(i.code == "INDEX_FILER_SUBMITTED_MISSING_FROM_DIRECTORY" for i in issues)
