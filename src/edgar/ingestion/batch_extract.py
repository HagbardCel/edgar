"""Extract one accession per worker process and write a sorted report.

Successful filings stay committed. A later failure does not roll them back.
The parent process always writes the report, then the caller exits non-zero
when any accession failed. Rerunning is safe because extract persistence is
idempotent.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from edgar.config import Settings
from edgar.domain.identifiers import accession_to_cik
from edgar.ingestion.source_extract import SourceExtractService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore, write_json_atomic
from edgar.xbrl.source_records import EXTRACTOR_VERSION


class BundleResolutionError(RuntimeError):
    """The accession does not resolve to exactly one published bundle."""


@dataclass(frozen=True)
class AccessionExtractRecord:
    accession: str
    success: bool
    wall_seconds: float
    fact_count: int | None
    declaration_count: int | None
    relationship_count: int | None
    extractor_version: str
    failure_class: str | None
    failure_message: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "accession": self.accession,
            "success": self.success,
            "wall_seconds": self.wall_seconds,
            "fact_count": self.fact_count,
            "declaration_count": self.declaration_count,
            "relationship_count": self.relationship_count,
            "extractor_version": self.extractor_version,
            "failure_class": self.failure_class,
            "failure_message": self.failure_message,
        }


@dataclass(frozen=True)
class BatchExtractResult:
    records: tuple[AccessionExtractRecord, ...]
    report_path: Path
    ok: bool


ExtractFn = Callable[[str, str, str], AccessionExtractRecord]


def extract_report_path(data_root: Path) -> Path:
    return data_root / "reports" / "p2-extract.json"


def extract_published_accession(
    data_root: Path,
    database_url: str,
    accession: str,
) -> AccessionExtractRecord:
    """Catalog and extract one published bundle in this process."""
    started = perf_counter()
    settings = Settings().model_copy(
        update={
            "edgar_data_root": data_root,
            "edgar_database_url": database_url,
        }
    )
    store = ObjectStore(data_root)
    repo = BundleRepository(data_root, store)
    published = repo.list_published(accession_to_cik(accession), accession)
    if len(published) != 1:
        raise BundleResolutionError(
            f"accession {accession} resolved to {len(published)} published bundles"
        )
    bundle_dir = published[0][0]
    service = SourceExtractService(settings)
    try:
        result = service.extract_published_bundle(bundle_dir)
    finally:
        engine = service._engine
        if engine is not None:
            engine.dispose()
    elapsed = perf_counter() - started
    declaration_count = sum(probe.declaration_count for probe in result.report_probes)
    relationship_count = sum(probe.relationship_count for probe in result.report_probes)
    return AccessionExtractRecord(
        accession=result.accession,
        success=True,
        wall_seconds=elapsed,
        fact_count=result.persist.fact_count,
        declaration_count=declaration_count,
        relationship_count=relationship_count,
        extractor_version=EXTRACTOR_VERSION,
        failure_class=None,
        failure_message=None,
    )


def _failure_record(accession: str, started: float, exc: BaseException) -> AccessionExtractRecord:
    return AccessionExtractRecord(
        accession=accession,
        success=False,
        wall_seconds=perf_counter() - started,
        fact_count=None,
        declaration_count=None,
        relationship_count=None,
        extractor_version=EXTRACTOR_VERSION,
        failure_class=type(exc).__name__,
        failure_message=str(exc),
    )


def _worker_job(job: tuple[str, str, str]) -> dict[str, object]:
    data_root, database_url, accession = job
    started = perf_counter()
    try:
        record = extract_published_accession(Path(data_root), database_url, accession)
    except Exception as exc:  # noqa: BLE001 — one accession must not kill the pool
        record = _failure_record(accession, started, exc)
    return record.to_dict()


def _record_from_dict(payload: dict[str, Any]) -> AccessionExtractRecord:
    return AccessionExtractRecord(
        accession=str(payload["accession"]),
        success=bool(payload["success"]),
        wall_seconds=float(payload["wall_seconds"]),
        fact_count=(None if payload["fact_count"] is None else int(payload["fact_count"])),
        declaration_count=(
            None if payload["declaration_count"] is None else int(payload["declaration_count"])
        ),
        relationship_count=(
            None if payload["relationship_count"] is None else int(payload["relationship_count"])
        ),
        extractor_version=str(payload["extractor_version"]),
        failure_class=(None if payload["failure_class"] is None else str(payload["failure_class"])),
        failure_message=(
            None if payload["failure_message"] is None else str(payload["failure_message"])
        ),
    )


def run_batch_extract(
    *,
    data_root: Path,
    database_url: str,
    accessions: Sequence[str],
    jobs: int = 1,
    report_path: Path | None = None,
    extract_fn: ExtractFn | None = None,
) -> BatchExtractResult:
    """Extract every accession and write a report sorted by accession.

    ``jobs`` defaults to 1 and runs in this process. ``jobs > 1`` uses a spawn
    pool. Each worker builds its own engine. ``extract_fn`` is for tests and
    runs only when ``jobs == 1``.
    """
    if jobs < 1:
        raise ValueError("jobs must be >= 1")
    if not accessions:
        raise ValueError("accession list is empty")
    if extract_fn is not None and jobs != 1:
        raise ValueError("extract_fn is only supported when jobs=1")

    destination = report_path or extract_report_path(data_root)
    if extract_fn is not None:
        raw_records = [
            extract_fn(str(data_root), database_url, accession).to_dict()
            for accession in accessions
        ]
    elif jobs == 1:
        raw_records = [
            _worker_job((str(data_root), database_url, accession)) for accession in accessions
        ]
    else:
        ctx = multiprocessing.get_context("spawn")
        jobs_payload = [(str(data_root), database_url, accession) for accession in accessions]
        with ProcessPoolExecutor(max_workers=jobs, mp_context=ctx) as pool:
            raw_records = list(pool.map(_worker_job, jobs_payload))

    records = tuple(
        sorted(
            (_record_from_dict(item) for item in raw_records),
            key=lambda record: record.accession,
        )
    )
    payload = {
        "extractor_version": EXTRACTOR_VERSION,
        "jobs": jobs,
        "accessions": [record.to_dict() for record in records],
    }
    write_json_atomic(destination, payload)
    ok = all(record.success for record in records)
    return BatchExtractResult(records=records, report_path=destination, ok=ok)


__all__ = [
    "AccessionExtractRecord",
    "BatchExtractResult",
    "BundleResolutionError",
    "extract_published_accession",
    "extract_report_path",
    "run_batch_extract",
]
