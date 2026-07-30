"""Accession mirroring and payload construction for Slice 0."""

from __future__ import annotations

import json
import re
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
    accession_archive_base,
    accession_dashless,
    classify_source_and_role,
    extract_accession_record,
    normalize_cik,
    sanitize_basename,
    submissions_url,
    validate_logical_path,
)
from spike_lib.storage import ObjectStore


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
class BundleDraft:
    cik: str
    accession: str
    archive_base: str
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)
    discovery: dict[str, Any] = field(default_factory=dict)
    index_entries: list[dict[str, Any]] = field(default_factory=list)
    primary_document: str | None = None

    def artifact_by_path(self, logical_path: str) -> ArtifactRecord | None:
        for artifact in self.artifacts:
            if artifact.logical_path == logical_path:
                return artifact
        return None

    def payload_entries(self) -> list[tuple[str, str, int]]:
        return [
            (a.logical_path, a.sha256, a.byte_size)
            for a in self.artifacts
            if a.in_payload
        ]

    def compute_payload_hash(self) -> str:
        return payload_hash(self.payload_entries())


def _parse_index_json(content: bytes, archive_base: str) -> list[dict[str, Any]]:
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


def _parse_index_html(content: bytes, archive_base: str) -> list[dict[str, Any]]:
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
        # SEC sometimes prefixes /ix?doc=/Archives/...
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

    def _put(
        self,
        draft: BundleDraft,
        *,
        logical_path: str,
        data: bytes,
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
        if len(data) > self.max_file_bytes:
            draft.issues.append(
                QualityIssue(
                    severity="fatal",
                    code="FILE_SIZE_LIMIT_EXCEEDED",
                    message=f"file exceeds MAX_FILE_BYTES ({self.max_file_bytes})",
                    context={"logical_path": logical_path, "byte_size": len(data)},
                )
            )
            raise RuntimeError(f"file size limit exceeded for {logical_path}")

        existing = draft.artifact_by_path(logical_path)
        if existing is not None:
            return existing

        obj = self.store.put_bytes(data)
        artifact = ArtifactRecord(
            logical_path=logical_path,
            sha256=obj.sha256,
            byte_size=obj.byte_size,
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

    def acquire(self, cik: str, accession: str) -> BundleDraft:
        cik_n = normalize_cik(cik)
        archive_base = accession_archive_base(cik_n, accession)
        draft = BundleDraft(cik=cik_n, accession=accession, archive_base=archive_base)

        # Raw submissions (provenance only; excluded from payload_hash).
        submissions_fetch = self.client.get(submissions_url(cik_n))
        submissions = json.loads(submissions_fetch.content.decode("utf-8"))
        self._put(
            draft,
            logical_path="metadata/submissions.raw.json",
            data=submissions_fetch.content,
            source_url=submissions_fetch.url,
            final_url=submissions_fetch.final_url,
            source_class="sec_submission_metadata",
            artifact_role="submissions_raw",
            in_payload=False,
            required=False,
            content_type=submissions_fetch.headers.get("content-type"),
            notes="Excluded from payload_hash; issuer submissions mutate over time.",
        )

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
            "company_name": submissions.get("name"),
            "is_inline_xbrl": accession_meta.get("is_inline_xbrl"),
            "is_xbrl": accession_meta.get("is_xbrl"),
        }
        discovery_bytes = json.dumps(
            draft.discovery,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8") + b"\n"
        self._put(
            draft,
            logical_path="metadata/discovery.json",
            data=discovery_bytes,
            source_url=None,
            final_url=None,
            source_class="sec_submission_metadata",
            artifact_role="discovery_record",
            in_payload=True,
            content_type="application/json",
        )

        # Directory index JSON
        index_json_url = urljoin(archive_base, "index.json")
        index_json_fetch = self.client.get(index_json_url)
        self._put(
            draft,
            logical_path="metadata/index.json",
            data=index_json_fetch.content,
            source_url=index_json_fetch.url,
            final_url=index_json_fetch.final_url,
            source_class="sec_submission_metadata",
            artifact_role="index_json",
            content_type=index_json_fetch.headers.get("content-type"),
        )
        json_entries = _parse_index_json(index_json_fetch.content, archive_base)

        # Index HTML / headers
        dashless = accession_dashless(accession)
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
                fetched = self.client.get(url)
            except Exception as exc:  # noqa: BLE001
                draft.issues.append(
                    QualityIssue(
                        severity="warning",
                        code="INDEX_METADATA_FETCH_FAILED",
                        message=str(exc),
                        context={"url": url, "role": role},
                    )
                )
                continue
            self._put(
                draft,
                logical_path=logical_path,
                data=fetched.content,
                source_url=fetched.url,
                final_url=fetched.final_url,
                source_class="sec_submission_metadata",
                artifact_role=role,
                content_type=fetched.headers.get("content-type"),
            )

        html_entries: list[dict[str, Any]] = []
        index_html_artifact = draft.artifact_by_path("metadata/index.html")
        if index_html_artifact is not None:
            html_entries = _parse_index_html(
                self.store.open_bytes(index_html_artifact.sha256),
                archive_base,
            )

        # Merge inventories by basename.
        by_name: dict[str, dict[str, Any]] = {}
        for entry in json_entries:
            by_name[entry["name"]] = {**entry, "from_json": True}
        for entry in html_entries:
            current = by_name.get(entry["name"], {"name": entry["name"], "url": entry["url"]})
            current.update({k: v for k, v in entry.items() if v})
            current["from_html"] = True
            by_name[entry["name"]] = current

        draft.index_entries = sorted(by_name.values(), key=lambda e: e["name"])

        # Download every accession-directory file from index.json (authoritative listing).
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
            fetched = self.client.get(url)
            self._put(
                draft,
                logical_path=f"accession/{name}",
                data=fetched.content,
                source_url=fetched.url,
                final_url=fetched.final_url,
                source_class=source_class,
                artifact_role=artifact_role,
                content_type=fetched.headers.get("content-type"),
                sec_sequence=meta.get("sequence"),
                sec_document_type=meta.get("document_type"),
                sec_description=meta.get("description"),
                required=True,
            )

        # Completeness checks
        complete_name = f"{dashless}.txt"
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

        # Inventory reconciliation notes
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

        return draft

    def add_external_dependency(
        self,
        draft: BundleDraft,
        *,
        original_uri: str,
        data: bytes,
        final_url: str | None = None,
        max_external_bytes: int,
    ) -> ArtifactRecord:
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

        uri_hash = sha256_of_uri(original_uri)
        basename = sanitize_basename(Path(original_uri).name or "dependency")
        logical_path = f"external/{uri_hash}/{basename}"
        existing = draft.artifact_by_path(logical_path)
        if existing is not None:
            return existing
        return self._put(
            draft,
            logical_path=logical_path,
            data=data,
            source_url=original_uri,
            final_url=final_url or original_uri,
            source_class="external_taxonomy_dependency",
            artifact_role="external_dts_document",
            required=True,
            in_payload=True,
        )


def write_manifest(
    path: Path,
    draft: BundleDraft,
    *,
    payload_hash_value: str,
    extra: dict[str, Any] | None = None,
) -> bytes:
    manifest = {
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
    }
    if extra:
        manifest.update(extra)
    data = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data
