"""Clean-DB gate: fresh alembic upgrade head creates only source.* tables."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select, text

from edgar.db import source_schema as src
from edgar.db.source import catalog_source_filing
from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.objects import ObjectStore
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables

pytestmark = pytest.mark.database

_ABSENT_PUBLIC_TABLES = (
    "semantic_projection",
    "document_projection",
    "filing_bundle",
    "content_object",
    "bundle_uri_binding",
    "xbrl_report_input",
    "filing_document",
    "semantic_projection_attempt",
    "document_projection_attempt",
)


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


def test_v2_clean_head_source_schema_only(engine: Engine) -> None:
    with engine.connect() as conn:
        source_exists = conn.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = 'source')")
        ).scalar_one()
        assert source_exists is True

        source_tables = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'source' ORDER BY tablename"
                )
            )
        }
        expected = {table.name for table in src.SOURCE_TABLES}
        assert source_tables == expected

        for name in _ABSENT_PUBLIC_TABLES:
            present = conn.execute(
                text("SELECT to_regclass(:q)"),
                {"q": f"public.{name}"},
            ).scalar_one()
            assert present is None, f"legacy table still present: public.{name}"

        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "0001_source_v2"


def test_v2_clean_head_catalog_smoke(engine: Engine, tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    obj = store.put_bytes(b"hello-world")
    path = "accession/a.htm"
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
    bundle = FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(InstanceReportInput(document_uris=(uri,)),),
        uri_bindings=bindings,
    )
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        rows = conn.execute(
            select(src.source_document.c.id).where(
                src.source_document.c.filing_id == catalog.filing_id
            )
        ).all()
        assert len(rows) == catalog.document_count
        assert catalog.document_count >= 1
