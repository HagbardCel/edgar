#!/usr/bin/env python3
"""Local real-corpus acceptance: coverage matrix over fixtures/corpus.toml.

Uses locally acquired bundles under EDGAR_DATA_ROOT and the normal EDGAR database.
Idempotent and non-destructive — does not truncate tables.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from edgar.config import Settings
from edgar.corpus_acceptance import (
    STANDARD_TAXONOMY_HOSTS,
    CanonicalSnapshot,
    CorpusProjection,
    canonical_snapshot,
    continuation_provenance_coverage,
    dimension_coverage,
    evaluate_class_a_requirements,
    extension_coverage,
    presentation_role_coverage,
    resolve_published_bundle,
    taxonomy_transition_coverage,
)
from edgar.corpus_manifest import load_corpus_manifest
from edgar.ingestion.catalog import CatalogService
from edgar.projection.document import DocumentProjectionService
from edgar.projection.semantic import SemanticProjectionService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORPUS_PATH = _REPO_ROOT / "fixtures" / "corpus.toml"


@dataclass
class PassResult:
    catalog_reused: bool
    semantic_reused: bool
    document_reused: bool
    bundle_id: int
    semantic_projection_id: int
    document_projection_id: int
    concept_declaration_count: int | None
    fact_count: int | None


@dataclass
class FilingRunStatus:
    role: str
    company: str
    cik: str
    accession: str
    form: str
    industry_group: str
    bundle_found: bool = False
    bundle_dir: str | None = None
    bundle_candidates: list[dict[str, str]] = field(default_factory=list)
    cataloged: bool = False
    semantic_projected: bool = False
    document_projected: bool = False
    concept_declaration_count: int | None = None
    fact_count: int | None = None
    first_pass: PassResult | None = None
    second_pass: PassResult | None = None
    idempotent: bool = False
    errors: list[str] = field(default_factory=list)


def _snapshot_dict(snapshot: CanonicalSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def _run_pipeline(
    *,
    bundle_dir: Path,
    catalog: CatalogService,
    semantic: SemanticProjectionService,
    document: DocumentProjectionService,
) -> PassResult:
    cat = catalog.catalog_published_bundle(bundle_dir)
    sem = semantic.project_published_bundle(bundle_dir)
    doc = document.project_published_bundle(bundle_dir)
    return PassResult(
        catalog_reused=cat.reused,
        semantic_reused=sem.projection.reused,
        document_reused=doc.projection.reused,
        bundle_id=cat.bundle_id,
        semantic_projection_id=sem.projection.projection_id,
        document_projection_id=doc.projection.projection_id,
        concept_declaration_count=sem.projection.counts.get("concept_declarations"),
        fact_count=sem.projection.counts.get("facts"),
    )


def _verify_idempotency(first: PassResult, second: PassResult, snapshots_match: bool) -> bool:
    return (
        second.catalog_reused
        and second.semantic_reused
        and second.document_reused
        and first.bundle_id == second.bundle_id
        and first.semantic_projection_id == second.semantic_projection_id
        and first.document_projection_id == second.document_projection_id
        and snapshots_match
    )


def run_acceptance() -> dict[str, Any]:
    settings = Settings()
    data_root = settings.edgar_data_root
    manifest = load_corpus_manifest(_CORPUS_PATH)

    store = ObjectStore(data_root)
    repo = BundleRepository(data_root, store)
    engine = create_engine(settings.require_database_url(), future=True)

    catalog = CatalogService(settings, engine=engine, bundles=repo)
    semantic = SemanticProjectionService(settings, engine=engine, bundles=repo)
    document = DocumentProjectionService(settings, engine=engine, bundles=repo)

    statuses: list[FilingRunStatus] = []
    projections: list[CorpusProjection] = []

    for filing in manifest.filings:
        status = FilingRunStatus(
            role=filing.role,
            company=filing.company,
            cik=filing.cik,
            accession=filing.accession,
            form=filing.form,
            industry_group=filing.industry_group,
        )
        resolution = resolve_published_bundle(repo, filing.cik, filing.accession)
        status.bundle_candidates = [dict(c) for c in resolution.candidates]
        if resolution.error is not None:
            status.errors.append(resolution.error)
            statuses.append(status)
            continue

        assert resolution.bundle_dir is not None
        status.bundle_found = True
        status.bundle_dir = str(resolution.bundle_dir)

        try:
            first = _run_pipeline(
                bundle_dir=resolution.bundle_dir,
                catalog=catalog,
                semantic=semantic,
                document=document,
            )
            status.first_pass = first
            status.cataloged = True
            status.semantic_projected = True
            status.document_projected = True
            status.concept_declaration_count = first.concept_declaration_count
            status.fact_count = first.fact_count

            with engine.connect() as conn:
                first_snapshot = _snapshot_dict(
                    canonical_snapshot(
                        conn,
                        CorpusProjection(
                            role=filing.role,
                            company=filing.company,
                            cik=filing.cik,
                            accession=filing.accession,
                            form=filing.form,
                            industry_group=filing.industry_group,
                            bundle_id=first.bundle_id,
                            semantic_projection_id=first.semantic_projection_id,
                            document_projection_id=first.document_projection_id,
                        ),
                    )
                )

            second = _run_pipeline(
                bundle_dir=resolution.bundle_dir,
                catalog=catalog,
                semantic=semantic,
                document=document,
            )
            status.second_pass = second

            with engine.connect() as conn:
                corpus_projection = CorpusProjection(
                    role=filing.role,
                    company=filing.company,
                    cik=filing.cik,
                    accession=filing.accession,
                    form=filing.form,
                    industry_group=filing.industry_group,
                    bundle_id=second.bundle_id,
                    semantic_projection_id=second.semantic_projection_id,
                    document_projection_id=second.document_projection_id,
                )
                second_snapshot = _snapshot_dict(canonical_snapshot(conn, corpus_projection))

            status.idempotent = _verify_idempotency(
                first, second, first_snapshot == second_snapshot
            )
            if not status.idempotent:
                status.errors.append("idempotency check failed on second pass")

            projections.append(corpus_projection)
        except Exception as exc:  # noqa: BLE001
            status.errors.append(str(exc))

        statuses.append(status)

    coverage: dict[str, Any] = {}
    class_a: dict[str, Any] = {"requirements": {}, "unmet": ["no successful projections"]}
    if projections:
        projection_tuple = tuple(projections)
        with engine.connect() as conn:
            ext = extension_coverage(conn, projection_tuple)
            dims = dimension_coverage(conn, projection_tuple)
            roles = presentation_role_coverage(conn, projection_tuple)
            tax = taxonomy_transition_coverage(conn, projection_tuple)
            cont = continuation_provenance_coverage(conn, projection_tuple)
        coverage = {
            "extensions": ext,
            "dimensions": dims,
            "presentation_roles": roles,
            "taxonomy_transition": tax,
            "continuation_provenance": cont,
            "standard_taxonomy_hosts": sorted(STANDARD_TAXONOMY_HOSTS),
        }
        class_a = evaluate_class_a_requirements(
            projection_tuple,
            extension=ext,
            dimensions=dims,
            presentation_roles=roles,
            taxonomy=tax,
        )

    all_ready = all(
        s.bundle_found
        and s.cataloged
        and s.semantic_projected
        and s.document_projected
        and s.idempotent
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
                "industry_group": s.industry_group,
                "bundle_found": s.bundle_found,
                "bundle_dir": s.bundle_dir,
                "bundle_candidates": s.bundle_candidates,
                "cataloged": s.cataloged,
                "semantic_projected": s.semantic_projected,
                "document_projected": s.document_projected,
                "concept_declaration_count": s.concept_declaration_count,
                "fact_count": s.fact_count,
                "first_pass": None if s.first_pass is None else asdict(s.first_pass),
                "second_pass": None if s.second_pass is None else asdict(s.second_pass),
                "idempotent": s.idempotent,
                "errors": s.errors,
            }
            for s in statuses
        ],
        "coverage": coverage,
        "class_a_requirements": class_a,
        "phase1d_readiness": {
            "all_filings_projected_and_idempotent": all_ready,
            "class_a_met": not class_a.get("unmet"),
        },
        "acceptance_gates": {
            "A_real_corpus": class_a.get("requirements", {}),
            "B_committed_tests": "make phase1-acceptance (contract + integration)",
            "C_informational": ["continuation_provenance", "real_corpus_awkward_html"],
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
            f"\nMissing or ambiguous local bundles for: {', '.join(missing)}. "
            "Acquire with `edgar filings retrieve --accession ...` first.",
            file=sys.stderr,
        )
        return 2

    if any(f["errors"] for f in report["filings"]):
        return 3

    if report["class_a_requirements"].get("unmet"):
        print(
            f"\nUnmet class-A requirements: {', '.join(report['class_a_requirements']['unmet'])}",
            file=sys.stderr,
        )
        return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
