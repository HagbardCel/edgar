"""Shared SEC HTTP client for spikes."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from spike_lib.quality import QualityIssue


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content: bytes
    headers: dict[str, str]
    redirect_count: int


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
                "SEC_USER_AGENT must identify the requester, e.g. "
                "'Name email@example.com'"
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

    def get(self, url: str) -> FetchResult:
        current = url
        redirect_count = 0
        for attempt in range(self.max_retries + 1):
            self._throttle()
            self._last_request_at = time.monotonic()
            response = self._client.get(current)
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
            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                backoff = (2**attempt) + random.uniform(0, 0.25)
                time.sleep(backoff)
                continue
            response.raise_for_status()
            return FetchResult(
                url=url,
                final_url=str(response.url),
                status_code=response.status_code,
                content=bytes(response.content),
                headers={k.lower(): v for k, v in response.headers.items()},
                redirect_count=redirect_count,
            )
        raise RuntimeError(f"failed to fetch {url} after retries")


def cik_int(cik: str) -> int:
    return int(cik)


def normalize_cik(cik: str) -> str:
    return f"{int(cik):010d}"


def accession_dashless(accession: str) -> str:
    return accession.replace("-", "")


def accession_archive_base(cik: str, accession: str) -> str:
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int(cik)}/{accession_dashless(accession)}/"
    )


def submissions_url(cik: str) -> str:
    return f"https://data.sec.gov/submissions/CIK{normalize_cik(cik)}.json"


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


def classify_source_and_role(
    filename: str,
    *,
    accession: str,
    description: str | None = None,
    document_type: str | None = None,
) -> tuple[str, str]:
    lower = filename.lower()
    dashless = accession_dashless(accession).lower()
    if lower == f"{dashless}.txt" or lower.endswith(f"{accession.lower()}.txt"):
        return "filer_submitted", "complete_submission"
    if lower.endswith("-index.json") or lower == "index.json":
        return "sec_submission_metadata", "index_json"
    if "index-headers" in lower:
        return "sec_submission_metadata", "index_headers"
    if lower.endswith("-index.html") or lower.endswith("-index.htm"):
        return "sec_submission_metadata", "index_html"
    if lower.endswith(".xsd"):
        return "filer_submitted", "taxonomy_schema"
    if lower.endswith("_pre.xml") or lower.endswith("_cal.xml") or lower.endswith("_def.xml"):
        return "filer_submitted", "linkbase"
    if lower.endswith("_lab.xml") or lower.endswith("_ref.xml"):
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
    return "filer_submitted", "attachment"


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
