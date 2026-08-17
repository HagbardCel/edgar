"""Production Typer CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, NoReturn, cast

import typer
from alembic import command
from alembic.config import Config

from edgar import __version__
from edgar.config import Settings
from edgar.db.check import DatabaseRevisionMismatch, require_database_at_head
from edgar.db.engine import create_db_engine
from edgar.db.mapping_evidence import MappingEvidenceError
from edgar.db.source import list_source_document_sections
from edgar.ingestion.acquisition import AcquisitionService
from edgar.ingestion.catalog import CatalogService
from edgar.ingestion.source_extract import SourceExtractError, SourceExtractService
from edgar.metrics.service import MetricRegistryService
from edgar.registry.loader import (
    LoadedCanonicalRegistry,
    load_canonical_registry,
    metric_list_payload,
    metric_show_payload,
)
from edgar.registry.models import RegistryValidationError

app = typer.Typer(name="edgar", help="SEC EDGAR filing acquisition and XBRL evidence platform.")
filings_app = typer.Typer(help="Filing acquisition, catalog, and extract workflows.")
db_app = typer.Typer(help="PostgreSQL source.* database workflows.")
documents_app = typer.Typer(help="Document section inspection (source.*).")
metrics_app = typer.Typer(help="Canonical metric registry workflows (Git-authoritative YAML).")
registry_app = typer.Typer(help="Canonical metric YAML validation and database sync.")
mappings_app = typer.Typer(help="Curated XBRL concept mapping audit workflows.")
app.add_typer(filings_app, name="filings")
app.add_typer(db_app, name="db")
app.add_typer(documents_app, name="documents")
app.add_typer(metrics_app, name="metrics")
app.add_typer(registry_app, name="registry")
app.add_typer(mappings_app, name="mappings")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


@app.callback()
def main() -> None:
    """edgar CLI."""


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.attributes["database_url"] = database_url
    return cfg


def _metric_service(registry_dir: Path | None = None) -> MetricRegistryService:
    return MetricRegistryService(Settings(), registry_dir=registry_dir)


def _metric_cli_error(exc: Exception) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _load_canonical(registry_dir: Path | None) -> LoadedCanonicalRegistry:
    try:
        return load_canonical_registry(registry_dir)
    except (OSError, RegistryValidationError) as exc:
        _metric_cli_error(exc)


@db_app.command("check")
def db_check() -> None:
    """Verify database reachability and Alembic revision == head."""
    settings = Settings()
    url = settings.require_database_url()
    try:
        revision = require_database_at_head(url)
    except DatabaseRevisionMismatch as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        typer.echo(f"database unavailable: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"database ok; alembic revision={revision.current}")


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply Alembic migrations to head."""
    settings = Settings()
    url = settings.require_database_url()
    command.upgrade(_alembic_config(url), "head")
    typer.echo("alembic upgrade head complete")


@filings_app.command("retrieve")
def filings_retrieve(
    accession: Annotated[str, typer.Option("--accession", help="Canonical dashed accession")],
    data_root: Annotated[
        Path | None,
        typer.Option("--data-root", help="Override EDGAR_DATA_ROOT"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
) -> None:
    """Acquire an accession as an immutable FilingBundle and validate offline replay."""
    settings = Settings()
    if data_root is not None:
        settings = settings.model_copy(update={"edgar_data_root": data_root})
    with AcquisitionService(settings) as service:
        result = service.acquire(accession)
    payload = {
        "accession": result.bundle.filing.accession,
        "cik": result.bundle.filing.cik,
        "payload_hash": result.bundle.payload_hash,
        "bundle_dir": str(result.publish.bundle_dir),
        "opaque_id": result.publish.opaque_id,
        "reused": result.publish.reused,
        "attempt_id": result.attempt_id,
        "report_input": result.bundle.report_inputs[0].to_dict(),
        "artifact_count": len(result.bundle.artifacts),
        "binding_count": len(result.bundle.uri_bindings),
        "replay_faithful": result.replay_faithful,
        "edgar_version": __version__,
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            f"Published FilingBundle {result.bundle.filing.accession} "
            f"({'reused' if result.publish.reused else 'new'}) "
            f"at {result.publish.bundle_dir}"
        )
        typer.echo(f"payload_hash={result.bundle.payload_hash}")
        typer.echo(f"report_input={result.bundle.report_inputs[0].to_dict()}")


@filings_app.command("catalog")
def filings_catalog(
    bundle_dir: Annotated[
        Path,
        typer.Option("--bundle-dir", help="Published bundle directory under EDGAR_DATA_ROOT"),
    ],
    data_root: Annotated[
        Path | None,
        typer.Option("--data-root", help="Override EDGAR_DATA_ROOT"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
) -> None:
    """Catalog a published FilingBundle into source.* (offline; no network)."""
    settings = Settings()
    if data_root is not None:
        settings = settings.model_copy(update={"edgar_data_root": data_root})
    result = CatalogService(settings).catalog_published_bundle(bundle_dir)
    payload = {
        "accession": result.accession,
        "opaque_id": result.opaque_id,
        "filing_id": result.filing_id,
        "issuer_cik": result.issuer_cik,
        "document_count": result.document_count,
        "reused": result.reused,
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            f"Cataloged FilingBundle {result.accession} "
            f"({'reused' if result.reused else 'new'}) "
            f"filing_id={result.filing_id} documents={result.document_count}"
        )


@filings_app.command("extract")
def filings_extract(
    bundle_dir: Annotated[
        Path,
        typer.Option("--bundle-dir", help="Published bundle directory under EDGAR_DATA_ROOT"),
    ],
    data_root: Annotated[
        Path | None,
        typer.Option("--data-root", help="Override EDGAR_DATA_ROOT"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
) -> None:
    """Catalog (source.*) if needed, extract XBRL + documents, and persist atomically."""
    settings = Settings()
    if data_root is not None:
        settings = settings.model_copy(update={"edgar_data_root": data_root})
    try:
        result = SourceExtractService(settings).extract_published_bundle(bundle_dir)
    except SourceExtractError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    persist = result.persist
    payload = {
        "accession": result.accession,
        "opaque_id": result.opaque_id,
        "filing_id": result.filing_id,
        "catalog_reused": result.catalog_reused,
        "document_count": result.document_count,
        "report_ids": list(persist.report_ids),
        "fact_count": persist.fact_count,
        "block_count": persist.block_count,
        "section_count": persist.section_count,
        "issue_count": persist.issue_count,
        "concept_upsert_count": persist.concept_upsert_count,
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            f"Extracted {result.accession} filing_id={result.filing_id} "
            f"facts={persist.fact_count} blocks={persist.block_count} "
            f"sections={persist.section_count}"
        )


@documents_app.command("sections")
def documents_sections(
    document_id: Annotated[int, typer.Option("--document-id", help="source.document.id")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
) -> None:
    """List compact section metadata for a source document."""
    settings = Settings()
    engine = create_db_engine(settings.require_database_url())
    with engine.connect() as conn:
        rows = list_source_document_sections(conn, document_id)
    payload = {"document_id": document_id, "sections": rows, "count": len(rows)}
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(f"document {document_id} sections={len(rows)}")
        for row in rows:
            typer.echo(
                f"  {row['section_key']} "
                f"[{row['start_block_ordinal']}, {row['end_block_ordinal_exclusive']}) "
                f"confidence={row['confidence_score']}"
            )


@registry_app.command("validate")
def registry_validate(
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
) -> None:
    """Load and validate registry/metrics.yml (no database)."""
    loaded = _load_canonical(registry_dir)
    typer.echo(f"metrics={len(loaded.metrics)}")
    typer.echo(f"semantic_registry_hash={loaded.semantic_registry_hash}")


@metrics_app.command("list")
def metrics_list(
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List canonical metric definitions from metrics.yml."""
    loaded = _load_canonical(registry_dir)
    payload = metric_list_payload(loaded)
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(
        f"metrics={payload['count']} semantic_registry_hash={payload['semantic_registry_hash']}"
    )
    for row in payload["metrics"]:
        typer.echo(f"  {row['key']} ({row['name']})")


@metrics_app.command("show")
def metrics_show(
    metric_key: Annotated[str, typer.Argument(help="Canonical metric key")],
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show one canonical metric definition contract."""
    loaded = _load_canonical(registry_dir)
    metric = loaded.get(metric_key)
    if metric is None:
        typer.echo(f"unknown metric: {metric_key}", err=True)
        raise typer.Exit(code=1)
    payload = metric_show_payload(loaded, metric)
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    shown = payload["metrics"][0]
    typer.echo(f"{shown['key']}: {shown['definition'].strip()}")
    typer.echo(f"definition_hash={shown['definition_hash']}")


@mappings_app.command("list")
def mappings_list(
    metric: Annotated[str | None, typer.Option("--metric")] = None,
    concept: Annotated[str | None, typer.Option("--concept", help="local_name filter")] = None,
    cik: Annotated[str | None, typer.Option("--cik")] = None,
    relationship: Annotated[str | None, typer.Option("--relationship")] = None,
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List curated mapping rules from Git."""
    service = _metric_service(registry_dir)
    registry = service.load_git_registry()
    rows = service.list_mappings(
        metric_code=metric,
        concept_local_name=concept,
        cik=cik,
        relationship_type=relationship,
        registry=registry,
    )
    payload = {
        "registry_hash": registry.registry_hash,
        "rules": [
            {
                "rule_key": r.rule.rule_key,
                "state": r.state,
                "source_concept": r.rule.source_concept.model_dump(),
                "target_metric_code": r.rule.target_metric_code,
                "target_definition_version": r.rule.target_definition_version,
                "relationship_type": r.rule.relationship_type,
                "scope_kind": r.rule.scope_kind,
            }
            for r in rows
        ],
        "count": len(rows),
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(f"mappings={len(rows)} registry_hash={registry.registry_hash}")
        for row in rows:
            q = row.rule.source_concept
            typer.echo(
                f"  {row.rule.rule_key} [{row.state}] "
                f"{q.local_name} -> {row.rule.target_metric_code}@"
                f"{row.rule.target_definition_version} "
                f"({row.rule.relationship_type})"
            )


@mappings_app.command("explain")
def mappings_explain(
    rule_key: Annotated[str, typer.Argument(help="Mapping rule key")],
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Explain one mapping rule with pinned source.* evidence enrichment."""
    try:
        payload = cast(dict[str, Any], _metric_service(registry_dir).explain_mapping(rule_key))
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except MappingEvidenceError as exc:
        _metric_cli_error(exc)
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(f"rule {rule_key} state={payload['state']}")
        typer.echo(f"relationship={payload['relationship_type']}")
        enrichment = payload.get("pinned_evidence_enrichment")
        if enrichment is not None:
            reports = enrichment.get("reports") or []
            typer.echo(f"pinned reports={len(reports)}")
            for report in reports:
                facts = len(report.get("fact_occurrences") or [])
                typer.echo(
                    f"  report_id={report.get('report_id')} "
                    f"report_key={report.get('report_key')} facts={facts}"
                )


@mappings_app.command("export")
def mappings_export(
    fmt: Annotated[str, typer.Option("--format", help="json | markdown")] = "json",
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
) -> None:
    """Export mapping audit ledger from Git (DB-free)."""
    service = _metric_service(registry_dir)
    if fmt == "json":
        payload = service.export_mappings_audit()
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif fmt == "markdown":
        typer.echo(service.export_mappings_audit_markdown())
    else:
        typer.echo(f"unsupported format: {fmt}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
