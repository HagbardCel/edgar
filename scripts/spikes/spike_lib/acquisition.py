"""Accession mirroring, SGML reconciliation, and bundle construction for Slice 0."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from lxml import html

from spike_lib import (
    ACQUISITION_POLICY_VERSION,
    DISCOVERY_EXTRACTION_POLICY_VERSION,
)
from spike_lib.hashing import payload_hash, sha256_of_uri
from spike_lib.quality import QualityIssue
from spike_lib.sec import (
    SecClient,
    SizeLimitExceeded,
    accession_archive_base,
    classify_source_and_role,
    extract_accession_record,
    normalize_cik,
    sanitize_basename,
    submissions_url,
    validate_accession,
    validate_logical_path,
)
from spike_lib.storage import ObjectStore, write_json_atomic


@dataclass
class ArtifactRecord:
    logical_path: str
    sha256: str
    byte_size: int
    source_url: str | None
    final_url: str | None
    source_class: str
    artifact_role: str
    content_type: str | None = None
    sec_sequence: str | None = None
    sec_document_type: str | None = None
    sec_description: str | None = None
    required: bool = True
    in_payload: bool = True
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_path": self.logical_path,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "source_url": self.source_url,
            "final_url": self.final_url,
            "source_class": self.source_class,
            "artifact_role": self.artifact_role,
            "content_type": self.content_type,
            "sec_sequence": self.sec_sequence,
            "sec_document_type": self.sec_document_type,
            "sec_description": self.sec_description,
            "required": self.required,
            "in_payload": self.in_payload,
            "notes": self.notes,
        }


@dataclass
class SgmlDocument:
    sequence: str | None
    filename: str | None
    document_type: str | None
    description: str | None
    block_ordinal: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "filename": self.filename,
            "document_type": self.document_type,
            "description": self.description,
            "block_ordinal": self.block_ordinal,
        }


@dataclass
class BundleDraft:
    cik: str
    accession: str
    archive_base: str
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    discovery: dict[str, Any] = field(default_factory=dict)
    issuer_provenance: dict[str, Any] = field(default_factory=dict)
    index_entries: list[dict[str, Any]] = field(default_factory=list)
    primary_document: str | None = None
    sgml_documents: list[SgmlDocument] = field(default_factory=list)
    sgml_reconciliation: dict[str, Any] = field(default_factory=dict)

    def artifact_by_path(self, logical_path: str) -> ArtifactRecord | None:
        for artifact in self.artifacts:
            if artifact.logical_path == logical_path:
                return artifact
        return None

    def artifact_by_sha256(self, digest: str) -> ArtifactRecord | None:
        for artifact in self.artifacts:
            if artifact.sha256 == digest and artifact.in_payload:
                return artifact
        return None

    def payload_entries(self) -> list[tuple[str, str, int]]:
        return [(a.logical_path, a.sha256, a.byte_size) for a in self.artifacts if a.in_payload]

    def compute_payload_hash(self) -> str:
        return payload_hash(self.payload_entries())


def parse_index_json(content: bytes, archive_base: str) -> list[dict[str, Any]]:
    data = json.loads(content.decode("utf-8"))
    items = data.get("directory", {}).get("item", [])
    entries: list[dict[str, Any]] = []
    for item in items:
        name = item.get("name")
        if not name:
            continue
        entries.append(
            {
                "name": name,
                "last_modified": item.get("last-modified"),
                "size": item.get("size"),
                "type": item.get("type"),
                "url": urljoin(archive_base, name),
            }
        )
    return entries


def parse_index_html(content: bytes, archive_base: str) -> list[dict[str, Any]]:
    doc = html.fromstring(content)
    entries: list[dict[str, Any]] = []
    rows = doc.xpath("//table[@class='tableFile']//tr")
    for row in rows:
        cells = row.xpath("./td")
        if len(cells) < 4:
            continue
        seq = (cells[0].text_content() or "").strip()
        description = (cells[1].text_content() or "").strip()
        anchors = cells[2].xpath(".//a")
        if not anchors:
            continue
        href = anchors[0].get("href")
        name = (anchors[0].text_content() or "").strip()
        if not href or not name:
            continue
        if "doc=" in href:
            match = re.search(r"doc=([^&]+)", href)
            if match:
                href = match.group(1)
        if href.startswith("/"):
            file_url = "https://www.sec.gov" + href
        else:
            file_url = urljoin(archive_base, href)
        basename = file_url.rstrip("/").split("/")[-1]
        doc_type = (cells[3].text_content() or "").strip()
        entries.append(
            {
                "sequence": seq,
                "description": description,
                "name": basename,
                "document_type": doc_type,
                "url": file_url,
            }
        )
    return entries


_HEADER_KEYS = ("SEQUENCE", "FILENAME", "TYPE", "DESCRIPTION")


def parse_sgml_documents(content: bytes) -> list[SgmlDocument]:
    """Line-oriented SGML <DOCUMENT> inventory parser.

    Does not use a single greedy regex over the entire filing.
    """
    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines()
    documents: list[SgmlDocument] = []
    in_document = False
    current: dict[str, str | None] = {}
    ordinal = 0

    def flush() -> None:
        nonlocal ordinal, current, in_document
        if not in_document:
            return
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

    for raw_line in lines:
        line = raw_line.strip()
        upper = line.upper()
        if upper == "<DOCUMENT>":
            flush()
            in_document = True
            current = {k: None for k in _HEADER_KEYS}
            continue
        if upper == "</DOCUMENT>":
            flush()
            continue
        if not in_document:
            continue
        for key in _HEADER_KEYS:
            prefix = f"<{key}>"
            if upper.startswith(prefix):
                # Preserve original value after the tag (case-sensitive remainder).
                value = raw_line.strip()[len(prefix) :].strip()
                current[key] = value or None
                break
    flush()
    return documents


def reconcile_sgml_inventory(
    *,
    sgml_documents: list[SgmlDocument],
    directory_names: set[str],
    html_submitted_names: set[str],
    accession_artifact_names: set[str],
) -> tuple[dict[str, Any], list[QualityIssue]]:
    """Reconcile SGML submitted-document inventory with index/directory inventories.

    SEC-generated directory artifacts are expected to be absent from SGML.
    """
    issues: list[QualityIssue] = []
    sgml_filenames = [d.filename for d in sgml_documents if d.filename]
    sgml_filename_set = set(sgml_filenames)
    missing_filename_blocks = [d.to_dict() for d in sgml_documents if not d.filename]

    # Duplicate filenames / sequences
    seen_names: dict[str, int] = {}
    for name in sgml_filenames:
        seen_names[name] = seen_names.get(name, 0) + 1
    duplicate_filenames = sorted(n for n, c in seen_names.items() if c > 1)
    if duplicate_filenames:
        issues.append(
            QualityIssue(
                severity="warning",
                code="SGML_DUPLICATE_FILENAME",
                message="duplicate FILENAME values in complete submission",
                context={"names": duplicate_filenames},
            )
        )

    sequences = [d.sequence for d in sgml_documents if d.sequence]
    seen_seq: dict[str, int] = {}
    for seq in sequences:
        seen_seq[seq] = seen_seq.get(seq, 0) + 1
    duplicate_sequences = sorted(s for s, c in seen_seq.items() if c > 1)
    if duplicate_sequences:
        issues.append(
            QualityIssue(
                severity="warning",
                code="SGML_DUPLICATE_SEQUENCE",
                message="duplicate SEQUENCE values in complete submission",
                context={"sequences": duplicate_sequences},
            )
        )

    if missing_filename_blocks:
        issues.append(
            QualityIssue(
                severity="info",
                code="SGML_MISSING_FILENAME",
                message="SGML DOCUMENT blocks without FILENAME preserved",
                context={"count": len(missing_filename_blocks)},
            )
        )

    missing_directory_files = sorted(
        n
        for n in sgml_filename_set
        if n not in directory_names and n not in accession_artifact_names
    )
    for name in missing_directory_files:
        issues.append(
            QualityIssue(
                severity="fatal",
                code="SGML_FILENAME_MISSING_FROM_DIRECTORY",
                message="SGML FILENAME absent from accession directory inventory",
                context={"filename": name},
            )
        )

    # Submitted documents from HTML index should appear in SGML when they have filenames.
    unmatched_submitted_index_entries = sorted(html_submitted_names - sgml_filename_set)
    for name in unmatched_submitted_index_entries:
        issues.append(
            QualityIssue(
                severity="warning",
                code="INDEX_SUBMITTED_ABSENT_FROM_SGML",
                message="filing-index submitted document absent from SGML inventory",
                context={"filename": name},
            )
        )

    generated_directory_extras = sorted(directory_names - sgml_filename_set)
    matched = sorted(sgml_filename_set & (directory_names | accession_artifact_names))

    result = {
        "sgml_document_count": len(sgml_documents),
        "sgml_with_filename_count": len(sgml_filename_set),
        "matched_submitted_files": matched,
        "matched_submitted_file_count": len(matched),
        "missing_directory_files": missing_directory_files,
        "unmatched_submitted_index_entries": unmatched_submitted_index_entries,
        "generated_directory_extras": generated_directory_extras,
        "missing_filename_block_count": len(missing_filename_blocks),
        "duplicate_filenames": duplicate_filenames,
        "duplicate_sequences": duplicate_sequences,
        "passed": not missing_directory_files,
    }
    return result, issues


class AcquisitionService:
    def __init__(
        self,
        client: SecClient,
        store: ObjectStore,
        *,
        max_file_bytes: int,
        max_bundle_bytes: int,
    ) -> None:
        self.client = client
        self.store = store
        self.max_file_bytes = max_file_bytes
        self.max_bundle_bytes = max_bundle_bytes

    def _put_object(
        self,
        draft: BundleDraft,
        *,
        logical_path: str,
        sha256: str,
        byte_size: int,
        source_url: str | None,
        final_url: str | None,
        source_class: str,
        artifact_role: str,
        in_payload: bool = True,
        required: bool = True,
        content_type: str | None = None,
        sec_sequence: str | None = None,
        sec_document_type: str | None = None,
        sec_description: str | None = None,
        notes: str | None = None,
    ) -> ArtifactRecord:
        validate_logical_path(logical_path)
        if byte_size > self.max_file_bytes:
            draft.issues.append(
                QualityIssue(
                    severity="fatal",
                    code="FILE_SIZE_LIMIT_EXCEEDED",
                    message=f"file exceeds MAX_FILE_BYTES ({self.max_file_bytes})",
                    context={"logical_path": logical_path, "byte_size": byte_size},
                )
            )
            raise RuntimeError(f"file size limit exceeded for {logical_path}")

        existing = draft.artifact_by_path(logical_path)
        if existing is not None:
            return existing

        artifact = ArtifactRecord(
            logical_path=logical_path,
            sha256=sha256,
            byte_size=byte_size,
            source_url=source_url,
            final_url=final_url,
            source_class=source_class,
            artifact_role=artifact_role,
            content_type=content_type,
            sec_sequence=sec_sequence,
            sec_document_type=sec_document_type,
            sec_description=sec_description,
            required=required,
            in_payload=in_payload,
            notes=notes,
        )
        draft.artifacts.append(artifact)

        payload_total = sum(a.byte_size for a in draft.artifacts if a.in_payload)
        if payload_total > self.max_bundle_bytes:
            draft.issues.append(
                QualityIssue(
                    severity="fatal",
                    code="BUNDLE_SIZE_LIMIT_EXCEEDED",
                    message=f"bundle exceeds MAX_BUNDLE_BYTES ({self.max_bundle_bytes})",
                    context={"payload_bytes": payload_total},
                )
            )
            raise RuntimeError("bundle size limit exceeded")
        return artifact

    def _fetch_put(
        self,
        draft: BundleDraft,
        *,
        url: str,
        logical_path: str,
        source_class: str,
        artifact_role: str,
        in_payload: bool = True,
        required: bool = True,
        sec_sequence: str | None = None,
        sec_document_type: str | None = None,
        sec_description: str | None = None,
        notes: str | None = None,
    ) -> ArtifactRecord:
        try:
            fetched, obj = self.client.fetch_to_store(
                url, self.store, max_bytes=self.max_file_bytes
            )
        except SizeLimitExceeded as exc:
            draft.issues.append(
                QualityIssue(
                    severity="fatal",
                    code="FILE_SIZE_LIMIT_EXCEEDED",
                    message=str(exc),
                    context={"logical_path": logical_path, "url": url},
                )
            )
            raise
        return self._put_object(
            draft,
            logical_path=logical_path,
            sha256=obj.sha256,
            byte_size=obj.byte_size,
            source_url=fetched.url,
            final_url=fetched.final_url,
            source_class=source_class,
            artifact_role=artifact_role,
            in_payload=in_payload,
            required=required,
            content_type=fetched.headers.get("content-type"),
            sec_sequence=sec_sequence,
            sec_document_type=sec_document_type,
            sec_description=sec_description,
            notes=notes,
        )

    def acquire(self, cik: str, accession: str) -> BundleDraft:
        cik_n = normalize_cik(cik)
        accession = validate_accession(accession)
        archive_base = accession_archive_base(cik_n, accession)
        draft = BundleDraft(cik=cik_n, accession=accession, archive_base=archive_base)

        # Raw submissions (provenance only; excluded from payload_hash).
        submissions_artifact = self._fetch_put(
            draft,
            url=submissions_url(cik_n),
            logical_path="metadata/submissions.raw.json",
            source_class="sec_submission_metadata",
            artifact_role="submissions_raw",
            in_payload=False,
            required=False,
            notes="Excluded from payload_hash; issuer submissions mutate over time.",
        )
        submissions = json.loads(self.store.open_bytes(submissions_artifact.sha256))

        accession_meta = extract_accession_record(submissions, accession)
        if accession_meta is None:
            draft.issues.append(
                QualityIssue(
                    severity="fatal",
                    code="ACCESSION_NOT_IN_SUBMISSIONS",
                    message="accession not found in issuer submissions JSON",
                    context={"cik": cik_n, "accession": accession},
                )
            )
            raise RuntimeError("accession not found in submissions JSON")

        draft.primary_document = accession_meta.get("primary_document")
        # Payload discovery: accession-specific values only (no mutable issuer name).
        draft.discovery = {
            "cik": cik_n,
            "accession": accession,
            "form": accession_meta.get("form"),
            "filing_date": accession_meta.get("filing_date"),
            "acceptance_timestamp": accession_meta.get("acceptance_datetime"),
            "report_period": accession_meta.get("report_period"),
            "primary_document": accession_meta.get("primary_document"),
            "archive_path": archive_base,
            "source_endpoint": submissions_url(cik_n),
            "extraction_policy_version": DISCOVERY_EXTRACTION_POLICY_VERSION,
            "is_inline_xbrl": accession_meta.get("is_inline_xbrl"),
            "is_xbrl": accession_meta.get("is_xbrl"),
        }
        draft.issuer_provenance = {
            "company_name": submissions.get("name"),
            "cik": cik_n,
        }
        discovery_bytes = (
            json.dumps(
                draft.discovery,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8")
            + b"\n"
        )
        discovery_obj = self.store.put_bytes(discovery_bytes)
        self._put_object(
            draft,
            logical_path="metadata/discovery.json",
            sha256=discovery_obj.sha256,
            byte_size=discovery_obj.byte_size,
            source_url=None,
            final_url=None,
            source_class="sec_submission_metadata",
            artifact_role="discovery_record",
            in_payload=True,
            content_type="application/json",
        )

        # Directory index JSON
        index_json_url = urljoin(archive_base, "index.json")
        index_json_artifact = self._fetch_put(
            draft,
            url=index_json_url,
            logical_path="metadata/index.json",
            source_class="sec_submission_metadata",
            artifact_role="index_json",
        )
        json_entries = parse_index_json(
            self.store.open_bytes(index_json_artifact.sha256), archive_base
        )

        # Index HTML / headers
        metadata_fetches = (
            (f"{accession}-index.html", "metadata/index.html", "index_html"),
            (
                f"{accession}-index-headers.html",
                "metadata/index-headers.html",
                "index_headers",
            ),
        )
        for filename, logical_path, role in metadata_fetches:
            url = urljoin(archive_base, filename)
            try:
                self._fetch_put(
                    draft,
                    url=url,
                    logical_path=logical_path,
                    source_class="sec_submission_metadata",
                    artifact_role=role,
                )
            except Exception as exc:  # noqa: BLE001
                draft.issues.append(
                    QualityIssue(
                        severity="warning",
                        code="INDEX_METADATA_FETCH_FAILED",
                        message=str(exc),
                        context={"url": url, "role": role},
                    )
                )

        html_entries: list[dict[str, Any]] = []
        index_html_artifact = draft.artifact_by_path("metadata/index.html")
        if index_html_artifact is not None:
            html_entries = parse_index_html(
                self.store.open_bytes(index_html_artifact.sha256),
                archive_base,
            )

        by_name: dict[str, dict[str, Any]] = {}
        for entry in json_entries:
            by_name[entry["name"]] = {**entry, "from_json": True}
        for entry in html_entries:
            current = by_name.get(entry["name"], {"name": entry["name"], "url": entry["url"]})
            current.update({k: v for k, v in entry.items() if v})
            current["from_html"] = True
            by_name[entry["name"]] = current

        draft.index_entries = sorted(by_name.values(), key=lambda e: e["name"])

        for entry in json_entries:
            name = entry["name"]
            url = entry["url"]
            meta = by_name.get(name, entry)
            source_class, artifact_role = classify_source_and_role(
                name,
                accession=accession,
                description=meta.get("description"),
                document_type=meta.get("document_type"),
            )
            self._fetch_put(
                draft,
                url=url,
                logical_path=f"accession/{name}",
                source_class=source_class,
                artifact_role=artifact_role,
                sec_sequence=meta.get("sequence"),
                sec_document_type=meta.get("document_type"),
                sec_description=meta.get("description"),
                required=True,
            )

        complete_name = f"{accession}.txt"
        if draft.artifact_by_path(f"accession/{complete_name}") is None:
            draft.issues.append(
                QualityIssue(
                    severity="fatal",
                    code="MISSING_COMPLETE_SUBMISSION",
                    message="complete submission text missing from accession directory",
                    context={"expected": f"accession/{complete_name}"},
                )
            )
        if draft.primary_document:
            primary_path = f"accession/{draft.primary_document}"
            if draft.artifact_by_path(primary_path) is None:
                draft.issues.append(
                    QualityIssue(
                        severity="fatal",
                        code="MISSING_PRIMARY_DOCUMENT",
                        message="primary document missing from accession directory",
                        context={"expected": primary_path},
                    )
                )

        json_names = {e["name"] for e in json_entries}
        html_names = {e["name"] for e in html_entries}
        only_json = sorted(json_names - html_names)
        only_html = sorted(html_names - json_names)
        if only_html:
            draft.issues.append(
                QualityIssue(
                    severity="warning",
                    code="INDEX_HTML_ONLY_ENTRIES",
                    message="index.html lists files not present in index.json",
                    context={"names": only_html},
                )
            )
        if only_json and html_entries:
            draft.issues.append(
                QualityIssue(
                    severity="info",
                    code="INDEX_JSON_ONLY_ENTRIES",
                    message="index.json lists files not present in index.html table",
                    context={"names": only_json},
                )
            )

        # SGML reconciliation against submitted-document inventory.
        complete_artifact = draft.artifact_by_path(f"accession/{complete_name}")
        if complete_artifact is not None:
            sgml_docs = parse_sgml_documents(self.store.open_bytes(complete_artifact.sha256))
            draft.sgml_documents = sgml_docs
            accession_names = {
                a.logical_path.split("/", 1)[1]
                for a in draft.artifacts
                if a.logical_path.startswith("accession/")
            }
            html_submitted = {
                e["name"]
                for e in html_entries
                if e.get("name") and e.get("document_type", "").upper() not in {"", "GRAPHIC"}
            }
            # Exclude complete submission itself and known metadata from "submitted index".
            html_submitted = {
                n
                for n in html_submitted
                if n.lower() != complete_name.lower()
                and not n.lower().endswith(("-index.html", "-index.htm", "index.json"))
            }
            recon, recon_issues = reconcile_sgml_inventory(
                sgml_documents=sgml_docs,
                directory_names=json_names,
                html_submitted_names=html_submitted,
                accession_artifact_names=accession_names,
            )
            draft.sgml_reconciliation = recon
            draft.issues.extend(recon_issues)

        return draft

    def add_external_dependency(
        self,
        draft: BundleDraft,
        *,
        original_uri: str,
        data: bytes | None = None,
        sha256: str | None = None,
        byte_size: int | None = None,
        final_url: str | None = None,
        max_external_bytes: int,
    ) -> ArtifactRecord:
        if data is not None:
            if len(data) > max_external_bytes:
                draft.issues.append(
                    QualityIssue(
                        severity="fatal",
                        code="EXTERNAL_DEPENDENCY_SIZE_LIMIT_EXCEEDED",
                        message="external dependency exceeds MAX_EXTERNAL_DEPENDENCY_BYTES",
                        context={"uri": original_uri, "byte_size": len(data)},
                    )
                )
                raise RuntimeError(f"external dependency too large: {original_uri}")
            obj = self.store.put_bytes(data)
            sha256 = obj.sha256
            byte_size = obj.byte_size
        elif sha256 is None or byte_size is None:
            raise ValueError("add_external_dependency requires data or sha256+byte_size")
        elif byte_size > max_external_bytes:
            draft.issues.append(
                QualityIssue(
                    severity="fatal",
                    code="EXTERNAL_DEPENDENCY_SIZE_LIMIT_EXCEEDED",
                    message="external dependency exceeds MAX_EXTERNAL_DEPENDENCY_BYTES",
                    context={"uri": original_uri, "byte_size": byte_size},
                )
            )
            raise RuntimeError(f"external dependency too large: {original_uri}")

        uri_hash = sha256_of_uri(original_uri)
        basename = sanitize_basename(Path(original_uri).name or "dependency")
        logical_path = f"external/{uri_hash}/{basename}"
        existing = draft.artifact_by_path(logical_path)
        if existing is not None:
            return existing
        return self._put_object(
            draft,
            logical_path=logical_path,
            sha256=sha256,
            byte_size=byte_size,
            source_url=original_uri,
            final_url=final_url or original_uri,
            source_class="external_taxonomy_dependency",
            artifact_role="external_dts_document",
            required=True,
            in_payload=True,
        )


def build_manifest_dict(
    draft: BundleDraft,
    *,
    payload_hash_value: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "manifest_version": "1",
        "acquisition_policy_version": ACQUISITION_POLICY_VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "cik": draft.cik,
        "accession": draft.accession,
        "payload_hash": payload_hash_value,
        "archive_base": draft.archive_base,
        "artifacts": [a.to_dict() for a in sorted(draft.artifacts, key=lambda x: x.logical_path)],
        "quality_issues": [i.to_dict() for i in draft.issues],
        "discovery": draft.discovery,
        "issuer_provenance": draft.issuer_provenance,
        "sgml_reconciliation": draft.sgml_reconciliation,
        "sgml_documents": [d.to_dict() for d in draft.sgml_documents],
    }
    if extra:
        manifest.update(extra)
    return manifest


def write_manifest(
    path: Path,
    draft: BundleDraft,
    *,
    payload_hash_value: str,
    extra: dict[str, Any] | None = None,
) -> bytes:
    manifest = build_manifest_dict(draft, payload_hash_value=payload_hash_value, extra=extra)
    return write_json_atomic(path, manifest)


def commit_bundle(
    accession_root: Path,
    *,
    policy_version: str,
    payload_hash_value: str,
    staged_manifest: dict[str, Any],
) -> Path:
    """Atomically place an immutable bundle under bundles/<policy>/<payload_hash>/.

    - Same policy+payload: reuse the existing immutable bundle manifest.
    - Different payload: create a new bundle snapshot (legitimate).
    - Same path with different *payload* artifact identities: fatal integrity error.

    Regenerable / non-payload artifacts (e.g. offline catalog with absolute paths)
    are not part of bundle identity.
    """

    def payload_identity(manifest: dict[str, Any]) -> list[tuple[str, str, int]]:
        artifacts = manifest.get("artifacts") or []
        entries = [
            (a["logical_path"], a["sha256"], int(a["byte_size"]))
            for a in artifacts
            if a.get("in_payload", True)
        ]
        return sorted(entries, key=lambda item: item[0].encode("utf-8"))

    bundle_dir = accession_root / "bundles" / policy_version / payload_hash_value
    manifest_path = bundle_dir / "manifest.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in ("payload_hash", "acquisition_policy_version", "cik", "accession"):
            if existing.get(key) != staged_manifest.get(key):
                raise RuntimeError(
                    f"bundle integrity conflict at {manifest_path}: field {key} differs"
                )
        if payload_identity(existing) != payload_identity(staged_manifest):
            raise RuntimeError(
                f"bundle integrity conflict at {manifest_path}: payload artifacts differ"
            )
        return bundle_dir

    bundle_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(manifest_path, staged_manifest)
    return bundle_dir


def stage_and_commit_bundle(
    accession_root: Path,
    draft: BundleDraft,
    *,
    payload_hash_value: str,
    extra: dict[str, Any] | None = None,
) -> Path:
    tmp = accession_root / "tmp" / f"stage-{payload_hash_value[:12]}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest_dict(draft, payload_hash_value=payload_hash_value, extra=extra)
    write_json_atomic(tmp / "manifest.json", manifest)
    try:
        return commit_bundle(
            accession_root,
            policy_version=ACQUISITION_POLICY_VERSION,
            payload_hash_value=payload_hash_value,
            staged_manifest=manifest,
        )
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
