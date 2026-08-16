"""Real-corpus acceptance helpers: bundle resolution and source.* snapshots."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from sqlalchemy import Connection, func, select

from edgar.corpus_manifest import CorpusFiling, CorpusManifest
from edgar.db import source_schema as src
from edgar.domain.bundle import FilingBundle
from edgar.storage.bundles import BundleRepository, BundleStorageError

AcceptanceComponent = Literal[
    "database",
    "manifest",
    "resolution",
    "identity",
    "catalog",
    "source",
    "idempotency",
    "coverage",
]


@dataclass(frozen=True)
class AcceptanceIssue:
    component: AcceptanceComponent
    code: str
    message: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


STANDARD_TAXONOMY_HOSTS = frozenset(
    {
        "fasb.org",
        "xbrl.sec.gov",
        "xbrl.org",
        "www.xbrl.org",
    }
)

_US_GAAP_YEAR = re.compile(r"^/us-gaap/(\d{4})(?:-\d{2}-\d{2})?$")


@dataclass(frozen=True)
class PublishedBundleResolution:
    bundle_dir: Path | None
    bundle: FilingBundle | None
    candidates: tuple[dict[str, str], ...]
    error: str | None
    error_code: str | None = None


@dataclass(frozen=True)
class CorpusSourceFiling:
    """Corpus filing identity keyed by source.filing (Phase 2B)."""

    role: str
    company: str
    cik: str
    accession: str
    form: str
    industry_group: str
    filing_id: int


@dataclass(frozen=True)
class SourceCatalogSnapshot:
    filing_id: int
    document_count: int
    report_count: int


@dataclass(frozen=True)
class SourceExtractionSnapshot:
    filing_id: int
    concept_declaration_count: int
    concept_label_count: int
    concept_reference_count: int
    context_count: int
    context_dimension_count: int
    unit_count: int
    unit_measure_count: int
    fact_count: int
    relationship_count: int
    extraction_issue_count: int
    block_count: int
    section_count: int


@dataclass(frozen=True)
class SourceCanonicalSnapshot:
    catalog: SourceCatalogSnapshot
    extraction: SourceExtractionSnapshot


def is_standard_taxonomy_namespace(namespace_uri: str | None) -> bool:
    if not namespace_uri:
        return False
    host = urlparse(namespace_uri).hostname
    if host is None:
        return False
    return host.lower() in STANDARD_TAXONOMY_HOSTS


def parse_us_gaap_taxonomy_year(namespace_uri: str | None) -> int | None:
    if not namespace_uri:
        return None
    parsed = urlparse(namespace_uri)
    if parsed.hostname != "fasb.org":
        return None
    match = _US_GAAP_YEAR.match(parsed.path or "")
    if match is None:
        return None
    return int(match.group(1))


def resolve_published_bundle(
    repo: BundleRepository, cik: str, accession: str
) -> PublishedBundleResolution:
    try:
        published = repo.list_published(cik, accession)
    except BundleStorageError as exc:
        return PublishedBundleResolution(
            bundle_dir=None,
            bundle=None,
            candidates=(),
            error=str(exc),
            error_code="BUNDLE_INTEGRITY_FAILED",
        )
    candidates = tuple(
        {
            "bundle_dir": str(bundle_dir),
            "opaque_id": bundle_dir.name,
            "payload_hash": bundle.payload_hash,
        }
        for bundle_dir, bundle in published
    )
    if not published:
        return PublishedBundleResolution(
            bundle_dir=None,
            bundle=None,
            candidates=(),
            error="bundle not found under EDGAR_DATA_ROOT",
            error_code="BUNDLE_NOT_FOUND",
        )
    if len(published) > 1:
        return PublishedBundleResolution(
            bundle_dir=None,
            bundle=None,
            candidates=candidates,
            error=f"ambiguous corpus identity: {len(published)} published bundles for accession",
            error_code="AMBIGUOUS_BUNDLE",
        )
    bundle_dir, bundle = published[0]
    return PublishedBundleResolution(
        bundle_dir=bundle_dir,
        bundle=bundle,
        candidates=candidates,
        error=None,
    )


def validate_corpus_bundle_identity(
    manifest_filing: CorpusFiling,
    bundle: FilingBundle,
    manifest: CorpusManifest,
    *,
    source: str,
) -> list[AcceptanceIssue]:
    """Verify resolved bundle metadata matches the typed corpus manifest row."""
    issues: list[AcceptanceIssue] = []
    filing = bundle.filing

    if filing.cik != manifest_filing.cik:
        issues.append(
            AcceptanceIssue(
                component="identity",
                code="CIK_MISMATCH",
                message=f"bundle cik {filing.cik!r} != manifest cik {manifest_filing.cik!r}",
                source=source,
            )
        )
    if filing.accession != manifest_filing.accession:
        issues.append(
            AcceptanceIssue(
                component="identity",
                code="ACCESSION_MISMATCH",
                message=(
                    f"bundle accession {filing.accession!r} != "
                    f"manifest accession {manifest_filing.accession!r}"
                ),
                source=source,
            )
        )
    if filing.form_type != manifest_filing.form:
        issues.append(
            AcceptanceIssue(
                component="identity",
                code="FORM_MISMATCH",
                message=(
                    f"bundle form_type {filing.form_type!r} != "
                    f"manifest form {manifest_filing.form!r}"
                ),
                source=source,
            )
        )
    if manifest_filing.filed is not None and filing.filing_date != manifest_filing.filed:
        issues.append(
            AcceptanceIssue(
                component="identity",
                code="FILED_MISMATCH",
                message=(
                    f"bundle filing_date {filing.filing_date.isoformat()!r} != "
                    f"manifest filed {manifest_filing.filed.isoformat()!r}"
                ),
                source=source,
            )
        )
    if bundle.acquisition_policy_version != manifest.acquisition_policy_version:
        issues.append(
            AcceptanceIssue(
                component="identity",
                code="ACQUISITION_POLICY_MISMATCH",
                message=(
                    "bundle acquisition_policy_version "
                    f"{bundle.acquisition_policy_version!r} != manifest "
                    f"{manifest.acquisition_policy_version!r}"
                ),
                source=source,
            )
        )
    return issues


def coverage_unmet_issues(unmet: list[str], *, source: str) -> list[AcceptanceIssue]:
    return [
        AcceptanceIssue(
            component="coverage",
            code=f"COVERAGE_{key.upper()}_UNMET",
            message=f"class-A requirement {key!r} not met",
            source=source,
        )
        for key in unmet
    ]


def _scalar_count(conn: Connection, stmt: Any) -> int:
    value = conn.execute(stmt).scalar_one()
    return int(value)


def evaluate_class_a_requirements(
    filings: tuple[CorpusSourceFiling, ...],
) -> dict[str, Any]:
    """Evaluate form/industry class-A coverage against cataloged source filings."""
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


def source_canonical_snapshot(conn: Connection, filing_id: int) -> SourceCanonicalSnapshot:
    """Count source.* catalog + extraction rows for one filing."""
    report_ids = select(src.source_xbrl_report.c.id).where(
        src.source_xbrl_report.c.filing_id == filing_id
    )
    document_ids = select(src.source_document.c.id).where(
        src.source_document.c.filing_id == filing_id
    )

    catalog = SourceCatalogSnapshot(
        filing_id=filing_id,
        document_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_document)
            .where(src.source_document.c.filing_id == filing_id),
        ),
        report_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_xbrl_report)
            .where(src.source_xbrl_report.c.filing_id == filing_id),
        ),
    )

    extraction = SourceExtractionSnapshot(
        filing_id=filing_id,
        concept_declaration_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_concept_declaration)
            .where(src.source_concept_declaration.c.report_id.in_(report_ids)),
        ),
        concept_label_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_concept_label)
            .where(src.source_concept_label.c.report_id.in_(report_ids)),
        ),
        concept_reference_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_concept_reference)
            .where(src.source_concept_reference.c.report_id.in_(report_ids)),
        ),
        context_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_context)
            .where(src.source_context.c.report_id.in_(report_ids)),
        ),
        context_dimension_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_context_dimension)
            .join(
                src.source_context,
                src.source_context_dimension.c.context_id == src.source_context.c.id,
            )
            .where(src.source_context.c.report_id.in_(report_ids)),
        ),
        unit_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_unit)
            .where(src.source_unit.c.report_id.in_(report_ids)),
        ),
        unit_measure_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_unit_measure)
            .join(src.source_unit, src.source_unit_measure.c.unit_id == src.source_unit.c.id)
            .where(src.source_unit.c.report_id.in_(report_ids)),
        ),
        fact_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_fact)
            .where(src.source_fact.c.report_id.in_(report_ids)),
        ),
        relationship_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_relationship)
            .where(src.source_relationship.c.report_id.in_(report_ids)),
        ),
        extraction_issue_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_extraction_issue)
            .where(src.source_extraction_issue.c.filing_id == filing_id),
        ),
        block_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_document_block)
            .where(src.source_document_block.c.document_id.in_(document_ids)),
        ),
        section_count=_scalar_count(
            conn,
            select(func.count())
            .select_from(src.source_filing_section)
            .where(src.source_filing_section.c.document_id.in_(document_ids)),
        ),
    )
    return SourceCanonicalSnapshot(catalog=catalog, extraction=extraction)


def lookup_source_filing_id(conn: Connection, accession: str) -> int | None:
    value = conn.execute(
        select(src.source_filing.c.id).where(src.source_filing.c.accession == accession)
    ).scalar_one_or_none()
    return int(value) if value is not None else None
