"""Accession directory index parsing and SGML inventory reconciliation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from lxml import html

from edgar.domain.issues import QualityIssue


@dataclass(frozen=True)
class DirectoryEntry:
    name: str
    last_modified: str | None
    size: str | None
    entry_type: str | None
    url: str


@dataclass(frozen=True)
class SubmittedDocumentRow:
    sequence: str | None
    description: str | None
    name: str
    document_type: str | None
    url: str


@dataclass(frozen=True)
class SgmlDocument:
    sequence: str | None
    filename: str | None
    document_type: str | None
    description: str | None
    block_ordinal: int


def parse_index_json(content: bytes, archive_base: str) -> list[DirectoryEntry]:
    data = json.loads(content.decode("utf-8"))
    items = data.get("directory", {}).get("item", [])
    entries: list[DirectoryEntry] = []
    for item in items:
        name = item.get("name")
        if not name:
            continue
        url = item.get("url") or f"{archive_base}{name}"
        entries.append(
            DirectoryEntry(
                name=name,
                last_modified=item.get("last-modified"),
                size=str(item.get("size")) if item.get("size") is not None else None,
                entry_type=item.get("type"),
                url=url,
            )
        )
    return entries


def parse_index_html(content: bytes, archive_base: str) -> list[SubmittedDocumentRow]:
    doc = html.fromstring(content)
    entries: list[SubmittedDocumentRow] = []
    rows = doc.xpath("//table[@class='tableFile']//tr")
    for row in rows:
        cells = row.xpath("./td")
        if len(cells) < 4:
            continue
        seq = (cells[0].text_content() or "").strip()
        description = (cells[1].text_content() or "").strip()
        doc_type = (cells[3].text_content() or "").strip() if len(cells) > 3 else ""
        anchors = cells[2].xpath(".//a")
        if not anchors:
            continue
        href = anchors[0].get("href") or ""
        name = (anchors[0].text_content() or "").strip()
        if not name:
            name = href.rstrip("/").split("/")[-1]
        if href.startswith("http"):
            file_url = href
        elif href.startswith("/"):
            file_url = f"https://www.sec.gov{href}"
        else:
            file_url = f"{archive_base}{name}"
        entries.append(
            SubmittedDocumentRow(
                sequence=seq or None,
                description=description or None,
                name=name,
                document_type=doc_type or None,
                url=file_url,
            )
        )
    return entries


_HEADER_KEYS = ("SEQUENCE", "FILENAME", "TYPE", "DESCRIPTION")


def parse_sgml_documents(content: bytes) -> list[SgmlDocument]:
    text = content.decode("utf-8", errors="replace")
    documents: list[SgmlDocument] = []
    current: dict[str, str] = {}
    in_document = False
    ordinal = 0
    for raw_line in text.splitlines():
        line = raw_line.strip("\r")
        if line.startswith("<DOCUMENT>"):
            in_document = True
            current = {}
            continue
        if line.startswith("</DOCUMENT>"):
            if in_document:
                documents.append(
                    SgmlDocument(
                        sequence=current.get("SEQUENCE"),
                        filename=current.get("FILENAME"),
                        document_type=current.get("TYPE"),
                        description=current.get("DESCRIPTION"),
                        block_ordinal=ordinal,
                    )
                )
                ordinal += 1
            current = {}
            in_document = False
            continue
        if not in_document:
            continue
        for key in _HEADER_KEYS:
            prefix = f"<{key}>"
            if line.startswith(prefix):
                current[key] = line[len(prefix) :].strip()
                break
    return documents


def reconcile_sgml_inventory(
    *,
    accession: str,
    directory_names: set[str],
    html_rows: list[SubmittedDocumentRow],
    sgml_docs: list[SgmlDocument],
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    complete_name = f"{accession}.txt"
    sgml_names = {d.filename for d in sgml_docs if d.filename}
    html_submitted = {
        e.name
        for e in html_rows
        if e.name
        and (e.document_type or "").upper() not in {"", "GRAPHIC"}
        and e.name.lower() != complete_name.lower()
        and not e.name.lower().endswith(("-index.html", "-index.htm", "index.json"))
    }
    html_filer_submitted: set[str] = set()
    for row in html_rows:
        if not row.name:
            continue
        source_class, role = classify_source_and_role(
            row.name,
            accession=accession,
            description=row.description,
            document_type=row.document_type,
        )
        if source_class == "filer_submitted" and role != "complete_submission":
            html_filer_submitted.add(row.name)
    for name in sorted(sgml_names):
        if name not in directory_names:
            issues.append(
                QualityIssue(
                    severity="fatal",
                    code="SGML_FILENAME_MISSING_FROM_DIRECTORY",
                    message=f"SGML FILENAME {name} missing from accession directory",
                    context={"filename": name},
                )
            )
    for name in sorted(html_filer_submitted - directory_names):
        issues.append(
            QualityIssue(
                severity="fatal",
                code="INDEX_FILER_SUBMITTED_MISSING_FROM_DIRECTORY",
                message=(f"filer-submitted index document {name} missing from accession directory"),
                context={"filename": name},
            )
        )
    for name in sorted(html_submitted - sgml_names):
        issues.append(
            QualityIssue(
                severity="warning",
                code="INDEX_SUBMITTED_ABSENT_FROM_SGML",
                message=f"index submitted document {name} absent from SGML inventory",
                context={"filename": name},
            )
        )
    return issues


_SEC_GENERATED_RENDERING_NAMES = {
    "filingsummary.xml",
    "metalinks.json",
    "show.js",
    "report.css",
    "financial_report.css",
}


def classify_source_and_role(
    filename: str,
    *,
    accession: str,
    description: str | None = None,
    document_type: str | None = None,
) -> tuple[str, str]:
    lower = filename.lower()
    if lower == f"{accession.lower()}.txt":
        return "filer_submitted", "complete_submission"
    if lower.endswith("-index.json") or lower == "index.json":
        return "sec_submission_metadata", "index_json"
    if "index-headers" in lower:
        return "sec_submission_metadata", "index_headers"
    if lower.endswith("-index.html") or lower.endswith("-index.htm"):
        return "sec_submission_metadata", "index_html"
    if lower in _SEC_GENERATED_RENDERING_NAMES:
        return "sec_generated_rendering", "sec_viewer_artifact"
    if re.fullmatch(r"r\d+\.htm(l)?", lower):
        return "sec_generated_rendering", "sec_viewer_artifact"
    if lower.endswith((".css", ".js")) and (
        "viewer" in lower or "report" in lower or lower.startswith("r")
    ):
        return "sec_generated_rendering", "sec_viewer_artifact"
    if lower.endswith(".xsd"):
        return "filer_submitted", "taxonomy_schema"
    if lower.endswith(("_pre.xml", "_cal.xml", "_def.xml", "_lab.xml", "_ref.xml")):
        return "filer_submitted", "linkbase"
    if lower.endswith(".xml") and "htm.xml" in lower:
        return "sec_generated_xbrl", "sec_generated_xbrl"
    if lower.endswith("-xbrl.zip"):
        return "sec_generated_xbrl", "xbrl_zip"
    if lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".svg")):
        return "filer_submitted", "image"
    if document_type and document_type.upper() in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
        return "filer_submitted", "primary_document"
    if description and "GRAPHIC" in description.upper():
        return "filer_submitted", "image"
    if description or document_type:
        return "filer_submitted", "attachment"
    return "unknown", "unknown"
