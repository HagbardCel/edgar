"""PostgreSQL FilingBundle catalog integration tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, select, text, update
from sqlalchemy.engine import make_url

from edgar.config import Settings
from edgar.db import schema as tables
from edgar.db.catalog import CatalogConflict, catalog_bundle, load_bundle
from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    IxdsReportInput,
    UriBinding,
    bundles_equivalent,
)
from edgar.ingestion.catalog import CatalogService
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore

pytestmark = pytest.mark.database

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"

CATALOG_TABLE_NAMES = (
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


def _test_database_url() -> str:
    """Sole source of the integration-test database URL (process env only)."""
    raw = os.environ.get("EDGAR_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("EDGAR_TEST_DATABASE_URL not set")
    url = make_url(raw)
    if url.database != "edgar_test":
        pytest.fail(
            "Refusing destructive database tests: "
            "EDGAR_TEST_DATABASE_URL must target database 'edgar_test'"
        )
    return raw


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.attributes["database_url"] = database_url
    return cfg


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = _test_database_url()
    eng = create_engine(url, future=True)
    command.upgrade(_alembic_config(url), "head")
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def truncate_catalog(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE " + ", ".join(CATALOG_TABLE_NAMES) + " RESTART IDENTITY CASCADE")
        )
    yield


def _publish_bundle(
    data_root: Path,
    *,
    cik: str = "0001065088",
    accession: str = "0001065088-24-000036",
    form_type: str = "10-K",
    payload_bytes: bytes = b"hello-world",
    document_uri: str = "https://example.com/a.htm",
    aliases: tuple[str, ...] = (),
    ixds: bool = False,
    extra_parts: tuple[bytes, ...] = (),
    filing_date: date = date(2024, 2, 12),
    accepted_at: datetime | None = None,
    primary_document: str = "a.htm",
) -> tuple[FilingBundle, Path, str]:
    store = ObjectStore(data_root)
    primary = store.put_bytes(payload_bytes)
    artifacts: list[BundleArtifact] = [
        BundleArtifact(
            logical_path="accession/a.htm",
            content=ContentObject(sha256=primary.sha256, byte_size=primary.byte_size),
            artifact_kind="primary_document",
            required=True,
        )
    ]
    bindings: list[UriBinding] = [
        UriBinding(
            document_uri=document_uri,
            artifact_path="accession/a.htm",
            content_sha256=primary.sha256,
            replay_aliases=aliases,
        )
    ]
    uris = [document_uri]
    for i, part in enumerate(extra_parts, start=2):
        obj = store.put_bytes(part)
        path = f"accession/part{i}.htm"
        uri = f"https://example.com/part{i}.htm"
        artifacts.append(
            BundleArtifact(
                logical_path=path,
                content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
                artifact_kind="attachment",
                required=True,
            )
        )
        bindings.append(
            UriBinding(
                document_uri=uri,
                artifact_path=path,
                content_sha256=obj.sha256,
            )
        )
        uris.append(uri)

    if ixds:
        report: InstanceReportInput | IxdsReportInput = IxdsReportInput(
            document_uris=tuple(uris),
            target="default",
        )
    else:
        report = InstanceReportInput(document_uris=(uris[0],))

    if accepted_at is None:
        accepted_at = datetime(2024, 2, 12, 15, 0, tzinfo=UTC)

    bundle = FilingBundle(
        filing=FilingIdentity(
            cik=cik,
            accession=accession,
            form_type=form_type,
            filing_date=filing_date,
            accepted_at=accepted_at,
            report_period_end=date(2023, 12, 31),
            primary_document=primary_document,
        ),
        payload_hash=compute_payload_hash(artifacts),
        artifacts=tuple(artifacts),
        report_inputs=(report,),
        uri_bindings=tuple(bindings),
    )
    repo = BundleRepository(data_root, store)
    published = repo.publish(bundle)
    return published.bundle, published.bundle_dir, published.opaque_id


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            name: int(conn.execute(text(f"SELECT count(*) FROM {name}")).scalar_one())
            for name in (
                "issuer",
                "filing",
                "filing_bundle",
                "bundle_artifact",
                "bundle_uri_binding",
                "content_object",
                "xbrl_report_input",
                "xbrl_report_input_member",
            )
        }


def test_migration_upgrade_downgrade_upgrade(engine: Engine) -> None:
    url = _test_database_url()
    cfg = _alembic_config(url)
    try:
        command.downgrade(cfg, "base")
        with engine.connect() as conn:
            reg = conn.execute(text("SELECT to_regclass('public.filing_bundle')"))
            assert reg.scalar_one() is None
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            reg = conn.execute(text("SELECT to_regclass('public.filing_bundle')"))
            assert reg.scalar_one()
            sem = conn.execute(text("SELECT to_regclass('public.semantic_projection')"))
            assert sem.scalar_one()
            fact = conn.execute(text("SELECT to_regclass('public.xbrl_fact')"))
            assert fact.scalar_one()
    finally:
        command.upgrade(cfg, "head")


def test_catalog_round_trip_ixds(engine: Engine, tmp_path: Path) -> None:
    bundle, _dir, opaque = _publish_bundle(
        tmp_path,
        ixds=True,
        extra_parts=(b"part-two", b"part-three"),
        aliases=("https://alias.example/a.htm",),
    )
    with engine.begin() as conn:
        result = catalog_bundle(conn, bundle, opaque)
        loaded = load_bundle(conn, result.bundle_id)
    assert bundles_equivalent(bundle, loaded)
    assert list(loaded.report_inputs[0].document_uris) == list(
        bundle.report_inputs[0].document_uris
    )
    assert set(loaded.uri_bindings[0].replay_aliases) == set(bundle.uri_bindings[0].replay_aliases)


def test_catalog_idempotent(engine: Engine, tmp_path: Path) -> None:
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    _bundle, bundle_dir, _opaque = _publish_bundle(tmp_path)
    service = CatalogService(settings, engine=engine)
    first = service.catalog_published_bundle(bundle_dir)
    counts = _counts(engine)
    second = service.catalog_published_bundle(bundle_dir)
    assert first.reused is False
    assert second.reused is True
    assert second.bundle_id == first.bundle_id
    assert _counts(engine) == counts


def test_cas_dedup_across_artifacts(engine: Engine, tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    obj = store.put_bytes(b"shared-bytes")
    art1 = BundleArtifact(
        logical_path="accession/a.htm",
        content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
        artifact_kind="primary_document",
        required=True,
    )
    art2 = BundleArtifact(
        logical_path="accession/copy.htm",
        content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
        artifact_kind="attachment",
        required=False,
    )
    uri1 = "https://example.com/a.htm"
    uri2 = "https://example.com/copy.htm"
    bundle = FilingBundle(
        filing=FilingIdentity(
            cik="0001065088",
            accession="0001065088-24-000036",
            form_type="10-K",
            filing_date=date(2024, 2, 12),
            accepted_at=datetime(2024, 2, 12, tzinfo=UTC),
            report_period_end=None,
            primary_document="a.htm",
        ),
        payload_hash=compute_payload_hash([art1, art2]),
        artifacts=(art1, art2),
        report_inputs=(InstanceReportInput(document_uris=(uri1,)),),
        uri_bindings=(
            UriBinding(
                document_uri=uri1,
                artifact_path=art1.logical_path,
                content_sha256=obj.sha256,
            ),
            UriBinding(
                document_uri=uri2,
                artifact_path=art2.logical_path,
                content_sha256=obj.sha256,
            ),
        ),
    )
    published = BundleRepository(tmp_path, store).publish(bundle)
    with engine.begin() as conn:
        catalog_bundle(conn, published.bundle, published.opaque_id)
    counts = _counts(engine)
    assert counts["content_object"] == 1
    assert counts["bundle_artifact"] == 2


def test_same_payload_hash_different_bindings_coexist(engine: Engine, tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    obj = store.put_bytes(b"payload")
    art = BundleArtifact(
        logical_path="accession/a.htm",
        content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
        artifact_kind="primary_document",
        required=True,
    )
    filing = FilingIdentity(
        cik="0001065088",
        accession="0001065088-24-000036",
        form_type="10-K",
        filing_date=date(2024, 2, 12),
        accepted_at=datetime(2024, 2, 12, tzinfo=UTC),
        report_period_end=None,
        primary_document="a.htm",
    )
    payload_hash = compute_payload_hash([art])
    left = FilingBundle(
        filing=filing,
        payload_hash=payload_hash,
        artifacts=(art,),
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/left.htm",)),),
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/left.htm",
                artifact_path=art.logical_path,
                content_sha256=obj.sha256,
            ),
        ),
    )
    right = FilingBundle(
        filing=filing,
        payload_hash=payload_hash,
        artifacts=(art,),
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/right.htm",)),),
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/right.htm",
                artifact_path=art.logical_path,
                content_sha256=obj.sha256,
            ),
        ),
    )
    assert left.payload_hash == right.payload_hash
    assert not bundles_equivalent(left, right)
    repo = BundleRepository(tmp_path, store)
    p1 = repo.publish(left)
    p2 = repo.publish(right)
    assert p1.opaque_id != p2.opaque_id
    with engine.begin() as conn:
        r1 = catalog_bundle(conn, p1.bundle, p1.opaque_id)
        r2 = catalog_bundle(conn, p2.bundle, p2.opaque_id)
    assert r1.bundle_id != r2.bundle_id
    assert _counts(engine)["filing_bundle"] == 2


def test_load_bundle_rejects_cross_bundle_artifact_binding(engine: Engine, tmp_path: Path) -> None:
    """Same path+SHA on A/B artifacts: ownership check must catch cross-link."""
    store = ObjectStore(tmp_path)
    obj = store.put_bytes(b"shared-payload")
    art = BundleArtifact(
        logical_path="accession/a.htm",
        content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
        artifact_kind="primary_document",
        required=True,
    )
    filing = FilingIdentity(
        cik="0001065088",
        accession="0001065088-24-000036",
        form_type="10-K",
        filing_date=date(2024, 2, 12),
        accepted_at=datetime(2024, 2, 12, tzinfo=UTC),
        report_period_end=None,
        primary_document="a.htm",
    )
    payload_hash = compute_payload_hash([art])
    left = FilingBundle(
        filing=filing,
        payload_hash=payload_hash,
        artifacts=(art,),
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/left.htm",)),),
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/left.htm",
                artifact_path=art.logical_path,
                content_sha256=obj.sha256,
            ),
        ),
    )
    right = FilingBundle(
        filing=filing,
        payload_hash=payload_hash,
        artifacts=(art,),
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/right.htm",)),),
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/right.htm",
                artifact_path=art.logical_path,
                content_sha256=obj.sha256,
            ),
        ),
    )
    repo = BundleRepository(tmp_path, store)
    p1 = repo.publish(left)
    p2 = repo.publish(right)
    with engine.begin() as conn:
        r1 = catalog_bundle(conn, p1.bundle, p1.opaque_id)
        r2 = catalog_bundle(conn, p2.bundle, p2.opaque_id)
        artifact_a_id = conn.execute(
            select(tables.bundle_artifact.c.id).where(
                tables.bundle_artifact.c.filing_bundle_id == r1.bundle_id
            )
        ).scalar_one()
        conn.execute(
            update(tables.bundle_uri_binding)
            .where(tables.bundle_uri_binding.c.filing_bundle_id == r2.bundle_id)
            .values(bundle_artifact_id=artifact_a_id)
        )
        with pytest.raises(CatalogConflict, match="invalid persisted"):
            load_bundle(conn, r2.bundle_id)


def test_filing_metadata_conflict(engine: Engine, tmp_path: Path) -> None:
    import uuid

    bundle, _d, opaque = _publish_bundle(tmp_path, filing_date=date(2024, 2, 12))
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)
    conflicting = FilingBundle(
        filing=FilingIdentity(
            cik=bundle.filing.cik,
            accession=bundle.filing.accession,
            form_type=bundle.filing.form_type,
            filing_date=date(2024, 2, 13),
            accepted_at=bundle.filing.accepted_at,
            report_period_end=bundle.filing.report_period_end,
            primary_document=bundle.filing.primary_document,
        ),
        payload_hash=bundle.payload_hash,
        artifacts=bundle.artifacts,
        report_inputs=bundle.report_inputs,
        uri_bindings=bundle.uri_bindings,
    )
    with pytest.raises(CatalogConflict), engine.begin() as conn:
        catalog_bundle(conn, conflicting, uuid.uuid4().hex)
    assert _counts(engine)["filing_bundle"] == 1


def test_sha_byte_size_conflict_rolls_back(engine: Engine, tmp_path: Path) -> None:
    bundle, _d, opaque = _publish_bundle(tmp_path, payload_bytes=b"abc")
    sha = bundle.artifacts[0].content.sha256
    size = bundle.artifacts[0].content.byte_size
    with engine.begin() as conn:
        conn.execute(tables.content_object.insert().values(sha256=sha, byte_size=size + 1))
    # Brand-new issuer/filing via different accession.
    other, _d2, opaque2 = _publish_bundle(
        tmp_path,
        cik="0000320193",
        accession="0000320193-24-000001",
        payload_bytes=b"abc",  # same bytes → same sha / size N
        document_uri="https://example.com/apple.htm",
        primary_document="apple.htm",
    )
    assert other.artifacts[0].content.sha256 == sha
    assert other.artifacts[0].content.byte_size == size
    with pytest.raises(CatalogConflict), engine.begin() as conn:
        catalog_bundle(conn, other, opaque2)
    counts = _counts(engine)
    assert counts["issuer"] == 0
    assert counts["filing"] == 0
    assert counts["filing_bundle"] == 0
    assert counts["content_object"] == 1
    with engine.connect() as conn:
        row = (
            conn.execute(select(tables.content_object).where(tables.content_object.c.sha256 == sha))
            .mappings()
            .one()
        )
        assert int(row["byte_size"]) == size + 1


def test_verified_reuse_structure_valid_mismatch(engine: Engine, tmp_path: Path) -> None:
    bundle, _d, opaque = _publish_bundle(tmp_path)
    with engine.begin() as conn:
        result = catalog_bundle(conn, bundle, opaque)
        conn.execute(
            update(tables.bundle_artifact)
            .where(tables.bundle_artifact.c.filing_bundle_id == result.bundle_id)
            .values(required=False)
        )
    with pytest.raises(CatalogConflict, match="not equivalent"), engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)


def test_load_bundle_rejects_corrupted_payload_hash(engine: Engine, tmp_path: Path) -> None:
    bundle, _d, opaque = _publish_bundle(tmp_path)
    bad_hash = "0" * 64
    assert bundle.payload_hash != bad_hash
    with engine.begin() as conn:
        result = catalog_bundle(conn, bundle, opaque)
        conn.execute(
            update(tables.filing_bundle)
            .where(tables.filing_bundle.c.id == result.bundle_id)
            .values(payload_hash=bad_hash)
        )
        with pytest.raises(CatalogConflict, match="invalid persisted"):
            load_bundle(conn, result.bundle_id)
