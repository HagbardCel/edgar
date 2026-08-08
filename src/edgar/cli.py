"""Production Typer CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from edgar import __version__
from edgar.config import Settings
from edgar.ingestion.acquisition import AcquisitionService

app = typer.Typer(name="edgar", help="SEC EDGAR filing acquisition and XBRL evidence platform.")
filings_app = typer.Typer(help="Filing acquisition workflows.")
app.add_typer(filings_app, name="filings")


@app.callback()
def main() -> None:
    """edgar CLI."""


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


if __name__ == "__main__":
    app()
