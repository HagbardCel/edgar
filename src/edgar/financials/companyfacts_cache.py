"""Cache companyfacts JSON through the shared SEC client and object store."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from edgar.config import Settings
from edgar.domain.identifiers import accession_to_cik, companyfacts_url, validate_cik
from edgar.sec.client import ControlledFetcher
from edgar.storage.objects import ObjectStore, StoredObject, write_bytes_atomic


def companyfacts_pointer_path(data_root: Path, cik: str) -> Path:
    return data_root / "companyfacts" / f"CIK{validate_cik(cik)}.sha256"


def cache_companyfacts(
    settings: Settings,
    cik: str,
    fetcher: ControlledFetcher,
) -> StoredObject:
    """Fetch one CIK and store the bytes by hash. Different bytes are not overwritten."""
    url = companyfacts_url(cik)
    store = ObjectStore(settings.edgar_data_root)
    _result, stored = fetcher.fetch_to_store(
        url,
        store,
        max_bytes=settings.max_file_bytes,
    )
    pointer = companyfacts_pointer_path(settings.edgar_data_root, cik)
    write_bytes_atomic(pointer, (stored.sha256 + "\n").encode("utf-8"))
    return stored


def distinct_ciks(accessions: Sequence[str]) -> tuple[str, ...]:
    """Zero-padded CIKs from accessions, first-seen order, duplicates removed."""
    seen: list[str] = []
    for accession in accessions:
        cik = accession_to_cik(accession)
        if cik not in seen:
            seen.append(cik)
    return tuple(seen)


def cache_companyfacts_for_accessions(
    settings: Settings,
    accessions: Sequence[str],
    fetcher: ControlledFetcher,
) -> tuple[StoredObject, ...]:
    """Populate the CAS for each distinct CIK using the caller's fetcher.

    ``edgar build`` does not call this. A quality report only reads the cache.
    """
    stored: list[StoredObject] = []
    for cik in distinct_ciks(accessions):
        stored.append(cache_companyfacts(settings, cik, fetcher))
    return tuple(stored)


def load_cached_companyfacts(data_root: Path, cik: str) -> bytes | None:
    pointer = companyfacts_pointer_path(data_root, cik)
    if not pointer.is_file():
        return None
    digest = pointer.read_text(encoding="utf-8").strip()
    if not digest:
        return None
    path = ObjectStore(data_root).path_for(digest)
    if not path.is_file():
        return None
    return path.read_bytes()
