"""PostgreSQL integration tests for Phase 2B source catalog and schema contracts."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import IntegrityError

from edgar.db import source_schema as src
from edgar.db.source import SourceCatalogConflict, catalog_source_filing
from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.domain.concept_id import concept_id
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.objects import ObjectStore
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables

pytestmark = pytest.mark.database


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = test_database_url()
    eng = create_engine(url, future=True)
    reset_test_database(eng, database_url=url)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def truncate_tables(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        truncate_all_tables(conn)
    yield


def _make_bundle(
    data_root: Path,
    *,
    payload: bytes = b"hello-world",
    path: str = "accession/a.htm",
) -> FilingBundle:
    store = ObjectStore(data_root)
    obj = store.put_bytes(payload)
    artifacts = (
        BundleArtifact(
            logical_path=path,
            content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
    )
    uri = "https://example.com/a.htm"
    bindings = (
        UriBinding(
            document_uri=uri,
            artifact_path=path,
            content_sha256=obj.sha256,
            replay_aliases=(),
        ),
    )
    filing = FilingIdentity(
        cik="0001065088",
        accession="0001065088-24-000036",
        form_type="10-K",
        filing_date=date(2024, 2, 28),
        accepted_at=None,
        report_period_end=date(2023, 12, 31),
        primary_document="a.htm",
    )
    return FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(InstanceReportInput(document_uris=(uri,)),),
        uri_bindings=bindings,
    )


def test_source_schema_exists(engine: Engine) -> None:
    with engine.connect() as conn:
        schemas = {
            row[0]
            for row in conn.execute(text("SELECT schema_name FROM information_schema.schemata"))
        }
        assert "source" in schemas
        tables = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'source'"
                )
            )
        }
        assert "issuer" in tables
        assert "filing" in tables
        assert "document" in tables
        assert "fact" in tables
        assert "xbrl_report" in tables


def test_catalog_source_filing_idempotent(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    with engine.begin() as conn:
        first = catalog_source_filing(conn, bundle, issuer_name="eBay Inc.")
        second = catalog_source_filing(conn, bundle, issuer_name="eBay Inc.")
    assert first.reused is False
    assert second.reused is True
    assert first.filing_id == second.filing_id
    assert first.document_count == 1


def test_catalog_rejects_form_mismatch(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    with engine.begin() as conn:
        catalog_source_filing(conn, bundle)

    from dataclasses import replace

    changed = FilingBundle(
        filing=replace(bundle.filing, form_type="10-Q"),
        payload_hash=bundle.payload_hash,
        artifacts=bundle.artifacts,
        report_inputs=bundle.report_inputs,
        uri_bindings=bundle.uri_bindings,
    )
    with engine.begin() as conn, pytest.raises(SourceCatalogConflict, match="form mismatch"):
        catalog_source_filing(conn, changed)


def test_catalog_rejects_document_kind_mismatch(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    with engine.begin() as conn:
        catalog_source_filing(conn, bundle)

    from dataclasses import replace

    art = bundle.artifacts[0]
    changed_art = replace(art, artifact_kind="attachment")
    changed = FilingBundle(
        filing=bundle.filing,
        payload_hash=bundle.payload_hash,
        artifacts=(changed_art,),
        report_inputs=bundle.report_inputs,
        uri_bindings=bundle.uri_bindings,
    )
    with engine.begin() as conn, pytest.raises(SourceCatalogConflict, match="document_kind"):
        catalog_source_filing(conn, changed)


def test_catalog_rejects_sha256_change(engine: Engine, tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path, payload=b"original")
    with engine.begin() as conn:
        catalog_source_filing(conn, bundle)

    other = _make_bundle(tmp_path / "b", payload=b"changed-bytes!!")
    # Same accession/path via reconstructing with different sha under same accession.
    conflict = FilingBundle(
        filing=bundle.filing,
        payload_hash=other.payload_hash,
        artifacts=other.artifacts,
        report_inputs=bundle.report_inputs,
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/a.htm",
                artifact_path=other.artifacts[0].logical_path,
                content_sha256=other.artifacts[0].content.sha256,
                replay_aliases=(),
            ),
        ),
    )
    with (
        engine.begin() as conn,
        pytest.raises(SourceCatalogConflict, match="inventory mismatch"),
    ):
        catalog_source_filing(conn, conflict)


def test_delete_report_cascades_leaves_concepts(engine: Engine, tmp_path: Path) -> None:
    from datetime import UTC, datetime

    bundle = _make_bundle(tmp_path)
    ns = "http://example.com/ns"
    local = "Revenue"
    cid = concept_id(ns, local)

    with engine.begin() as conn:
        result = catalog_source_filing(conn, bundle)
        conn.execute(
            src.source_concept.insert().values(
                id=cid,
                namespace_uri=ns,
                local_name=local,
            )
        )
        report_id = conn.execute(
            src.source_xbrl_report.insert()
            .values(
                filing_id=result.filing_id,
                report_key="a" * 64,
                report_input={"kind": "instance", "document_uris": ["https://example.com/a.htm"]},
                extractor_version="test",
                arelle_version="2.43.1",
                extracted_at=datetime(2024, 1, 1, tzinfo=UTC),
                arelle_item_fact_count=0,
            )
            .returning(src.source_xbrl_report.c.id)
        ).scalar_one()
        conn.execute(
            src.source_concept_declaration.insert().values(
                report_id=report_id,
                concept_id=cid,
                data_type="monetaryItemType",
                period_type="duration",
                balance="credit",
                abstract=False,
                nillable=True,
                substitution_group=None,
            )
        )
        conn.execute(
            src.source_xbrl_report.delete().where(src.source_xbrl_report.c.id == report_id)
        )
        decls = conn.execute(select(src.source_concept_declaration.c.id)).all()
        assert decls == []
        remaining = conn.execute(
            select(src.source_concept.c.id).where(src.source_concept.c.id == cid)
        ).scalar_one()
        assert UUID(str(remaining)) == cid
        filing_still = conn.execute(
            select(src.source_filing.c.id).where(src.source_filing.c.id == result.filing_id)
        ).scalar_one()
        assert int(filing_still) == result.filing_id


def test_context_period_check(engine: Engine, tmp_path: Path) -> None:
    from datetime import UTC, datetime

    bundle = _make_bundle(tmp_path)
    with engine.begin() as conn:
        result = catalog_source_filing(conn, bundle)
        report_id = conn.execute(
            src.source_xbrl_report.insert()
            .values(
                filing_id=result.filing_id,
                report_key="b" * 64,
                report_input={"kind": "instance", "document_uris": ["https://example.com/a.htm"]},
                extractor_version="test",
                arelle_version="2.43.1",
                extracted_at=datetime(2024, 1, 1, tzinfo=UTC),
                arelle_item_fact_count=0,
            )
            .returning(src.source_xbrl_report.c.id)
        ).scalar_one()
        with pytest.raises(IntegrityError):
            conn.execute(
                src.source_context.insert().values(
                    report_id=report_id,
                    source_context_id="c1",
                    entity_scheme="http://www.sec.gov/CIK",
                    entity_identifier="0001065088",
                    period_kind="instant",
                    instant=None,
                    start_date=date(2023, 1, 1),
                    end_date=date(2023, 12, 31),
                )
            )
