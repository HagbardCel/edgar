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

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from edgar.config import Settings
from edgar.corpus_acceptance import (
    STANDARD_TAXONOMY_HOSTS,
    AcceptanceIssue,
    CanonicalSnapshot,
    CorpusProjection,
    canonical_snapshot,
    continuation_provenance_coverage,
    coverage_unmet_issues,
    dimension_coverage,
    evaluate_class_a_requirements,
    extension_coverage,
    presentation_role_coverage,
    resolve_published_bundle,
    taxonomy_transition_coverage,
    validate_corpus_bundle_identity,
)
from edgar.corpus_manifest import CorpusManifest, load_corpus_manifest
from edgar.db.check import DatabaseRevisionMismatch, require_database_at_head
from edgar.ingestion.catalog import CatalogService
from edgar.projection.document import DocumentProjectionError, DocumentProjectionService
from edgar.projection.semantic import SemanticProjectionError, SemanticProjectionService
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
    issues: list[AcceptanceIssue] = field(default_factory=list)


def _snapshot_dict(snapshot: CanonicalSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def _issue_dict(issue: AcceptanceIssue) -> dict[str, str]:
    return issue.to_dict()


def _empty_report(settings: Settings) -> dict[str, Any]:
    return {
        "issues": [],
        "data_root": str(settings.edgar_data_root),
        "corpus_path": str(_CORPUS_PATH),
        "filings": [],
        "coverage": {},
        "class_a_requirements": {"requirements": {}, "checks": {}, "unmet": []},
        "phase1d_readiness": {
            "all_filings_projected_and_idempotent": False,
            "class_a_met": False,
        },
        "acceptance_gates": {
            "A_real_corpus": {},
            "B_committed_tests": "make phase1-acceptance (unit + contract + integration)",
            "C_informational": ["continuation_provenance", "real_corpus_awkward_html"],
        },
    }


def _run_pipeline_pass(
    *,
    bundle_dir: Path,
    catalog: CatalogService,
    semantic: SemanticProjectionService,
    document: DocumentProjectionService,
    source: str,
) -> tuple[PassResult | None, list[AcceptanceIssue]]:
    issues: list[AcceptanceIssue] = []
    try:
        cat = catalog.catalog_published_bundle(bundle_dir)
    except Exception as exc:  # noqa: BLE001
        issues.append(
            AcceptanceIssue(
                component="catalog",
                code="CATALOG_FAILED",
                message=str(exc),
                source=source,
            )
        )
        return None, issues

    try:
        sem = semantic.project_published_bundle(bundle_dir)
    except SemanticProjectionError as exc:
        issues.append(
            AcceptanceIssue(
                component="semantic",
                code="SEMANTIC_PROJECTION_FAILED",
                message=str(exc),
                source=source,
            )
        )
        return None, issues
    except Exception as exc:  # noqa: BLE001
        issues.append(
            AcceptanceIssue(
                component="semantic",
                code="SEMANTIC_PROJECTION_FAILED",
                message=str(exc),
                source=source,
            )
        )
        return None, issues

    try:
        doc = document.project_published_bundle(bundle_dir)
    except DocumentProjectionError as exc:
        issues.append(
            AcceptanceIssue(
                component="document",
                code="DOCUMENT_PROJECTION_FAILED",
                message=str(exc),
                source=source,
            )
        )
        return None, issues
    except Exception as exc:  # noqa: BLE001
        issues.append(
            AcceptanceIssue(
                component="document",
                code="DOCUMENT_PROJECTION_FAILED",
                message=str(exc),
                source=source,
            )
        )
        return None, issues

    return (
        PassResult(
            catalog_reused=cat.reused,
            semantic_reused=sem.projection.reused,
            document_reused=doc.projection.reused,
            bundle_id=cat.bundle_id,
            semantic_projection_id=sem.projection.projection_id,
            document_projection_id=doc.projection.projection_id,
            concept_declaration_count=sem.projection.counts.get("concept_declarations"),
            fact_count=sem.projection.counts.get("facts"),
        ),
        [],
    )


def _idempotency_issues(
    first: PassResult,
    second: PassResult,
    *,
    snapshots_match: bool,
    source: str,
) -> list[AcceptanceIssue]:
    issues: list[AcceptanceIssue] = []
    if not second.catalog_reused:
        issues.append(
            AcceptanceIssue(
                component="idempotency",
                code="SECOND_PASS_CATALOG_NOT_REUSED",
                message="second catalog pass did not reuse existing bundle catalog rows",
                source=source,
            )
        )
    if not second.semantic_reused:
        issues.append(
            AcceptanceIssue(
                component="idempotency",
                code="SECOND_PASS_SEMANTIC_NOT_REUSED",
                message="second semantic projection pass did not reuse existing projection",
                source=source,
            )
        )
    if not second.document_reused:
        issues.append(
            AcceptanceIssue(
                component="idempotency",
                code="SECOND_PASS_DOCUMENT_NOT_REUSED",
                message="second document projection pass did not reuse existing projection",
                source=source,
            )
        )
    if first.bundle_id != second.bundle_id:
        issues.append(
            AcceptanceIssue(
                component="idempotency",
                code="BUNDLE_ID_CHANGED",
                message=f"bundle_id changed from {first.bundle_id} to {second.bundle_id}",
                source=source,
            )
        )
    if first.semantic_projection_id != second.semantic_projection_id:
        issues.append(
            AcceptanceIssue(
                component="idempotency",
                code="SEMANTIC_PROJECTION_ID_CHANGED",
                message=(
                    "semantic_projection_id changed from "
                    f"{first.semantic_projection_id} to {second.semantic_projection_id}"
                ),
                source=source,
            )
        )
    if first.document_projection_id != second.document_projection_id:
        issues.append(
            AcceptanceIssue(
                component="idempotency",
                code="DOCUMENT_PROJECTION_ID_CHANGED",
                message=(
                    "document_projection_id changed from "
                    f"{first.document_projection_id} to {second.document_projection_id}"
                ),
                source=source,
            )
        )
    if not snapshots_match:
        issues.append(
            AcceptanceIssue(
                component="idempotency",
                code="CANONICAL_SNAPSHOT_CHANGED",
                message="canonical snapshot counts changed between first and second pass",
                source=source,
            )
        )
    return issues


def _filing_report(status: FilingRunStatus) -> dict[str, Any]:
    return {
        "role": status.role,
        "company": status.company,
        "cik": status.cik,
        "accession": status.accession,
        "form": status.form,
        "industry_group": status.industry_group,
        "bundle_found": status.bundle_found,
        "bundle_dir": status.bundle_dir,
        "bundle_candidates": status.bundle_candidates,
        "cataloged": status.cataloged,
        "semantic_projected": status.semantic_projected,
        "document_projected": status.document_projected,
        "concept_declaration_count": status.concept_declaration_count,
        "fact_count": status.fact_count,
        "first_pass": None if status.first_pass is None else asdict(status.first_pass),
        "second_pass": None if status.second_pass is None else asdict(status.second_pass),
        "idempotent": status.idempotent,
        "issues": [_issue_dict(issue) for issue in status.issues],
    }


def run_acceptance(settings: Settings, manifest: CorpusManifest) -> dict[str, Any]:
    data_root = settings.edgar_data_root
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
            status.issues.append(
                AcceptanceIssue(
                    component="resolution",
                    code=resolution.error_code or "BUNDLE_NOT_FOUND",
                    message=resolution.error,
                    source=str(data_root / "bundles"),
                )
            )
            statuses.append(status)
            continue

        assert resolution.bundle_dir is not None
        assert resolution.bundle is not None
        bundle_dir = resolution.bundle_dir
        source = str(bundle_dir)
        status.bundle_found = True
        status.bundle_dir = source

        identity_issues = validate_corpus_bundle_identity(
            filing,
            resolution.bundle,
            manifest,
            source=source,
        )
        if identity_issues:
            status.issues.extend(identity_issues)
            statuses.append(status)
            continue

        resolved_form = resolution.bundle.filing.form_type

        first, first_issues = _run_pipeline_pass(
            bundle_dir=bundle_dir,
            catalog=catalog,
            semantic=semantic,
            document=document,
            source=source,
        )
        if first_issues:
            status.issues.extend(first_issues)
            failed_components = {issue.component for issue in first_issues}
            status.cataloged = "catalog" not in failed_components
            status.semantic_projected = status.cataloged and "semantic" not in failed_components
            status.document_projected = (
                status.semantic_projected and "document" not in failed_components
            )
            statuses.append(status)
            continue

        assert first is not None
        status.first_pass = first
        status.cataloged = True
        status.semantic_projected = True
        status.document_projected = True
        status.concept_declaration_count = first.concept_declaration_count
        status.fact_count = first.fact_count

        first_projection = CorpusProjection(
            role=filing.role,
            company=filing.company,
            cik=filing.cik,
            accession=filing.accession,
            form=resolved_form,
            industry_group=filing.industry_group,
            bundle_id=first.bundle_id,
            semantic_projection_id=first.semantic_projection_id,
            document_projection_id=first.document_projection_id,
        )
        with engine.connect() as conn:
            first_snapshot = _snapshot_dict(canonical_snapshot(conn, first_projection))

        second, second_issues = _run_pipeline_pass(
            bundle_dir=bundle_dir,
            catalog=catalog,
            semantic=semantic,
            document=document,
            source=source,
        )
        if second_issues:
            status.issues.extend(second_issues)
            statuses.append(status)
            continue

        assert second is not None
        status.second_pass = second

        corpus_projection = CorpusProjection(
            role=filing.role,
            company=filing.company,
            cik=filing.cik,
            accession=filing.accession,
            form=resolved_form,
            industry_group=filing.industry_group,
            bundle_id=second.bundle_id,
            semantic_projection_id=second.semantic_projection_id,
            document_projection_id=second.document_projection_id,
        )
        with engine.connect() as conn:
            second_snapshot = _snapshot_dict(canonical_snapshot(conn, corpus_projection))

        idempotency_issues = _idempotency_issues(
            first,
            second,
            snapshots_match=first_snapshot == second_snapshot,
            source=source,
        )
        if idempotency_issues:
            status.issues.extend(idempotency_issues)
            statuses.append(status)
            continue

        status.idempotent = True
        projections.append(corpus_projection)
        statuses.append(status)

    report = _empty_report(settings)
    report["filings"] = [_filing_report(status) for status in statuses]

    coverage: dict[str, Any] = {}
    class_a: dict[str, Any] = {
        "requirements": {},
        "checks": {},
        "unmet": ["no successful projections"],
    }
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
        if class_a.get("unmet"):
            report["issues"].extend(
                coverage_unmet_issues(class_a["unmet"], source=str(_CORPUS_PATH))
            )

    report["coverage"] = coverage
    report["class_a_requirements"] = class_a

    all_ready = all(
        s.bundle_found
        and s.cataloged
        and s.semantic_projected
        and s.document_projected
        and s.idempotent
        for s in statuses
    )
    report["phase1d_readiness"] = {
        "all_filings_projected_and_idempotent": all_ready,
        "class_a_met": not class_a.get("unmet"),
    }
    report["acceptance_gates"]["A_real_corpus"] = class_a.get("requirements", {})
    report["issues"] = [_issue_dict(issue) for issue in report["issues"]]
    return report


def main() -> int:
    settings = Settings()
    report = _empty_report(settings)

    try:
        database_url = settings.require_database_url()
    except Exception as exc:  # noqa: BLE001
        report["issues"].append(
            _issue_dict(
                AcceptanceIssue(
                    component="database",
                    code="DATABASE_UNAVAILABLE",
                    message=str(exc),
                    source="EDGAR_DATABASE_URL",
                )
            )
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    try:
        require_database_at_head(database_url)
    except DatabaseRevisionMismatch as exc:
        report["issues"].append(
            _issue_dict(
                AcceptanceIssue(
                    component="database",
                    code="DATABASE_REVISION_MISMATCH",
                    message=str(exc),
                    source="EDGAR_DATABASE_URL",
                )
            )
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        print(
            "\nDatabase migration revision is not at head. Run `make migrate` or "
            "`uv run edgar db upgrade`.",
            file=sys.stderr,
        )
        return 1
    except SQLAlchemyError as exc:
        report["issues"].append(
            _issue_dict(
                AcceptanceIssue(
                    component="database",
                    code="DATABASE_UNAVAILABLE",
                    message=str(exc),
                    source="EDGAR_DATABASE_URL",
                )
            )
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    except OSError as exc:
        report["issues"].append(
            _issue_dict(
                AcceptanceIssue(
                    component="database",
                    code="DATABASE_UNAVAILABLE",
                    message=str(exc),
                    source="EDGAR_DATABASE_URL",
                )
            )
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    try:
        manifest = load_corpus_manifest(_CORPUS_PATH)
    except (ValidationError, ValueError) as exc:
        report["issues"].append(
            _issue_dict(
                AcceptanceIssue(
                    component="manifest",
                    code="MANIFEST_INVALID",
                    message=str(exc),
                    source=str(_CORPUS_PATH),
                )
            )
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    report.update(run_acceptance(settings, manifest))
    print(json.dumps(report, indent=2, sort_keys=True))

    missing = [f["accession"] for f in report["filings"] if not f["bundle_found"]]
    if missing:
        print(
            f"\nMissing or ambiguous local bundles for: {', '.join(missing)}. "
            "Acquire with `edgar filings retrieve --accession ...` first.",
            file=sys.stderr,
        )
        return 2

    if any(f["issues"] for f in report["filings"]):
        return 3

    if report["issues"]:
        unmet = report["class_a_requirements"].get("unmet") or []
        if unmet:
            print(
                f"\nUnmet class-A requirements: {', '.join(unmet)}",
                file=sys.stderr,
            )
        return 4

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
