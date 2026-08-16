#!/usr/bin/env python3
"""Local real-corpus acceptance: coverage matrix over fixtures/corpus.toml.

Uses locally acquired bundles under EDGAR_DATA_ROOT and the normal EDGAR database.
Phase 2B: catalogs + extracts into source.* (no projection dual-write).
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
    AcceptanceIssue,
    CorpusSourceFiling,
    SourceCanonicalSnapshot,
    coverage_unmet_issues,
    resolve_published_bundle,
    source_canonical_snapshot,
    validate_corpus_bundle_identity,
)
from edgar.corpus_manifest import CorpusManifest, load_corpus_manifest
from edgar.db.check import DatabaseRevisionMismatch, require_database_at_head
from edgar.ingestion.source_extract import SourceExtractError, SourceExtractService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORPUS_PATH = _REPO_ROOT / "fixtures" / "corpus.toml"


@dataclass
class PassResult:
    catalog_reused: bool
    filing_id: int
    report_ids: tuple[int, ...]
    concept_declaration_count: int | None
    fact_count: int | None
    block_count: int | None
    section_count: int | None


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
    extracted: bool = False
    concept_declaration_count: int | None = None
    fact_count: int | None = None
    first_pass: PassResult | None = None
    second_pass: PassResult | None = None
    idempotent: bool = False
    issues: list[AcceptanceIssue] = field(default_factory=list)


def _snapshot_dict(snapshot: SourceCanonicalSnapshot) -> dict[str, Any]:
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
            "all_filings_extracted_and_idempotent": False,
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
    extract: SourceExtractService,
    source: str,
) -> tuple[PassResult | None, list[AcceptanceIssue]]:
    issues: list[AcceptanceIssue] = []
    try:
        result = extract.extract_published_bundle(bundle_dir)
    except SourceExtractError as exc:
        issues.append(
            AcceptanceIssue(
                component="source",
                code="SOURCE_EXTRACT_FAILED",
                message=str(exc),
                source=source,
            )
        )
        return None, issues
    except Exception as exc:  # noqa: BLE001
        issues.append(
            AcceptanceIssue(
                component="source",
                code="SOURCE_EXTRACT_FAILED",
                message=str(exc),
                source=source,
            )
        )
        return None, issues

    return (
        PassResult(
            catalog_reused=result.catalog_reused,
            filing_id=result.filing_id,
            report_ids=result.persist.report_ids,
            concept_declaration_count=None,
            fact_count=result.persist.fact_count,
            block_count=result.persist.block_count,
            section_count=result.persist.section_count,
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
                message="second source catalog pass did not reuse existing source.filing",
                source=source,
            )
        )
    if first.filing_id != second.filing_id:
        issues.append(
            AcceptanceIssue(
                component="idempotency",
                code="FILING_ID_CHANGED",
                message=f"filing_id changed from {first.filing_id} to {second.filing_id}",
                source=source,
            )
        )
    if first.fact_count != second.fact_count:
        issues.append(
            AcceptanceIssue(
                component="idempotency",
                code="FACT_COUNT_CHANGED",
                message=f"fact_count changed from {first.fact_count} to {second.fact_count}",
                source=source,
            )
        )
    if not snapshots_match:
        issues.append(
            AcceptanceIssue(
                component="idempotency",
                code="CANONICAL_SNAPSHOT_CHANGED",
                message="source.* snapshot counts changed between first and second pass",
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
        "extracted": status.extracted,
        "concept_declaration_count": status.concept_declaration_count,
        "fact_count": status.fact_count,
        "first_pass": None if status.first_pass is None else asdict(status.first_pass),
        "second_pass": None if status.second_pass is None else asdict(status.second_pass),
        "idempotent": status.idempotent,
        "issues": [_issue_dict(issue) for issue in status.issues],
    }


def _evaluate_source_class_a(filings: tuple[CorpusSourceFiling, ...]) -> dict[str, Any]:
    two_10k = [p.company for p in filings if p.form == "10-K"]
    two_10q = [p.company for p in filings if p.form == "10-Q"]
    amendment = [p.company for p in filings if p.form in ("10-K/A", "10-Q/A")]
    industries = sorted({p.industry_group for p in filings})
    requirements = {
        "two_10k": two_10k,
        "two_10q": two_10q,
        "amendment": amendment,
        "multiple_industries": len(industries) >= 2,
        "industry_groups": industries,
    }
    checks = {
        "two_10k": len(two_10k) >= 2,
        "two_10q": len(two_10q) >= 2,
        "amendment": len(amendment) >= 1,
        "multiple_industries": len(industries) >= 2,
    }
    unmet = [key for key, met in checks.items() if not met]
    return {"requirements": requirements, "checks": checks, "unmet": unmet}


def run_acceptance(settings: Settings, manifest: CorpusManifest) -> dict[str, Any]:
    data_root = settings.edgar_data_root
    store = ObjectStore(data_root)
    repo = BundleRepository(data_root, store)
    engine = create_engine(settings.require_database_url(), future=True)
    extract = SourceExtractService(settings, engine=engine, bundles=repo)

    statuses: list[FilingRunStatus] = []
    source_filings: list[CorpusSourceFiling] = []
    source_snapshots: dict[str, dict[str, Any]] = {}

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
                    source=str(data_root / "bundles" / filing.cik / filing.accession),
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
            extract=extract,
            source=source,
        )
        if first_issues:
            status.issues.extend(first_issues)
            status.cataloged = False
            status.extracted = False
            statuses.append(status)
            continue

        assert first is not None
        status.first_pass = first
        status.cataloged = True
        status.extracted = True
        status.fact_count = first.fact_count

        with engine.connect() as conn:
            first_snapshot_obj = source_canonical_snapshot(conn, first.filing_id)
            first_snapshot = _snapshot_dict(first_snapshot_obj)
            status.concept_declaration_count = (
                first_snapshot_obj.extraction.concept_declaration_count
            )
            first.concept_declaration_count = status.concept_declaration_count

        second, second_issues = _run_pipeline_pass(
            bundle_dir=bundle_dir,
            extract=extract,
            source=source,
        )
        if second_issues:
            status.issues.extend(second_issues)
            statuses.append(status)
            continue

        assert second is not None
        status.second_pass = second

        with engine.connect() as conn:
            second_snapshot = _snapshot_dict(source_canonical_snapshot(conn, second.filing_id))

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
        source_filings.append(
            CorpusSourceFiling(
                role=filing.role,
                company=filing.company,
                cik=filing.cik,
                accession=filing.accession,
                form=resolved_form,
                industry_group=filing.industry_group,
                filing_id=second.filing_id,
            )
        )
        source_snapshots[filing.accession] = second_snapshot
        statuses.append(status)

    report = _empty_report(settings)
    report["filings"] = [_filing_report(status) for status in statuses]

    coverage: dict[str, Any] = {
        "source_snapshots": source_snapshots,
        "note": (
            "Phase 2B Commit 5: acceptance counts source.* facts/contexts/"
            "relationships/blocks/sections. Projection-table coverage queries "
            "are deferred."
        ),
    }
    class_a: dict[str, Any] = {
        "requirements": {},
        "checks": {},
        "unmet": ["no successful source extractions"],
    }
    if source_filings:
        class_a = _evaluate_source_class_a(tuple(source_filings))
        if class_a.get("unmet"):
            report["issues"].extend(
                coverage_unmet_issues(class_a["unmet"], source=str(_CORPUS_PATH))
            )

    report["coverage"] = coverage
    report["class_a_requirements"] = class_a

    all_ready = all(
        s.bundle_found and s.cataloged and s.extracted and s.idempotent for s in statuses
    )
    report["phase1d_readiness"] = {
        "all_filings_extracted_and_idempotent": all_ready,
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
    except (OSError, ValidationError, ValueError) as exc:
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

    try:
        report = run_acceptance(settings, manifest)
    except Exception as exc:  # noqa: BLE001
        report["issues"].append(
            _issue_dict(
                AcceptanceIssue(
                    component="source",
                    code="ACCEPTANCE_FAILED",
                    message=str(exc),
                    source=str(settings.edgar_data_root),
                )
            )
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    ready = report["phase1d_readiness"]["all_filings_extracted_and_idempotent"]
    class_a_met = report["phase1d_readiness"]["class_a_met"]
    if not ready or not class_a_met or report["issues"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
