"""Production Typer CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from edgar import __version__
from edgar.config import Settings
from edgar.db.document import list_document_sections
from edgar.db.engine import create_db_engine
from edgar.db.mapping_evidence import MappingEvidenceError
from edgar.db.semantic import list_network_relationships
from edgar.ingestion.acquisition import AcquisitionService
from edgar.ingestion.catalog import CatalogService
from edgar.metrics.service import MetricRegistryService
from edgar.parsing.config import DOCUMENT_PROJECTION_VERSION
from edgar.projection.document import (
    DocumentPreflightError,
    DocumentProjectionError,
    DocumentProjectionService,
)
from edgar.projection.semantic import SemanticProjectionError, SemanticProjectionService

app = typer.Typer(name="edgar", help="SEC EDGAR filing acquisition and XBRL evidence platform.")
filings_app = typer.Typer(help="Filing acquisition and catalog workflows.")
db_app = typer.Typer(help="PostgreSQL catalog database workflows.")
xbrl_app = typer.Typer(help="XBRL semantic projection workflows.")
documents_app = typer.Typer(help="Document block and regulatory section workflows.")
metrics_app = typer.Typer(help="Metric ontology registry workflows (Git-authoritative).")
mappings_app = typer.Typer(help="Curated XBRL concept mapping audit workflows.")
app.add_typer(filings_app, name="filings")
app.add_typer(db_app, name="db")
app.add_typer(xbrl_app, name="xbrl")
app.add_typer(documents_app, name="documents")
app.add_typer(metrics_app, name="metrics")
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


def _metric_cli_error(exc: Exception) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


@db_app.command("check")
def db_check() -> None:
    """Verify database reachability and Alembic revision == head."""
    settings = Settings()
    url = settings.require_database_url()
    engine = create_db_engine(url)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    cfg = _alembic_config(url)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        current = context.get_current_revision()
    if current != head:
        typer.echo(f"database revision {current!r} != head {head!r}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"database ok; alembic revision={current}")


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
    """Catalog a published FilingBundle into PostgreSQL (offline; no network)."""
    settings = Settings()
    if data_root is not None:
        settings = settings.model_copy(update={"edgar_data_root": data_root})
    result = CatalogService(settings).catalog_published_bundle(bundle_dir)
    payload = {
        "accession": result.accession,
        "opaque_id": result.opaque_id,
        "filing_id": result.filing_id,
        "bundle_id": result.bundle_id,
        "reused": result.reused,
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            f"Cataloged FilingBundle {result.accession} "
            f"({'reused' if result.reused else 'new'}) "
            f"bundle_id={result.bundle_id}"
        )


@xbrl_app.command("project")
def xbrl_project(
    bundle_dir: Annotated[
        Path,
        typer.Option("--bundle-dir", help="Published cataloged bundle under EDGAR_DATA_ROOT"),
    ],
    data_root: Annotated[
        Path | None,
        typer.Option("--data-root", help="Override EDGAR_DATA_ROOT"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
) -> None:
    """Project the primary XBRL report of an already-cataloged FilingBundle offline."""
    settings = Settings()
    if data_root is not None:
        settings = settings.model_copy(update={"edgar_data_root": data_root})
    try:
        result = SemanticProjectionService(settings).project_published_bundle(bundle_dir)
    except SemanticProjectionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    projection = result.projection
    payload = {
        "accession": result.accession,
        "bundle_id": result.bundle_id,
        "report_input_id": result.report_input_id,
        "projection_id": projection.projection_id,
        "attempt_id": projection.attempt_id,
        "status": projection.status,
        "reused": projection.reused,
        "arelle_version": result.projection.arelle_version,
        "concept_count": projection.counts.get("concept_declarations", 0),
        "fact_count": projection.counts.get("facts", 0),
        "context_count": projection.counts.get("contexts", 0),
        "unit_count": projection.counts.get("units", 0),
        "relationship_count": projection.counts.get("relationships", 0),
        "issue_count": projection.counts.get("issues", 0),
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            f"Semantic projection {projection.projection_id} "
            f"({'reused' if projection.reused else 'new'}) "
            f"status={projection.status} facts={payload['fact_count']}"
        )


@xbrl_app.command("network")
def xbrl_network(
    projection_id: Annotated[int, typer.Option("--projection-id", help="semantic_projection.id")],
    network_type: Annotated[
        str,
        typer.Option("--type", help="presentation | calculation | definition"),
    ],
    role: Annotated[str, typer.Option("--role", help="Extended link role URI")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
) -> None:
    """Inspect an effective relationship network from persisted rows (no Arelle)."""
    if network_type not in {"presentation", "calculation", "definition"}:
        typer.echo(f"unsupported network type: {network_type}", err=True)
        raise typer.Exit(code=1)
    settings = Settings()
    engine = create_db_engine(settings.require_database_url())
    with engine.connect() as conn:
        rows = list_network_relationships(
            conn, projection_id, network_type=network_type, link_role_uri=role
        )
    payload = {
        "projection_id": projection_id,
        "network_type": network_type,
        "link_role_uri": role,
        "relationships": rows,
        "count": len(rows),
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(f"{network_type} network role={role} relationships={len(rows)}")
        for row in rows:
            typer.echo(
                f"  {row['source_concept']['local_name']} -> "
                f"{row['target_concept']['local_name']} "
                f"order={row.get('order')} weight={row.get('weight')}"
            )


@documents_app.command("project")
def documents_project(
    bundle_dir: Annotated[
        Path,
        typer.Option("--bundle-dir", help="Published FilingBundle directory"),
    ],
    artifact_path: Annotated[
        str | None,
        typer.Option("--artifact-path", help="Bundle-relative HTML artifact (default: primary)"),
    ] = None,
    data_root: Annotated[
        Path | None,
        typer.Option("--data-root", help="Override EDGAR_DATA_ROOT"),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
) -> None:
    """Project an HTML filing document into blocks and (for primary) sections."""
    settings = Settings()
    if data_root is not None:
        settings = settings.model_copy(update={"edgar_data_root": data_root})
    service = DocumentProjectionService(settings)
    try:
        result = service.project_published_bundle(bundle_dir, artifact_path=artifact_path)
    except DocumentPreflightError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    except DocumentProjectionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    projection = result.projection
    payload = {
        "accession": result.accession,
        "bundle_id": result.bundle_id,
        "filing_document_id": result.filing_document_id,
        "artifact_path": result.artifact_path,
        "projection_id": projection.projection_id,
        "attempt_id": projection.attempt_id,
        "parser_version": DOCUMENT_PROJECTION_VERSION,
        "status": projection.status,
        "reused": projection.reused,
        "block_count": projection.counts.get("blocks", 0),
        "section_count": projection.counts.get("sections", 0),
        "issue_count": projection.counts.get("issues", 0),
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            f"Document projection {projection.projection_id} "
            f"({'reused' if projection.reused else 'new'}) "
            f"status={projection.status} blocks={payload['block_count']} "
            f"sections={payload['section_count']}"
        )


@documents_app.command("sections")
def documents_sections(
    projection_id: Annotated[int, typer.Option("--projection-id", help="document_projection.id")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
) -> None:
    """List compact section metadata for a document projection."""
    settings = Settings()
    engine = create_db_engine(settings.require_database_url())
    with engine.connect() as conn:
        rows = list_document_sections(conn, projection_id)
    payload = {"projection_id": projection_id, "sections": rows, "count": len(rows)}
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(f"projection {projection_id} sections={len(rows)}")
        for row in rows:
            typer.echo(
                f"  {row['section_key']} "
                f"[{row['start_block_ordinal']}, {row['end_block_ordinal_exclusive']}) "
                f"confidence={row['confidence_score']}"
            )


@metrics_app.command("list")
def metrics_list(
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List metric definitions from the Git registry."""
    registry = _metric_service(registry_dir).load_git_registry()
    rows = sorted(registry.definitions, key=lambda d: (d.metric_code, d.definition_version))
    payload = {
        "registry_hash": registry.registry_hash,
        "metrics": [
            {
                "metric_code": r.metric_code,
                "definition_version": r.definition_version,
                "name": r.name,
                "family_code": r.family_code,
                "period_type": r.period_type,
                "dimension_policy": r.dimension_policy,
            }
            for r in rows
        ],
        "count": len(rows),
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(f"metrics={len(rows)} registry_hash={registry.registry_hash}")
        for row in rows:
            typer.echo(f"  {row.metric_code}@{row.definition_version} ({row.name})")


@metrics_app.command("show")
def metrics_show(
    metric_code: Annotated[str, typer.Argument(help="Metric code")],
    version: Annotated[
        int | None,
        typer.Option("--version", help="Definition version (required if multiple exist)"),
    ] = None,
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show one metric definition contract."""
    try:
        rows = _metric_service(registry_dir).get_metric(metric_code, definition_version=version)
    except ValueError as exc:
        _metric_cli_error(exc)
    if not rows:
        typer.echo(f"unknown metric: {metric_code}", err=True)
        raise typer.Exit(code=1)
    registry = _metric_service(registry_dir).load_git_registry()
    payload = {
        "registry_hash": registry.registry_hash,
        "definitions": [r.model_dump(mode="json") for r in rows],
        "count": len(rows),
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for row in rows:
            typer.echo(f"{row.metric_code}@{row.definition_version}: {row.economic_definition}")


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
    registry = _metric_service(registry_dir).load_git_registry()
    rows = _metric_service(registry_dir).list_mappings(
        metric_code=metric,
        concept_local_name=concept,
        cik=cik,
        relationship_type=relationship,
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
    """Explain one mapping rule with pinned projection evidence enrichment."""
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
            typer.echo(f"pinned projection facts={len(enrichment.get('fact_occurrences', []))}")


@mappings_app.command("export")
def mappings_export(
    fmt: Annotated[str, typer.Option("--format", help="json | markdown")] = "json",
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
) -> None:
    """Export mapping audit ledger from Git (DB-free)."""
    from edgar.metrics.export import mapping_rule_markdown

    reports = _metric_service(registry_dir).export_mappings_audit()
    if fmt == "json":
        payload = {"reports": reports, "count": len(reports)}
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif fmt == "markdown":
        for report in reports:
            typer.echo(mapping_rule_markdown(cast(dict[str, Any], report)))
    else:
        typer.echo(f"unsupported format: {fmt}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
