"""Deterministic primary XBRL report-input identification (ADR 0009)."""

from __future__ import annotations

from dataclasses import dataclass

import lxml.etree as etree

from edgar.domain.bundle import InstanceReportInput, IxdsReportInput, XbrlReportInput
from edgar.domain.identifiers import accession_archive_base
from edgar.domain.issues import QualityIssue
from edgar.sec.accession import SgmlDocument, SubmittedDocumentRow, classify_source_and_role
from edgar.xbrl.uri import normalize_uri

XBRLI_NS = "http://www.xbrl.org/2003/instance"
INLINE_NS_URIS = frozenset(
    {
        "http://www.xbrl.org/2013/inlineXBRL",
        "http://www.xbrl.org/2008/inlineXBRL",
    }
)
EX_FILING_FEES_TYPES = frozenset({"EX-FILING FEES", "EX-FILINGFEE"})


class UnsupportedReportInput(ValueError):
    """Raised when report input cannot be deterministically identified."""


def is_inline_xbrl(data: bytes) -> bool:
    """Structural check: XML/XHTML with Inline XBRL namespace-bound elements."""
    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError:
        return False
    for el in root.iter():
        ns = etree.QName(el).namespace
        if ns in INLINE_NS_URIS:
            return True
    return False


def is_xbrl_instance(data: bytes) -> bool:
    """Structural check: xbrli:xbrl root; excludes inline documents."""
    if is_inline_xbrl(data):
        return False
    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError:
        return False
    qn = etree.QName(root)
    return qn.namespace == XBRLI_NS and qn.localname == "xbrl"


@dataclass(frozen=True)
class SubmittedAttachment:
    filename: str
    document_type: str | None
    description: str | None
    logical_path: str
    content_sha256: str
    source_class: str
    artifact_role: str


def reconcile_primary_row(
    *,
    form_type: str,
    primary_document: str,
    html_rows: list[SubmittedDocumentRow],
    sgml_docs: list[SgmlDocument],
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    html_matches = [
        r
        for r in html_rows
        if r.name == primary_document and (r.document_type or "").upper() == form_type.upper()
    ]
    if len(html_matches) != 1:
        issues.append(
            QualityIssue(
                severity="fatal",
                code="PRIMARY_DOCUMENT_CONFLICT",
                message="index HTML primary row mismatch",
                context={
                    "expected_filename": primary_document,
                    "expected_type": form_type,
                    "matches": len(html_matches),
                },
            )
        )
    sgml_matches = [
        d
        for d in sgml_docs
        if d.filename == primary_document and (d.document_type or "").upper() == form_type.upper()
    ]
    if len(sgml_matches) != 1:
        issues.append(
            QualityIssue(
                severity="fatal",
                code="PRIMARY_DOCUMENT_CONFLICT",
                message="SGML primary DOCUMENT mismatch",
                context={
                    "expected_filename": primary_document,
                    "expected_type": form_type,
                    "matches": len(sgml_matches),
                },
            )
        )
    return issues


def _doc_type_for(
    filename: str,
    html_rows: list[SubmittedDocumentRow],
    sgml_docs: list[SgmlDocument],
) -> str | None:
    for row in html_rows:
        if row.name == filename and row.document_type:
            return row.document_type
    for doc in sgml_docs:
        if doc.filename == filename and doc.document_type:
            return doc.document_type
    return None


def build_submitted_attachments(
    *,
    accession: str,
    html_rows: list[SubmittedDocumentRow],
    sgml_docs: list[SgmlDocument],
    artifact_bytes: dict[str, bytes],
    artifact_digests: dict[str, str],
) -> list[SubmittedAttachment]:
    """Individual DOCUMENT attachments only (not complete submission / metadata)."""
    names: set[str] = set()
    for row in html_rows:
        if row.name:
            names.add(row.name)
    for doc in sgml_docs:
        if doc.filename:
            names.add(doc.filename)

    attachments: list[SubmittedAttachment] = []
    for name in sorted(names):
        logical = f"accession/{name}"
        if logical not in artifact_bytes:
            continue
        doc_type = _doc_type_for(name, html_rows, sgml_docs)
        description = None
        for row in html_rows:
            if row.name == name:
                description = row.description
                break
        source_class, role = classify_source_and_role(
            name, accession=accession, description=description, document_type=doc_type
        )
        if role in {"complete_submission", "index_json", "index_html", "index_headers"}:
            continue
        if source_class.startswith("sec_generated"):
            continue
        if source_class != "filer_submitted":
            continue
        attachments.append(
            SubmittedAttachment(
                filename=name,
                document_type=doc_type,
                description=description,
                logical_path=logical,
                content_sha256=artifact_digests[logical],
                source_class=source_class,
                artifact_role=role,
            )
        )
    return attachments


def identify_report_input(
    *,
    cik: str,
    accession: str,
    form_type: str,
    primary_document: str,
    html_rows: list[SubmittedDocumentRow],
    sgml_docs: list[SgmlDocument],
    artifact_bytes: dict[str, bytes],
    artifact_digests: dict[str, str],
) -> tuple[XbrlReportInput, list[QualityIssue]]:
    issues = reconcile_primary_row(
        form_type=form_type,
        primary_document=primary_document,
        html_rows=html_rows,
        sgml_docs=sgml_docs,
    )
    if any(i.severity == "fatal" for i in issues):
        raise UnsupportedReportInput("primary document reconciliation failed")

    primary_path = f"accession/{primary_document}"
    if primary_path not in artifact_bytes:
        raise UnsupportedReportInput(f"primary document missing: {primary_path}")

    archive = accession_archive_base(cik, accession)
    primary_bytes = artifact_bytes[primary_path]
    attachments = build_submitted_attachments(
        accession=accession,
        html_rows=html_rows,
        sgml_docs=sgml_docs,
        artifact_bytes=artifact_bytes,
        artifact_digests=artifact_digests,
    )

    if is_inline_xbrl(primary_bytes):
        inline_docs = [
            a
            for a in attachments
            if is_inline_xbrl(artifact_bytes[a.logical_path])
            and (a.document_type or "").upper() not in EX_FILING_FEES_TYPES
        ]
        primary_att = next((a for a in inline_docs if a.filename == primary_document), None)
        if primary_att is None:
            raise UnsupportedReportInput("primary document not in inline candidate set")
        # Evidence of independent non-primary instance types is out of Phase-1
        # form universe; if we later detect conflicting instance families, fail.
        remaining = [a for a in inline_docs if a.filename != primary_document]
        remaining.sort(key=lambda a: a.filename.encode("utf-8"))
        ordered = [primary_att, *remaining]
        uris = tuple(normalize_uri(f"{archive}{a.filename}") for a in ordered)
        return IxdsReportInput(document_uris=uris, target="default"), issues

    # Traditional instance path.
    candidates = [
        a
        for a in attachments
        if (a.document_type or "").upper() == "EX-101.INS"
        and a.source_class == "filer_submitted"
        and "htm.xml" not in a.filename.lower()
        and is_xbrl_instance(artifact_bytes[a.logical_path])
    ]
    if len(candidates) != 1:
        raise UnsupportedReportInput(
            f"expected exactly one EX-101.INS instance, found {len(candidates)}"
        )
    uri = normalize_uri(f"{archive}{candidates[0].filename}")
    return InstanceReportInput(document_uris=(uri,)), issues
