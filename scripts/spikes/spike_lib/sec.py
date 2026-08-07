"""Shared SEC HTTP client and identifier helpers for spikes."""

from __future__ import annotations

import hashlib
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

import httpx

from spike_lib.quality import QualityIssue

if TYPE_CHECKING:
    from spike_lib.storage import ContentObject, ObjectStore

ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
CIK_DIGITS_RE = re.compile(r"^\d{1,10}$")


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    redirect_count: int
    sha256: str
    byte_size: int


class SizeLimitExceeded(RuntimeError):
    """Raised when a streamed response exceeds the configured byte limit."""


class NetworkDenied(RuntimeError):
    """Raised when the offline network guard blocks a connection attempt."""


class SecClient:
    def __init__(
        self,
        user_agent: str,
        *,
        min_interval_seconds: float = 0.2,
        max_redirects: int = 5,
        timeout_seconds: float = 60.0,
        max_retries: int = 4,
    ) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "SEC_USER_AGENT must identify the requester, e.g. 'Name email@example.com'"
            )
        self.user_agent = user_agent
        self.min_interval_seconds = min_interval_seconds
        self.max_redirects = max_redirects
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._last_request_at = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=timeout_seconds,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SecClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def fetch_to_store(
        self,
        url: str,
        store: ObjectStore,
        *,
        max_bytes: int,
    ) -> tuple[FetchResult, ContentObject]:
        """Stream a response into the object store with incremental hashing.

        One network read, one disk write, bounded memory. Retries discard any
        partial temporary file before retrying.
        """
        current = url
        redirect_count = 0
        for attempt in range(self.max_retries + 1):
            self._throttle()
            self._last_request_at = time.monotonic()
            try:
                with self._client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not location:
                            raise RuntimeError(f"redirect without Location from {current}")
                        redirect_count += 1
                        if redirect_count > self.max_redirects:
                            raise RuntimeError(
                                f"exceeded MAX_REDIRECTS={self.max_redirects} resolving {url}"
                            )
                        current = urljoin(current, location)
                        continue
                    if (
                        response.status_code in {429, 500, 502, 503, 504}
                        and attempt < self.max_retries
                    ):
                        backoff = (2**attempt) + random.uniform(0, 0.25)
                        time.sleep(backoff)
                        continue
                    response.raise_for_status()

                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared = int(content_length)
                        except ValueError:
                            declared = None
                        else:
                            if declared > max_bytes:
                                raise SizeLimitExceeded(
                                    f"Content-Length {declared} exceeds max_bytes={max_bytes}"
                                )

                    obj = store.put_stream(
                        response.iter_bytes(chunk_size=64 * 1024),
                        max_bytes=max_bytes,
                    )
                    headers = {k.lower(): v for k, v in response.headers.items()}
                    return (
                        FetchResult(
                            url=url,
                            final_url=str(response.url),
                            status_code=response.status_code,
                            headers=headers,
                            redirect_count=redirect_count,
                            sha256=obj.sha256,
                            byte_size=obj.byte_size,
                        ),
                        obj,
                    )
            except SizeLimitExceeded:
                raise
            except httpx.HTTPStatusError:
                raise
            except Exception:
                if attempt >= self.max_retries:
                    raise
                backoff = (2**attempt) + random.uniform(0, 0.25)
                time.sleep(backoff)
        raise RuntimeError(f"failed to fetch {url} after retries")


def validate_cik(cik: str) -> str:
    """Validate and normalize a CIK to a zero-padded ten-digit string."""
    if not isinstance(cik, str):
        raise ValueError(f"CIK must be a string, got {type(cik).__name__}")
    cleaned = cik.strip()
    if cleaned != cik or not cleaned:
        raise ValueError(f"CIK rejected (whitespace or empty): {cik!r}")
    if any(ch in cleaned for ch in "/\\."):
        raise ValueError(f"CIK rejected (path characters): {cik!r}")
    if cleaned.startswith(("+", "-")):
        raise ValueError(f"CIK rejected (signed): {cik!r}")
    if not CIK_DIGITS_RE.fullmatch(cleaned):
        raise ValueError(f"CIK must be 1-10 decimal digits: {cik!r}")
    return f"{int(cleaned):010d}"


def validate_accession(accession: str) -> str:
    """Validate accession in canonical dashed form."""
    if not isinstance(accession, str):
        raise ValueError(f"accession must be a string, got {type(accession).__name__}")
    cleaned = accession.strip()
    if cleaned != accession:
        raise ValueError(f"accession rejected (surrounding whitespace): {accession!r}")
    if not ACCESSION_RE.fullmatch(cleaned):
        raise ValueError(f"accession must match ^\\d{{10}}-\\d{{2}}-\\d{{6}}$: {accession!r}")
    return cleaned


def assert_cik_accession_consistent(cik: str, accession: str) -> None:
    """Fail when the accession prefix does not match the normalized CIK."""
    cik_n = validate_cik(cik)
    acc = validate_accession(accession)
    prefix = acc.split("-", 1)[0]
    if prefix != cik_n:
        raise ValueError(f"accession CIK prefix {prefix} does not match normalized CIK {cik_n}")


def assert_path_under(path: Path, root: Path) -> Path:
    """Resolve path and assert it is a strict descendant of root."""
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"path {resolved} escapes root {root_resolved}") from exc
    if resolved == root_resolved:
        raise ValueError(f"path {resolved} is not a strict descendant of {root_resolved}")
    return resolved


def normalize_cik(cik: str) -> str:
    return validate_cik(cik)


def cik_int(cik: str) -> int:
    return int(validate_cik(cik))


def accession_dashless(accession: str) -> str:
    return validate_accession(accession).replace("-", "")


def accession_archive_base(cik: str, accession: str) -> str:
    assert_cik_accession_consistent(cik, accession)
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik_int(cik)}/{accession_dashless(accession)}/"
    )


def submissions_url(cik: str) -> str:
    return f"https://data.sec.gov/submissions/CIK{validate_cik(cik)}.json"


def sanitize_basename(name: str) -> str:
    cleaned = name.replace("\\", "/").split("/")[-1].strip()
    if not cleaned or cleaned in {".", ".."}:
        return "unnamed"
    out = []
    for ch in cleaned:
        if ch.isalnum() or ch in {".", "-", "_"}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:180] or "unnamed"


def validate_logical_path(logical_path: str) -> str:
    if logical_path.startswith("/") or logical_path.startswith("\\"):
        raise ValueError(f"absolute logical path rejected: {logical_path}")
    parts = logical_path.split("/")
    if any(p in {"", ".", ".."} for p in parts):
        raise ValueError(f"unsafe logical path rejected: {logical_path}")
    return logical_path


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
    # Unknown origin stays unknown; never default to filer_submitted.
    if description or document_type:
        return "filer_submitted", "attachment"
    return "unknown", "unknown"


def extract_accession_record(
    submissions: dict[str, Any],
    accession: str,
) -> dict[str, Any] | None:
    recent = submissions.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    try:
        idx = accessions.index(accession)
    except ValueError:
        return None

    def at(key: str, default: Any = None) -> Any:
        values = recent.get(key, [])
        return values[idx] if idx < len(values) else default

    return {
        "accession": accession,
        "form": at("form"),
        "filing_date": at("filingDate"),
        "acceptance_datetime": at("acceptanceDateTime"),
        "report_period": at("reportDate"),
        "primary_document": at("primaryDocument"),
        "primary_doc_description": at("primaryDocDescription"),
        "file_number": at("fileNumber"),
        "film_number": at("filmNumber"),
        "items": at("items"),
        "size": at("size"),
        "is_xbrl": at("isXBRL"),
        "is_inline_xbrl": at("isInlineXBRL"),
    }


def missing_primary_issue(accession: str) -> QualityIssue:
    return QualityIssue(
        severity="fatal",
        code="MISSING_PRIMARY_DOCUMENT",
        message=f"primary document not found for accession {accession}",
        context={"accession": accession},
    )


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
