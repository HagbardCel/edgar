"""PostgreSQL semantic projection integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, select, text, update

from edgar.config import Settings
from edgar.db import schema as tables
from edgar.db.catalog import catalog_bundle
from edgar.db.semantic import (
    SemanticProjectionConflict,
    catalog_semantic_projection,
    load_semantic_projection,
    record_semantic_projection_failure,
)
from edgar.projection.semantic import SemanticProjectionService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from edgar.xbrl.config import build_semantic_config, semantic_config_fingerprint
from edgar.xbrl.records import SemanticIssueRecord
from tests.helpers.database import alembic_config, test_database_url
from tests.helpers.xbrl_bundles import make_minimal_semantic_bundle

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


def _publish(tmp_path: Path) -> tuple[object, Path, str]:
    store = ObjectStore(tmp_path)
    bundle = make_minimal_semantic_bundle(store)
    repo = BundleRepository(tmp_path, store)
    published = repo.publish(bundle)
    return bundle, published.bundle_dir, published.opaque_id


def test_semantic_projection_round_trip_and_reuse(engine: Engine, tmp_path: Path) -> None:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    _bundle, bundle_dir, opaque = _publish(tmp_path)
    with engine.begin() as conn:
        catalog_bundle(conn, _bundle, opaque)

    service = SemanticProjectionService(settings, engine=engine)
    first = service.project_published_bundle(bundle_dir)
    assert first.projection.reused is False
    assert first.projection.status in {"complete", "incomplete"}
    assert first.projection.counts["facts"] >= 2

    second = service.project_published_bundle(bundle_dir)
    assert second.projection.reused is True
    assert second.projection.projection_id == first.projection.projection_id
    assert second.projection.attempt_id != first.projection.attempt_id


def test_failed_attempt_persists_config(engine: Engine, tmp_path: Path) -> None:
    bundle, _bundle_dir, opaque = _publish(tmp_path)
    with engine.begin() as conn:
        cataloged = catalog_bundle(conn, bundle, opaque)
        report_id = conn.execute(
            select(tables.xbrl_report_input.c.id).where(
                tables.xbrl_report_input.c.filing_bundle_id == cataloged.bundle_id
            )
        ).scalar_one()
        config = build_semantic_config()
        started = datetime.now(UTC)
        failure = record_semantic_projection_failure(
            conn,
            report_input_id=int(report_id),
            projection_version=config.projection_version,
            semantic_config=config.to_dict(),
            config_fingerprint=semantic_config_fingerprint(config),
            arelle_version=None,
            started_at=started,
            completed_at=datetime.now(UTC),
            issues=(
                SemanticIssueRecord(
                    severity="fatal",
                    code="TEST_FAILURE",
                    message="forced failure",
                ),
            ),
        )
        row = (
            conn.execute(
                select(tables.semantic_projection_attempt).where(
                    tables.semantic_projection_attempt.c.id == failure.attempt_id
                )
            )
            .mappings()
            .one()
        )
        assert row["status"] == "failed"
        assert row["semantic_projection_id"] is None
        assert row["arelle_version"] is None
        assert row["semantic_config_fingerprint"] == semantic_config_fingerprint(config)
        assert dict(row["semantic_config"]) == config.to_dict()
        proj_count = conn.execute(text("SELECT count(*) FROM semantic_projection")).scalar_one()
        assert int(proj_count) == 0


def test_projection_config_corruption_fails_load(engine: Engine, tmp_path: Path) -> None:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    bundle, bundle_dir, opaque = _publish(tmp_path)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)
    service = SemanticProjectionService(settings, engine=engine)
    result = service.project_published_bundle(bundle_dir)
    with engine.begin() as conn:
        conn.execute(
            update(tables.semantic_projection)
            .where(tables.semantic_projection.c.id == result.projection.projection_id)
            .values(semantic_config={"tampered": True})
        )
        with pytest.raises(SemanticProjectionConflict):
            load_semantic_projection(conn, result.projection.projection_id)


def test_preflight_uncataloged_creates_no_attempt(engine: Engine, tmp_path: Path) -> None:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    _bundle, bundle_dir, _opaque = _publish(tmp_path)
    service = SemanticProjectionService(settings, engine=engine)
    with pytest.raises(LookupError):
        service.project_published_bundle(bundle_dir)
    with engine.begin() as conn:
        attempts = conn.execute(
            text("SELECT count(*) FROM semantic_projection_attempt")
        ).scalar_one()
        assert int(attempts) == 0


def test_reuse_conflict_persists_failed_attempt(engine: Engine, tmp_path: Path) -> None:
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    bundle, bundle_dir, opaque = _publish(tmp_path)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)
    service = SemanticProjectionService(settings, engine=engine)
    first = service.project_published_bundle(bundle_dir)
    with engine.begin() as conn:
        # Corrupt persisted facts so verified reuse equality fails.
        conn.execute(text("DELETE FROM xbrl_fact"))
    from edgar.projection.semantic import SemanticProjectionError

    with pytest.raises(SemanticProjectionError):
        service.project_published_bundle(bundle_dir)
    with engine.begin() as conn:
        failed = conn.execute(
            text(
                "SELECT count(*) FROM semantic_projection_attempt "
                "WHERE status = 'failed' AND semantic_projection_id IS NULL"
            )
        ).scalar_one()
        assert int(failed) >= 1
        # Existing projection identity row remains.
        assert (
            int(
                conn.execute(
                    text("SELECT count(*) FROM semantic_projection WHERE id = :id"),
                    {"id": first.projection.projection_id},
                ).scalar_one()
            )
            == 1
        )


def test_cross_bundle_binding_rejected_on_insert(engine: Engine, tmp_path: Path) -> None:
    from dataclasses import replace

    from edgar.storage.bundles import BundleRepository
    from edgar.xbrl.config import build_semantic_config
    from edgar.xbrl.records import SourceLocator
    from edgar.xbrl.semantic import run_offline_semantic_projection

    store = ObjectStore(tmp_path)
    bundle = make_minimal_semantic_bundle(store)
    published = BundleRepository(tmp_path, store).publish(bundle)
    worker = run_offline_semantic_projection(bundle, store)
    config = build_semantic_config()
    with engine.begin() as conn:
        cataloged = catalog_bundle(conn, bundle, published.opaque_id)
        report_id = int(
            conn.execute(
                select(tables.xbrl_report_input.c.id).where(
                    tables.xbrl_report_input.c.filing_bundle_id == cataloged.bundle_id
                )
            ).scalar_one()
        )
        facts = list(worker.data.facts)
        bad = facts[0]
        facts[0] = replace(
            bad,
            source_locator=SourceLocator(
                document_uri="https://evil.example/not-in-bundle.xml",
                scheme=bad.source_locator.scheme,
                value=bad.source_locator.value,
            ),
        )
        mutated = replace(worker.data, facts=tuple(facts))
        started = datetime.now(UTC)
        with pytest.raises(SemanticProjectionConflict):
            catalog_semantic_projection(
                conn,
                report_input_id=report_id,
                bundle_id=cataloged.bundle_id,
                projection_data=mutated,
                status=worker.status,
                semantic_config=config.to_dict(),
                started_at=started,
                completed_at=datetime.now(UTC),
            )


def test_cross_projection_declaration_fk_rejected(engine: Engine, tmp_path: Path) -> None:
    """A fact pointing at another projection's concept_declaration fails on load."""
    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    store = ObjectStore(tmp_path)
    # Two published cataloged bundles → two projections sharing concept QName Assets.
    from edgar.storage.bundles import BundleRepository
    from tests.helpers.xbrl_bundles import make_unit_order_bundle

    a = make_minimal_semantic_bundle(store)
    repo = BundleRepository(tmp_path, store)
    pub_a = repo.publish(a)
    # Distinct opaque path for second publish: use separate data root subtree via second store root.
    root_b = tmp_path / "b"
    root_b.mkdir()
    store_b = ObjectStore(root_b)
    b2 = make_unit_order_bundle(store_b)
    repo_b = BundleRepository(root_b, store_b)
    pub_b = repo_b.publish(b2)

    with engine.begin() as conn:
        catalog_bundle(conn, a, pub_a.opaque_id)
    settings_a = settings
    service_a = SemanticProjectionService(settings_a, engine=engine)
    proj_a = service_a.project_published_bundle(pub_a.bundle_dir)

    settings_b = Settings().model_copy(
        update={"edgar_data_root": root_b, "edgar_database_url": test_database_url()}
    )
    with engine.begin() as conn:
        catalog_bundle(conn, b2, pub_b.opaque_id)
    service_b = SemanticProjectionService(settings_b, engine=engine)
    proj_b = service_b.project_published_bundle(pub_b.bundle_dir)

    with engine.begin() as conn:
        foreign_decl = conn.execute(
            text(
                "SELECT concept_declaration_id FROM xbrl_fact "
                "WHERE semantic_projection_id = :pid LIMIT 1"
            ),
            {"pid": proj_b.projection.projection_id},
        ).scalar_one()
        conn.execute(
            text(
                "UPDATE xbrl_fact SET concept_declaration_id = :decl "
                "WHERE semantic_projection_id = :pid"
            ),
            {"decl": foreign_decl, "pid": proj_a.projection.projection_id},
        )
        with pytest.raises(SemanticProjectionConflict):
            load_semantic_projection(conn, proj_a.projection.projection_id)


def test_config_fingerprint_coexistence(engine: Engine, tmp_path: Path) -> None:
    """Same report/version/arelle, different semantic_config → two projection ids."""
    from dataclasses import replace

    from edgar.storage.bundles import BundleRepository
    from edgar.xbrl.semantic import run_offline_semantic_projection

    store = ObjectStore(tmp_path)
    bundle = make_minimal_semantic_bundle(store)
    published = BundleRepository(tmp_path, store).publish(bundle)
    worker = run_offline_semantic_projection(bundle, store)
    config_a = build_semantic_config()
    config_b = build_semantic_config(item_facts_only=False)
    assert semantic_config_fingerprint(config_a) != semantic_config_fingerprint(config_b)

    with engine.begin() as conn:
        cataloged = catalog_bundle(conn, bundle, published.opaque_id)
        report_id = int(
            conn.execute(
                select(tables.xbrl_report_input.c.id).where(
                    tables.xbrl_report_input.c.filing_bundle_id == cataloged.bundle_id
                )
            ).scalar_one()
        )
        started = datetime.now(UTC)
        first = catalog_semantic_projection(
            conn,
            report_input_id=report_id,
            bundle_id=cataloged.bundle_id,
            projection_data=replace(
                worker.data,
                config_fingerprint=semantic_config_fingerprint(config_a),
            ),
            status=worker.status,
            semantic_config=config_a.to_dict(),
            started_at=started,
            completed_at=datetime.now(UTC),
        )
        second = catalog_semantic_projection(
            conn,
            report_input_id=report_id,
            bundle_id=cataloged.bundle_id,
            projection_data=replace(
                worker.data,
                config_fingerprint=semantic_config_fingerprint(config_b),
            ),
            status=worker.status,
            semantic_config=config_b.to_dict(),
            started_at=started,
            completed_at=datetime.now(UTC),
        )
        assert first.projection_id != second.projection_id
        assert first.arelle_version == second.arelle_version == worker.data.engine_version
        count = conn.execute(text("SELECT count(*) FROM semantic_projection")).scalar_one()
        assert int(count) == 2


def test_supported_network_worker_error_records_failed_attempt(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar.projection.semantic import SemanticProjectionError
    from edgar.xbrl.extract import ENDPOINT_FAMILY_MISMATCH
    from edgar.xbrl.replay_normalize import NormalizedReplayView
    from edgar.xbrl.semantic import SemanticWorkerError

    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    bundle, bundle_dir, opaque = _publish(tmp_path)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)

    def boom(*_args, **_kwargs):  # noqa: ANN001
        replay = NormalizedReplayView(
            load_completed=True,
            network_attempts=(),
            unresolved_documents=(),
            loaded_source_documents=(),
            resolved_documents=(),
            expected_binding_documents=(),
            diagnostics=(),
            errors=(),
            closure_equal=True,
        )
        raise SemanticWorkerError(
            "supported network incoherent",
            replay=replay,
            issues=(
                SemanticIssueRecord(
                    severity="fatal",
                    code=ENDPOINT_FAMILY_MISMATCH,
                    message="stub network failure",
                ),
            ),
            arelle_version="test-arelle",
        )

    monkeypatch.setattr(
        "edgar.projection.semantic.run_offline_semantic_projection",
        boom,
    )
    service = SemanticProjectionService(settings, engine=engine)
    with pytest.raises(SemanticProjectionError):
        service.project_published_bundle(bundle_dir)
    with engine.begin() as conn:
        failed = conn.execute(
            text(
                "SELECT count(*) FROM semantic_projection_attempt "
                "WHERE status = 'failed' AND semantic_projection_id IS NULL"
            )
        ).scalar_one()
        assert int(failed) == 1
        assert int(conn.execute(text("SELECT count(*) FROM semantic_projection")).scalar_one()) == 0
        codes = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT code FROM semantic_issue "
                    "WHERE semantic_projection_attempt_id IS NOT NULL"
                )
            )
        ]
        assert ENDPOINT_FAMILY_MISMATCH in codes


def test_worker_process_error_records_failed_attempt(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edgar.projection.semantic import SemanticProjectionError
    from edgar.xbrl.closure import WorkerProtocolError

    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    bundle, bundle_dir, opaque = _publish(tmp_path)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)

    def boom(*_args, **_kwargs):  # noqa: ANN001
        raise WorkerProtocolError("worker exited without a result")

    monkeypatch.setattr("edgar.xbrl.semantic.run_worker_process", boom)
    service = SemanticProjectionService(settings, engine=engine)
    with pytest.raises(SemanticProjectionError):
        service.project_published_bundle(bundle_dir)

    expected_config = build_semantic_config()
    expected_fingerprint = semantic_config_fingerprint(expected_config)
    with engine.begin() as conn:
        rows = list(
            conn.execute(
                text(
                    "SELECT status, arelle_version, semantic_config, "
                    "semantic_config_fingerprint, semantic_projection_id "
                    "FROM semantic_projection_attempt"
                )
            ).mappings()
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "failed"
        assert row["arelle_version"] is None
        assert row["semantic_projection_id"] is None
        assert dict(row["semantic_config"]) == expected_config.to_dict()
        assert row["semantic_config_fingerprint"] == expected_fingerprint
        assert int(conn.execute(text("SELECT count(*) FROM semantic_projection")).scalar_one()) == 0
        codes = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT code FROM semantic_issue "
                    "WHERE semantic_projection_attempt_id IS NOT NULL"
                )
            )
        ]
        assert codes == ["SEMANTIC_WORKER_PROCESS_FAILED"]


def test_resolved_value_coherence_check_rejects_kind_null_with_numeric(
    engine: Engine, tmp_path: Path
) -> None:
    from sqlalchemy.exc import IntegrityError

    settings = Settings().model_copy(
        update={"edgar_data_root": tmp_path, "edgar_database_url": test_database_url()}
    )
    bundle, bundle_dir, opaque = _publish(tmp_path)
    with engine.begin() as conn:
        catalog_bundle(conn, bundle, opaque)
    service = SemanticProjectionService(settings, engine=engine)
    result = service.project_published_bundle(bundle_dir)
    projection_id = result.projection.projection_id

    with engine.begin() as conn:
        numeric_facts = (
            conn.execute(
                text(
                    "SELECT id, resolved_value_text, resolved_numeric "
                    "FROM xbrl_fact "
                    "WHERE semantic_projection_id = :pid AND resolved_value_kind = 'numeric'"
                ),
                {"pid": projection_id},
            )
            .mappings()
            .all()
        )
        assert numeric_facts
        for fact in numeric_facts:
            assert fact["resolved_value_text"] is None
            assert fact["resolved_numeric"] is not None

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            update(tables.xbrl_fact)
            .where(tables.xbrl_fact.c.semantic_projection_id == projection_id)
            .where(tables.xbrl_fact.c.resolved_value_kind == "numeric")
            .values(resolved_value_kind=None)
        )
