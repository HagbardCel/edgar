"""Exact-accession lookup from SEC submissions (recent + historical files)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from edgar.domain.identifiers import (
    SUPPORTED_FORMS,
    accession_to_cik,
    submissions_url,
    validate_accession,
    validate_cik,
)
from edgar.domain.issues import QualityIssue
from edgar.sec.client import ControlledFetcher
from edgar.storage.objects import ObjectStore


@dataclass(frozen=True)
class AccessionMetadata:
    cik: str
    accession: str
    form_type: str
    filing_date: date
    accepted_at: datetime | None
    report_period_end: date | None
    primary_document: str
    is_inline_xbrl: bool | None
    is_xbrl: bool | None
    submissions_content_sha256: str
    discovery: dict[str, Any]


def _parse_acceptance(value: str | None) -> datetime | None:
    if not value:
        return None
    # SEC uses YYYYMMDDHHMMSS
    if len(value) == 14 and value.isdigit():
        dt = datetime(
            int(value[0:4]),
            int(value[4:6]),
            int(value[6:8]),
            int(value[8:10]),
            int(value[10:12]),
            int(value[12:14]),
            tzinfo=UTC,
        )
        return dt
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def _record_from_arrays(recent: dict[str, Any], idx: int, accession: str) -> dict[str, Any]:
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
        "is_inline_xbrl": at("isInlineXBRL"),
        "is_xbrl": at("isXBRL"),
    }


def _find_in_filing_block(block: dict[str, Any], accession: str) -> dict[str, Any] | None:
    accessions = block.get("accessionNumber") or []
    try:
        idx = accessions.index(accession)
    except ValueError:
        return None
    return _record_from_arrays(block, idx, accession)


def lookup_accession_metadata(
    fetcher: ControlledFetcher,
    store: ObjectStore,
    accession: str,
    *,
    max_bytes: int,
) -> tuple[AccessionMetadata, list[QualityIssue]]:
    """Locate exact accession in recent filings or historical submission shards."""
    issues: list[QualityIssue] = []
    accession = validate_accession(accession)
    cik = accession_to_cik(accession)
    url = submissions_url(cik)
    result, obj = fetcher.fetch_to_store(url, store, max_bytes=max_bytes)
    payload = json.loads(store.open_bytes(obj.sha256))
    filings = payload.get("filings") or {}
    recent = filings.get("recent") or {}
    record = _find_in_filing_block(recent, accession)

    if record is None:
        for file_meta in filings.get("files") or []:
            name = file_meta.get("name")
            if not name:
                continue
            hist_url = f"https://data.sec.gov/submissions/{name}"
            _hr, hist_obj = fetcher.fetch_to_store(hist_url, store, max_bytes=max_bytes)
            hist = json.loads(store.open_bytes(hist_obj.sha256))
            # Historical files are themselves filing blocks (arrays).
            record = _find_in_filing_block(hist, accession)
            if record is None and "filings" in hist:
                recent_hist = (hist.get("filings") or {}).get("recent") or {}
                record = _find_in_filing_block(recent_hist, accession)
            if record is not None:
                # Prefer the shard that contained the accession for observation linkage;
                # discovery still excludes shard URL.
                obj = hist_obj
                result = _hr
                break

    if record is None:
        raise LookupError(f"accession {accession} not found in SEC submissions for CIK {cik}")

    form_type = str(record.get("form") or "")
    if form_type not in SUPPORTED_FORMS:
        raise ValueError(f"unsupported form_type {form_type!r} for accession {accession}")

    primary = str(record.get("primary_document") or "")
    if not primary:
        raise ValueError(f"missing primaryDocument for accession {accession}")

    filing_date = _parse_date(record.get("filing_date"))
    if filing_date is None:
        raise ValueError(f"missing filingDate for accession {accession}")

    discovery = {
        "cik": validate_cik(cik),
        "accession": accession,
        "form_type": form_type,
        "filing_date": filing_date.isoformat(),
        "accepted_at": None,
        "report_period_end": None,
        "primary_document": primary,
        "is_inline_xbrl": record.get("is_inline_xbrl"),
        "is_xbrl": record.get("is_xbrl"),
    }
    raw_accepted = record.get("acceptance_datetime")
    accepted = _parse_acceptance(str(raw_accepted) if raw_accepted is not None else None)
    if accepted is not None:
        discovery["accepted_at"] = accepted.isoformat()
    period = _parse_date(record.get("report_period"))
    if period is not None:
        discovery["report_period_end"] = period.isoformat()

    meta = AccessionMetadata(
        cik=validate_cik(cik),
        accession=accession,
        form_type=form_type,
        filing_date=filing_date,
        accepted_at=accepted,
        report_period_end=period,
        primary_document=primary,
        is_inline_xbrl=record.get("is_inline_xbrl"),
        is_xbrl=record.get("is_xbrl"),
        submissions_content_sha256=obj.sha256,
        discovery=discovery,
    )
    # Silence unused if fetch result only needed for observations by caller.
    _ = result
    return meta, issues
