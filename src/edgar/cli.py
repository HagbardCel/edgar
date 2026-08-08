"""Production Typer CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from edgar import __version__
from edgar.config import Settings
from edgar.db.engine import create_db_engine
from edgar.db.semantic import list_network_relationships
from edgar.ingestion.acquisition import AcquisitionService
from edgar.ingestion.catalog import CatalogService
from edgar.projection.semantic import SemanticProjectionError, SemanticProjectionService

app = typer.Typer(name="edgar", help="SEC EDGAR filing acquisition and XBRL evidence platform.")
filings_app = typer.Typer(help="Filing acquisition and catalog workflows.")
db_app = typer.Typer(help="PostgreSQL catalog database workflows.")
xbrl_app = typer.Typer(help="XBRL semantic projection workflows.")
app.add_typer(filings_app, name="filings")
app.add_typer(db_app, name="db")
app.add_typer(xbrl_app, name="xbrl")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


@app.callback()
def main() -> None:
    """edgar CLI."""


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.attributes["database_url"] = database_url
    return cfg


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
        "arelle_version": None,
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


if __name__ == "__main__":
    app()
