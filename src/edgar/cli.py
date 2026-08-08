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
from edgar.ingestion.acquisition import AcquisitionService
from edgar.ingestion.catalog import CatalogService

app = typer.Typer(name="edgar", help="SEC EDGAR filing acquisition and XBRL evidence platform.")
filings_app = typer.Typer(help="Filing acquisition and catalog workflows.")
db_app = typer.Typer(help="PostgreSQL catalog database workflows.")
app.add_typer(filings_app, name="filings")
app.add_typer(db_app, name="db")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


@app.callback()
def main() -> None:
    """edgar CLI."""


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
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


if __name__ == "__main__":
    app()
