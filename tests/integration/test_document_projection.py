"""PostgreSQL document projection integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, select, text, update

from edgar.config import Settings
from edgar.db import schema as tables
from edgar.db.catalog import catalog_bundle
from edgar.db.document import (
    load_document_projection,
)
from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.ingestion.payload import compute_payload_hash
from edgar.parsing.config import build_document_config, document_config_fingerprint
from edgar.projection.document import (
    DocumentPreflightError,
    DocumentProjectionError,
    DocumentProjectionService,
)
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from tests.helpers.database import alembic_config, test_database_url
from tests.helpers.document_fixtures import RICH_10K_HTML

pytestmark = pytest.mark.database

TABLE_NAMES = (
    "filing_section",
    "document_block",
    "document_issue",
    "document_projection_attempt",
    "document_projection",
    "filing_document",
    "xbrl_relationship",
    "xbrl_fact",
    "xbrl_unit_measure",
    "xbrl_unit",
    "xbrl_context_dimension",
    "xbrl_context",
    "concept_reference",
    "concept_label",
    "concept_declaration",
    "concept_identity",
    "role_declaration",
    "arcrole_declaration",
    "semantic_issue",
    "semantic_projection_attempt",
    "semantic_projection",
    "xbrl_report_input_member",
    "xbrl_report_input",
    "bundle_uri_binding",
    "bundle_artifact",
    "filing_bundle",
    "content_object",
    "filing",
    "issuer",
)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = test_database_url()
    eng = create_engine(url, future=True)
    command.upgrade(alembic_config(url), "head")
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def truncate_all(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(TABLE_NAMES) + " RESTART IDENTITY CASCADE"))
    yield


def _publish_html_bundle(
    data_root: Path,
    *,
    primary_html: bytes = RICH_10K_HTML,
    exhibit_html: bytes | None = b"<html><body><p>Exhibit only.</p></body></html>",
    form_type: str = "10-K",
    primary_name: str = "primary.htm",
) -> tuple[FilingBundle, Path, str]:
    store = ObjectStore(data_root)
    primary = store.put_bytes(primary_html)
    artifacts: list[BundleArtifact] = [
        BundleArtifact(
            logical_path=f"accession/{primary_name}",
            content=ContentObject(sha256=primary.sha256, byte_size=primary.byte_size),
            artifact_kind="primary_document",
            required=True,
        )
    ]
    bindings: list[UriBinding] = [
        UriBinding(
            document_uri=f"https://example.com/{primary_name}",
            artifact_path=f"accession/{primary_name}",
            content_sha256=primary.sha256,
        )
    ]
    if exhibit_html is not None:
        exhibit = store.put_bytes(exhibit_html)
        artifacts.append(
            BundleArtifact(
                logical_path="accession/exhibit.htm",
                content=ContentObject(sha256=exhibit.sha256, byte_size=exhibit.byte_size),
                artifact_kind="attachment",
                required=True,
            )
        )
        bindings.append(
            UriBinding(
                document_uri="https://example.com/exhibit.htm",
                artifact_path="accession/exhibit.htm",
                content_sha256=exhibit.sha256,
            )
        )
    report = InstanceReportInput(document_uris=(bindings[0].document_uri,))
    bundle = FilingBundle(
        filing=FilingIdentity(
            cik="0000000001",
            accession="0000000001-00-000001",
            form_type=form_type,
            filing_date=date(2024, 1, 1),
            accepted_at=datetime(2024, 1, 2, tzinfo=UTC),
            report_period_end=date(2023, 12, 31),
            primary_document=primary_name,
        ),
        payload_hash=compute_payload_hash(tuple(artifacts)),
        artifacts=tuple(artifacts),
        report_inputs=(report,),
        uri_bindings=tuple(bindings),
    )
    repo = BundleRepository(data_root, store)
    published = repo.publish(bundle)
    return published.bundle, published.bundle_dir, published.opaque_id


def test_migration_includes_document_tables(engine: Engine) -> None:
    url = test_database_url()
    cfg = alembic_config(url)
    command.downgrade(cfg, "0002_semantic_projection")
    with engine.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            )
        }
        assert "document_projection" not in names
    try:
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            names = {
                row[0]
                for row in conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                )
            }
            assert "filing_document" in names
            assert "document_projection" in names
            assert "filing_section" in names
    finally:
        command.upgrade(cfg, "head")


def test_document_projection_round_trip_reuse_and_reconstruct(
    engine: Engine, tmp_path: Path
) -> None:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    bundle, bundle_dir, opaque = _publish_html_bundle(tmp_path)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)

    service = DocumentProjectionService(settings, engine=engine)
    first = service.project_published_bundle(bundle_dir)
    assert first.projection.reused is False
    assert first.projection.counts["blocks"] > 0
    assert first.projection.counts["sections"] >= 1

    with engine.connect() as conn:
        data, status = load_document_projection(conn, first.projection.projection_id)
    item8 = next(s for s in data.sections if s.section_key.endswith("item_8.financial_statements"))
    body = " ".join(
        b.text or ""
        for b in data.blocks
        if item8.start_block_ordinal <= b.ordinal < item8.end_block_ordinal_exclusive
    )
    assert "SIGNATURES" not in body
    assert "Financial" in body or "financial" in body.lower() or "1000" in body

    second = service.project_published_bundle(bundle_dir)
    assert second.projection.reused is True
    assert second.projection.projection_id == first.projection.projection_id
    assert second.projection.attempt_id != first.projection.attempt_id


def test_attachment_blocks_without_sections(engine: Engine, tmp_path: Path) -> None:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    bundle, bundle_dir, opaque = _publish_html_bundle(tmp_path)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)
    service = DocumentProjectionService(settings, engine=engine)
    primary = service.project_published_bundle(bundle_dir)
    exhibit = service.project_published_bundle(bundle_dir, artifact_path="accession/exhibit.htm")
    assert primary.filing_document_id != exhibit.filing_document_id
    assert primary.projection.projection_id != exhibit.projection.projection_id
    assert exhibit.projection.counts["sections"] == 0
    with engine.connect() as conn:
        issue_count = conn.execute(
            select(tables.document_issue.c.id).where(
                tables.document_issue.c.document_projection_id == exhibit.projection.projection_id
            )
        ).all()
    assert issue_count == []


def test_preflight_uncataloged_and_unsupported(engine: Engine, tmp_path: Path) -> None:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    _bundle, bundle_dir, _opaque = _publish_html_bundle(tmp_path)
    service = DocumentProjectionService(settings, engine=engine)
    with pytest.raises(LookupError):
        service.project_published_bundle(bundle_dir)
    with engine.begin() as conn:
        catalog_bundle(conn, _bundle, _opaque)
    with pytest.raises(DocumentPreflightError):
        service.project_published_bundle(bundle_dir, artifact_path="accession/missing.htm")
    with engine.connect() as conn:
        attempts = conn.execute(
            text("SELECT count(*) FROM document_projection_attempt")
        ).scalar_one()
    assert int(attempts) == 0


def test_parse_failure_failed_attempt(engine: Engine, tmp_path: Path) -> None:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    bundle, bundle_dir, opaque = _publish_html_bundle(tmp_path, primary_html=b"   ")
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)
    service = DocumentProjectionService(settings, engine=engine)
    with pytest.raises(DocumentProjectionError):
        service.project_published_bundle(bundle_dir)
    with engine.connect() as conn:
        row = conn.execute(select(tables.document_projection_attempt)).mappings().one()
        assert row["status"] == "failed"
        assert row["document_projection_id"] is None
        assert int(conn.execute(text("SELECT count(*) FROM document_projection")).scalar_one()) == 0


def test_config_fingerprint_coexistence(engine: Engine, tmp_path: Path) -> None:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    bundle, bundle_dir, opaque = _publish_html_bundle(tmp_path)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)
    service = DocumentProjectionService(settings, engine=engine)
    first = service.project_published_bundle(bundle_dir)
    # Force a second projection identity by corrupting is not allowed; instead insert via
    # alternate fingerprint through direct catalog after mutating loaded config version.
    from edgar.db.document import catalog_document_projection, ensure_filing_document
    from edgar.parsing.html import parse_html_document
    from edgar.parsing.records import DocumentProjectionData
    from edgar.parsing.sections import extract_filing_sections

    html = ObjectStore(tmp_path).open_bytes(bundle.artifacts[0].content.sha256)
    parsed = parse_html_document(html)
    sections, issues, status, _ = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    alt_config = build_document_config(block_extractor="block-extractor-v1-test")
    data = DocumentProjectionData(
        parser_version=alt_config.parser_version,
        config_fingerprint=document_config_fingerprint(alt_config),
        blocks=parsed.blocks,
        sections=tuple(sections),
        issues=tuple(list(parsed.issues) + list(issues)),
    )
    with engine.begin() as conn:
        artifact_id = conn.execute(
            select(tables.bundle_artifact.c.id).where(
                tables.bundle_artifact.c.logical_path == bundle.artifacts[0].logical_path
            )
        ).scalar_one()
        fd_id = ensure_filing_document(conn, int(artifact_id))
        second = catalog_document_projection(
            conn,
            filing_document_id=fd_id,
            projection_data=data,
            status=status,
            parser_config=alt_config.to_dict(),
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
    assert second.projection_id != first.projection.projection_id


def test_reuse_conflict_persists_failed_attempt(engine: Engine, tmp_path: Path) -> None:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    bundle, bundle_dir, opaque = _publish_html_bundle(tmp_path)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)
    service = DocumentProjectionService(settings, engine=engine)
    first = service.project_published_bundle(bundle_dir)
    with engine.begin() as conn:
        conn.execute(
            update(tables.document_block)
            .where(tables.document_block.c.document_projection_id == first.projection.projection_id)
            .values(text="tampered")
        )
    with pytest.raises(DocumentProjectionError) as exc_info:
        service.project_published_bundle(bundle_dir)
    assert exc_info.value.failure is not None
    with engine.connect() as conn:
        failed = (
            conn.execute(
                select(tables.document_projection_attempt).where(
                    tables.document_projection_attempt.c.status == "failed"
                )
            )
            .mappings()
            .all()
        )
        assert len(failed) >= 1
        # Original projection still present
        data, _ = load_document_projection(conn, first.projection.projection_id)
        assert any(b.text == "tampered" for b in data.blocks)
