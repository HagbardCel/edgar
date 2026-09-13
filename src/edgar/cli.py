"""Production Typer CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from alembic import command
from alembic.config import Config

from edgar import __version__
from edgar.config import Settings
from edgar.db.check import DatabaseRevisionMismatch, require_database_at_head
from edgar.db.engine import create_db_engine
from edgar.db.source import list_source_document_sections
from edgar.domain.identifiers import validate_cik
from edgar.ingestion.acquisition import AcquisitionService
from edgar.ingestion.catalog import CatalogService
from edgar.ingestion.source_extract import SourceExtractError, SourceExtractService
from edgar.registry.export import dump_json, dump_jsonl, dump_markdown
from edgar.registry.loader import (
    LoadedCanonicalRegistry,
    load_canonical_registry,
    metric_list_payload,
    metric_show_payload,
)
from edgar.registry.mapping import (
    MappingAssertionCreate,
    MappingAssertionRevision,
    MappingEvidenceItem,
)
from edgar.registry.models import RegistryValidationError
from edgar.registry.service import (
    RegistryError,
    RegistryService,
    UnsafeMetricDeletionError,
    format_sync_result,
)
from edgar.registry.views import MappingReport

app = typer.Typer(name="edgar", help="SEC EDGAR filing acquisition and XBRL evidence platform.")
filings_app = typer.Typer(help="Filing acquisition, catalog, and extract workflows.")
db_app = typer.Typer(help="PostgreSQL source.* database workflows.")
documents_app = typer.Typer(help="Document section inspection (source.*).")
metrics_app = typer.Typer(help="Canonical metric registry workflows (Git-authoritative YAML).")
registry_app = typer.Typer(help="Canonical metric YAML validation and database sync.")
mappings_app = typer.Typer(help="Mapping decision ledger workflows (registry.mapping_assertion).")
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


def _registry_service(registry_dir: Path | None = None) -> RegistryService:
    return RegistryService(Settings(), registry_dir=registry_dir)


def _metric_cli_error(exc: Exception) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _load_canonical(registry_dir: Path | None) -> LoadedCanonicalRegistry:
    try:
        return load_canonical_registry(registry_dir)
    except (OSError, RegistryValidationError) as exc:
        _metric_cli_error(exc)


def _read_text_file(path: Path | None) -> str | None:
    if path is None:
        return None
    return path.read_text(encoding="utf-8").strip()


def _read_evidence(path: Path | None) -> tuple[MappingEvidenceItem, ...]:
    if path is None:
        return ()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("evidence file must contain a JSON array")
    return tuple(MappingEvidenceItem.model_validate(item) for item in raw)


def _format_mapping_report_text(report: MappingReport) -> str:
    mapping = report.mapping
    currency = (
        "current" if report.is_current else f"superseded; current={report.current_revision_id}"
    )
    lines = [
        f"mapping {mapping.id} {mapping.status} ({currency})",
        f"concept={mapping.source_concept}",
        f"metric={mapping.target_metric_key} relation={mapping.relation}",
        f"scope={mapping.scope.kind}"
        + (f" issuer={mapping.scope.issuer_cik}" if mapping.scope.issuer_cik else ""),
        f"target_definition_hash={mapping.target_definition_hash}",
        f"yaml_definition_hash={report.yaml_definition_hash}",
        f"definition_changed={str(report.definition_changed).lower()}",
        f"method={mapping.method} created_by={mapping.created_by}",
    ]
    if mapping.rationale:
        lines.append(f"rationale={mapping.rationale}")
    lines.append("history:")
    for item in report.history:
        lines.append(f"  {item.id} {item.status} {item.created_at.isoformat()} {item.created_by}")
    summary = report.affected_fact_summary
    lines.append(
        f"affected_facts={summary.count} shown={summary.shown} truncated={summary.truncated}"
    )
    for fact in report.affected_facts:
        period = fact.report_period_end.isoformat() if fact.report_period_end else "null"
        lines.append(
            f"  {fact.accession} period={period} "
            f"document={fact.source_document or ''} fact_id={fact.fact_id}"
        )
    return "\n".join(lines)


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


@registry_app.command("sync")
def registry_sync(
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
) -> None:
    """Synchronize registry.canonical_metric from metrics.yml."""
    settings = Settings()
    service = RegistryService(settings, registry_dir=registry_dir)
    try:
        result = service.sync_canonical_metrics()
    except UnsafeMetricDeletionError as exc:
        _metric_cli_error(exc)
    except RegistryError as exc:
        _metric_cli_error(exc)
    typer.echo(format_sync_result(result))


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
    status: Annotated[str | None, typer.Option("--status")] = None,
    relation: Annotated[str | None, typer.Option("--relation")] = None,
    metric: Annotated[str | None, typer.Option("--metric")] = None,
    issuer: Annotated[str | None, typer.Option("--issuer", help="Zero-padded CIK")] = None,
    concept: Annotated[
        str | None, typer.Option("--concept", help="Clark '{namespace-uri}LocalName'")
    ] = None,
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List current mapping assertion revisions (all statuses by default)."""
    issuer_cik = None
    if issuer is not None:
        try:
            issuer_cik = validate_cik(issuer)
        except ValueError as exc:
            _metric_cli_error(exc)
    try:
        rows = _registry_service(registry_dir).list_mappings(
            status=status,
            relation=relation,
            metric_key=metric,
            issuer_cik=issuer_cik,
            concept=concept,
        )
    except (ValueError, RegistryError) as exc:
        _metric_cli_error(exc)
    payload = {
        "assertions": [row.model_dump(mode="json") for row in rows],
        "count": len(rows),
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(f"mappings={len(rows)}")
    for row in rows:
        typer.echo(
            f"  {row.id} {row.status} {row.relation} {row.source_concept} -> "
            f"{row.target_metric_key} ({row.scope.kind})"
        )


@mappings_app.command("show")
def mappings_show(
    assertion_id: Annotated[int, typer.Argument(help="Mapping assertion revision id")],
    include_facts: Annotated[bool, typer.Option("--include-facts")] = False,
    fmt: Annotated[str, typer.Option("--format", help="text | json")] = "text",
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
) -> None:
    """Show a named mapping revision plus its full assertion chain."""
    try:
        report = _registry_service(registry_dir).get_mapping(
            assertion_id, include_facts=include_facts
        )
    except (ValueError, RegistryError) as exc:
        _metric_cli_error(exc)
    if fmt == "json":
        typer.echo(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
        return
    if fmt != "text":
        typer.echo(f"unsupported format: {fmt}", err=True)
        raise typer.Exit(code=1)
    typer.echo(_format_mapping_report_text(report))


@mappings_app.command("propose")
def mappings_propose(
    concept: Annotated[str, typer.Option("--concept", help="Clark '{namespace-uri}LocalName'")],
    metric: Annotated[str, typer.Option("--metric")],
    relation: Annotated[str, typer.Option("--relation")],
    method: Annotated[str, typer.Option("--method")],
    created_by: Annotated[str, typer.Option("--created-by")],
    issuer: Annotated[str | None, typer.Option("--issuer", help="Zero-padded CIK")] = None,
    valid_from: Annotated[str | None, typer.Option("--valid-from")] = None,
    valid_to: Annotated[str | None, typer.Option("--valid-to")] = None,
    rationale_file: Annotated[Path | None, typer.Option("--rationale")] = None,
    evidence_file: Annotated[Path | None, typer.Option("--evidence")] = None,
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
) -> None:
    """Insert a candidate mapping assertion root."""
    try:
        evidence = _read_evidence(evidence_file)
        issuer_cik = validate_cik(issuer) if issuer is not None else None
        create = MappingAssertionCreate.model_validate(
            {
                "concept": concept,
                "target_metric_key": metric,
                "relation": relation,
                "scope_kind": "issuer" if issuer_cik is not None else "global",
                "issuer_cik": issuer_cik,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "method": method,
                "rationale": _read_text_file(rationale_file),
                "evidence": evidence,
                "created_by": created_by,
            }
        )
        assertion_id = _registry_service(registry_dir).propose_mapping(create)
    except (OSError, ValueError, RegistryError) as exc:
        _metric_cli_error(exc)
    typer.echo(f"proposed mapping assertion {assertion_id}")


@mappings_app.command("accept")
def mappings_accept(
    assertion_id: Annotated[int, typer.Argument(help="Current candidate assertion id")],
    created_by: Annotated[str, typer.Option("--created-by")],
    rationale_file: Annotated[Path | None, typer.Option("--rationale")] = None,
    evidence_file: Annotated[Path | None, typer.Option("--evidence")] = None,
    method: Annotated[str, typer.Option("--method")] = "human_review",
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
) -> None:
    """Accept a current candidate by inserting an accepted successor."""
    try:
        revision = MappingAssertionRevision.model_validate(
            {
                "method": method,
                "rationale": _read_text_file(rationale_file),
                "evidence": _read_evidence(evidence_file),
                "created_by": created_by,
            }
        )
        accepted_id = _registry_service(registry_dir).accept_mapping(assertion_id, revision)
    except (OSError, ValueError, RegistryError) as exc:
        _metric_cli_error(exc)
    typer.echo(f"accepted mapping assertion {accepted_id} (supersedes {assertion_id})")


@mappings_app.command("reject")
def mappings_reject(
    assertion_id: Annotated[int, typer.Argument(help="Current candidate or accepted assertion id")],
    reason: Annotated[str, typer.Option("--reason")],
    created_by: Annotated[str, typer.Option("--created-by")],
    method: Annotated[str, typer.Option("--method")] = "human_review",
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
) -> None:
    """Reject a current candidate or revoke a current accepted assertion."""
    try:
        revision = MappingAssertionRevision.model_validate(
            {
                "method": method,
                "rationale": reason,
                "created_by": created_by,
            }
        )
        rejected_id = _registry_service(registry_dir).reject_mapping(assertion_id, revision)
    except (OSError, ValueError, RegistryError) as exc:
        _metric_cli_error(exc)
    typer.echo(f"rejected mapping assertion {rejected_id} (supersedes {assertion_id})")


@mappings_app.command("export")
def mappings_export(
    fmt: Annotated[str, typer.Option("--format", help="json | jsonl | markdown")] = "json",
    registry_dir: Annotated[Path | None, typer.Option("--registry-dir")] = None,
) -> None:
    """Export current mapping assertions, including candidate and rejected."""
    if fmt not in {"json", "jsonl", "markdown"}:
        typer.echo(f"unsupported format: {fmt}", err=True)
        raise typer.Exit(code=1)
    try:
        reports = _registry_service(registry_dir).export_mappings()
    except (ValueError, RegistryError) as exc:
        _metric_cli_error(exc)
    if fmt == "json":
        typer.echo(dump_json(reports), nl=False)
    elif fmt == "jsonl":
        text = dump_jsonl(reports)
        if text:
            typer.echo(text, nl=False)
    else:
        typer.echo(dump_markdown(reports), nl=False)


if __name__ == "__main__":
    app()
