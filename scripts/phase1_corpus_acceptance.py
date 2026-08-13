#!/usr/bin/env python3
"""Local real-corpus acceptance: coverage matrix over fixtures/corpus.yaml.

Uses locally acquired bundles under EDGAR_DATA_ROOT and the normal EDGAR database.
Idempotent and non-destructive — does not truncate tables.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from edgar.config import Settings
from edgar.ingestion.catalog import CatalogService
from edgar.projection.document import DocumentProjectionService
from edgar.projection.semantic import SemanticProjectionService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORPUS_PATH = _REPO_ROOT / "fixtures" / "corpus.yaml"


@dataclass
class FilingStatus:
    role: str
    company: str
    cik: str
    accession: str
    form: str
    bundle_found: bool = False
    bundle_dir: str | None = None
    cataloged: bool = False
    semantic_projected: bool = False
    document_projected: bool = False
    concept_count: int | None = None
    fact_count: int | None = None
    errors: list[str] = field(default_factory=list)


def _parse_corpus_yaml(text: str) -> dict[str, Any]:
    """Minimal parser for fixtures/corpus.yaml (avoids PyYAML dependency)."""
    filings: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("- role:"):
            if current is not None:
                filings.append(current)
            current = {"role": line.split(":", 1)[1].strip()}
            continue
        if current is None:
            continue
        for key in ("company", "cik", "accession", "form", "filed", "amends"):
            if line.startswith(f"{key}:"):
                current[key] = line.split(":", 1)[1].strip().strip('"')
                break
    if current is not None:
        filings.append(current)
    return {"filings": filings}


def _load_corpus() -> dict[str, Any]:
    return _parse_corpus_yaml(_CORPUS_PATH.read_text(encoding="utf-8"))


def _find_published_bundle(
    repo: BundleRepository, cik: str, accession: str
) -> tuple[Path, Any] | None:
    published = repo.list_published(cik, accession)
    if not published:
        return None
    return published[0]


def _coverage_requirements(filings: list[FilingStatus]) -> dict[str, Any]:
    by_role = {f.role: f for f in filings}
    return {
        "two_10k": [
            name
            for name in (
                by_role.get("base_10k", FilingStatus("", "", "", "", "")).company,
                by_role.get("second_10k", FilingStatus("", "", "", "", "")).company,
            )
            if name
        ],
        "two_10q": [
            name
            for name in (
                by_role.get("first_10q", FilingStatus("", "", "", "", "")).company,
                by_role.get("second_10q", FilingStatus("", "", "", "", "")).company,
            )
            if name
        ],
        "amendment": [
            by_role["amendment_10ka"].company
            if "amendment_10ka" in by_role and by_role["amendment_10ka"].bundle_found
            else None
        ],
        "taxonomy_transition": [],
        "extension_concepts": [
            f.company for f in filings if f.semantic_projected and (f.concept_count or 0) > 0
        ],
        "dimensions": [
            f.company for f in filings if f.role == "first_10q" and f.semantic_projected
        ],
    }


def run_acceptance() -> dict[str, Any]:
    settings = Settings()
    data_root = settings.edgar_data_root
    corpus = _load_corpus()
    filings_cfg = corpus.get("filings") or []

    store = ObjectStore(data_root)
    repo = BundleRepository(data_root, store)
    engine = create_engine(settings.require_database_url(), future=True)

    catalog = CatalogService(settings, engine=engine, bundles=repo)
    semantic = SemanticProjectionService(settings, engine=engine, bundles=repo)
    document = DocumentProjectionService(settings, engine=engine, bundles=repo)

    statuses: list[FilingStatus] = []
    for entry in filings_cfg:
        status = FilingStatus(
            role=str(entry.get("role", "")),
            company=str(entry.get("company", "")),
            cik=str(entry["cik"]),
            accession=str(entry["accession"]),
            form=str(entry.get("form", "")),
        )
        found = _find_published_bundle(repo, status.cik, status.accession)
        if found is None:
            status.errors.append("bundle not found under EDGAR_DATA_ROOT")
            statuses.append(status)
            continue

        bundle_dir, _bundle = found
        status.bundle_found = True
        status.bundle_dir = str(bundle_dir)

        try:
            catalog.catalog_published_bundle(bundle_dir)
            status.cataloged = True
        except Exception as exc:  # noqa: BLE001
            status.errors.append(f"catalog failed: {exc}")
            statuses.append(status)
            continue

        try:
            sem = semantic.project_published_bundle(bundle_dir)
            status.semantic_projected = sem.projection.status in {"complete", "incomplete"}
            status.concept_count = sem.projection.counts.get("concepts")
            status.fact_count = sem.projection.counts.get("facts")
        except Exception as exc:  # noqa: BLE001
            status.errors.append(f"semantic projection failed: {exc}")

        try:
            doc = document.project_published_bundle(bundle_dir)
            status.document_projected = doc.projection.status in {"complete", "incomplete"}
        except Exception as exc:  # noqa: BLE001
            status.errors.append(f"document projection failed: {exc}")

        try:
            catalog.catalog_published_bundle(bundle_dir)
        except Exception as exc:  # noqa: BLE001
            status.errors.append(f"idempotent catalog failed: {exc}")

        statuses.append(status)

    requirements = _coverage_requirements(statuses)
    all_ready = all(
        s.bundle_found and s.cataloged and s.semantic_projected and s.document_projected
        for s in statuses
    )

    return {
        "data_root": str(data_root),
        "corpus_path": str(_CORPUS_PATH),
        "filings": [
            {
                "role": s.role,
                "company": s.company,
                "cik": s.cik,
                "accession": s.accession,
                "form": s.form,
                "bundle_found": s.bundle_found,
                "bundle_dir": s.bundle_dir,
                "cataloged": s.cataloged,
                "semantic_projected": s.semantic_projected,
                "document_projected": s.document_projected,
                "concept_count": s.concept_count,
                "fact_count": s.fact_count,
                "errors": s.errors,
            }
            for s in statuses
        ],
        "requirements": requirements,
        "phase2_readiness": {
            "all_filings_projected": all_ready,
            "note": (
                "Mapping evidence requires semantic projections with concept/fact counts; "
                "run after local corpus acquisition."
            ),
        },
    }


def main() -> int:
    try:
        with create_engine(Settings().require_database_url()).connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        print(f"database unavailable: {exc}", file=sys.stderr)
        return 1

    report = run_acceptance()
    print(json.dumps(report, indent=2, sort_keys=True))
    missing = [f["accession"] for f in report["filings"] if not f["bundle_found"]]
    if missing:
        print(
            f"\nMissing local bundles for: {', '.join(missing)}. "
            "Acquire with `edgar filings retrieve --accession ...` first.",
            file=sys.stderr,
        )
        return 2
    if any(f["errors"] for f in report["filings"]):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
