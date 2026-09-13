"""Clean-DB gate: fresh alembic upgrade head creates source.* and registry.*."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select, text

from edgar.db import registry_schema as reg
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

        registry_exists = conn.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = 'registry')")
        ).scalar_one()
        assert registry_exists is True

        registry_tables = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'registry' "
                    "ORDER BY tablename"
                )
            )
        }
        assert registry_tables == {table.name for table in reg.REGISTRY_TABLES}

        for name in _ABSENT_PUBLIC_TABLES:
            present = conn.execute(
                text("SELECT to_regclass(:q)"),
                {"q": f"public.{name}"},
            ).scalar_one()
            assert present is None, f"legacy table still present: public.{name}"

        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "0002_registry"


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


def _sa_udt_name(col_type: object) -> str:
    from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Numeric, SmallInteger, Text
    from sqlalchemy.dialects.postgresql import JSONB, UUID

    if isinstance(col_type, UUID):
        return "uuid"
    if isinstance(col_type, JSONB):
        return "jsonb"
    if isinstance(col_type, DateTime):
        return "timestamptz"
    if isinstance(col_type, Numeric):
        return "numeric"
    if isinstance(col_type, BigInteger):
        return "int8"
    if isinstance(col_type, SmallInteger):
        return "int2"
    if isinstance(col_type, Integer):
        return "int4"
    if isinstance(col_type, Boolean):
        return "bool"
    if isinstance(col_type, Date):
        return "date"
    if isinstance(col_type, Text):
        return "text"
    raise TypeError(f"unsupported column type {col_type!r}")


def test_v2_clean_head_source_schema_column_parity(engine: Engine) -> None:
    """Live source_schema.py must match frozen 0001 DDL (drift detector)."""
    with engine.connect() as conn:
        columns = {
            (row.table_name, row.column_name): row
            for row in conn.execute(
                text(
                    """
                    SELECT table_name, column_name, is_nullable, udt_name
                    FROM information_schema.columns
                    WHERE table_schema = 'source'
                    """
                )
            )
        }
        constraints = {
            (row.table_name, row.constraint_name, row.constraint_type)
            for row in conn.execute(
                text(
                    """
                    SELECT c.relname AS table_name, con.conname AS constraint_name,
                           con.contype AS constraint_type
                    FROM pg_constraint con
                    JOIN pg_class c ON c.oid = con.conrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'source'
                    """
                )
            )
        }
        indexes = {
            row[0]
            for row in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'source'")
            )
        }

    expected_columns: set[tuple[str, str]] = set()
    expected_indexes: set[str] = set()
    expected_constraints: set[tuple[str, str, str]] = set()
    for table in src.SOURCE_TABLES:
        for col in table.columns:
            expected_columns.add((table.name, col.name))
            row = columns[(table.name, col.name)]
            expected_null = "YES" if col.nullable else "NO"
            assert row.is_nullable == expected_null, (table.name, col.name, row.is_nullable)
            assert row.udt_name == _sa_udt_name(col.type), (table.name, col.name, row.udt_name)
        for idx in table.indexes:
            expected_indexes.add(idx.name)
        for constraint in table.constraints:
            name = constraint.name
            if not name:
                continue
            visit = type(constraint).__name__
            kind = {
                "PrimaryKeyConstraint": "p",
                "UniqueConstraint": "u",
                "ForeignKeyConstraint": "f",
                "CheckConstraint": "c",
            }.get(visit)
            if kind is None:
                continue
            expected_constraints.add((table.name, name, kind))

    actual_columns = set(columns)
    assert actual_columns == expected_columns
    assert None not in expected_indexes
    assert all(name.startswith("ix_") for name in expected_indexes)
    actual_application_indexes = {name for name in indexes if name.startswith("ix_")}
    assert actual_application_indexes == expected_indexes
    assert constraints == expected_constraints
