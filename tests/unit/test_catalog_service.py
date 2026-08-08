"""Unit tests for domain equality / identity hardenings and catalog path gates."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from edgar.cli import app
from edgar.config import Settings
from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
    bundles_equivalent,
)
from edgar.domain.identifiers import validate_uuid4_hex
from edgar.ingestion.acquisition import AcquisitionResult
from edgar.ingestion.catalog import CatalogService
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.bundles import PublishResult


def _bundle(*, accepted_at: datetime | None) -> FilingBundle:
    sha = "ab" * 32
    art = BundleArtifact(
        logical_path="accession/a.xml",
        content=ContentObject(sha256=sha, byte_size=1),
        artifact_kind="attachment",
        required=True,
    )
    filing = FilingIdentity(
        cik="0001065088",
        accession="0001065088-24-000036",
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        accepted_at=accepted_at,
        report_period_end=date(2023, 12, 31),
        primary_document="a.htm",
    )
    return FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash([art]),
        artifacts=(art,),
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/a.xml",)),),
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/a.xml",
                artifact_path="accession/a.xml",
                content_sha256=sha,
            ),
        ),
    )


def test_accepted_at_same_instant_different_offsets_equivalent() -> None:
    utc = datetime(2026, 8, 8, 15, 0, 0, tzinfo=UTC)
    offset = timezone(timedelta(hours=2))
    local = utc.astimezone(offset)
    assert utc.isoformat() != local.isoformat()
    assert bundles_equivalent(_bundle(accepted_at=utc), _bundle(accepted_at=local))


def test_filing_identity_rejects_mismatched_cik_accession() -> None:
    with pytest.raises(ValueError, match="does not match"):
        FilingIdentity(
            cik="0001065088",
            accession="0000320193-24-000123",
            form_type="10-K",
            filing_date=date(2024, 1, 1),
            accepted_at=None,
            report_period_end=None,
            primary_document="a.htm",
        )


def test_validate_uuid4_hex() -> None:
    good = uuid.uuid4().hex
    assert validate_uuid4_hex(good) == good
    with pytest.raises(ValueError):
        validate_uuid4_hex("0" * 32)
    with pytest.raises(ValueError):
        validate_uuid4_hex("not-a-uuid")


def _fake_engine() -> MagicMock:
    engine = MagicMock()
    engine.begin.side_effect = AssertionError("engine.begin must not be called")
    return engine


def _assert_no_objects(settings: Settings) -> None:
    assert not (settings.edgar_data_root / "objects").exists()


def test_catalog_rejects_path_outside_data_root(tmp_path: Path) -> None:
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path / "data"})
    (settings.edgar_data_root / "bundles").mkdir(parents=True)
    outside = (
        tmp_path / "other" / "bundles" / "0001065088" / "0001065088-24-000036" / uuid.uuid4().hex
    )
    outside.mkdir(parents=True)
    service = CatalogService(settings, engine=_fake_engine())
    with pytest.raises(ValueError, match="escapes root"):
        service.catalog_published_bundle(outside)
    _assert_no_objects(settings)


def test_catalog_rejects_non_uuid4_opaque(tmp_path: Path) -> None:
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    bad = tmp_path / "bundles" / "0001065088" / "0001065088-24-000036" / ("0" * 32)
    bad.mkdir(parents=True)
    (bad / "bundle.json").write_text("{}", encoding="utf-8")
    service = CatalogService(settings, engine=_fake_engine())
    with pytest.raises(ValueError, match="uuid"):
        service.catalog_published_bundle(bad)
    _assert_no_objects(settings)


def test_catalog_rejects_noncanonical_cik_path(tmp_path: Path) -> None:
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    bad = tmp_path / "bundles" / "1065088" / "0001065088-24-000036" / uuid.uuid4().hex
    bad.mkdir(parents=True)
    (bad / "bundle.json").write_text("{}", encoding="utf-8")
    service = CatalogService(settings, engine=_fake_engine())
    with pytest.raises(ValueError, match="noncanonical CIK"):
        service.catalog_published_bundle(bad)
    _assert_no_objects(settings)


def test_catalog_corrupt_bundle_rejected_before_begin(tmp_path: Path) -> None:
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    bundle_dir = tmp_path / "bundles" / "0001065088" / "0001065088-24-000036" / uuid.uuid4().hex
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "bundle.json").write_text("{not-json", encoding="utf-8")
    service = CatalogService(settings, engine=_fake_engine())
    with pytest.raises(json.JSONDecodeError):
        service.catalog_published_bundle(bundle_dir)
    _assert_no_objects(settings)


def test_filings_retrieve_does_not_require_database_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("EDGAR_DATABASE_URL", raising=False)

    def _tripwire(self: Settings) -> str:
        raise AssertionError("require_database_url must not be called by filings retrieve")

    monkeypatch.setattr(Settings, "require_database_url", _tripwire)

    bundle = _bundle(accepted_at=datetime(2024, 1, 2, tzinfo=UTC))
    publish = PublishResult(
        bundle=bundle,
        bundle_dir=tmp_path / "bundle",
        opaque_id=uuid.uuid4().hex,
        reused=False,
    )
    fake_result = AcquisitionResult(
        bundle=bundle,
        publish=publish,
        attempt_id="test-attempt",
        attempt_path=tmp_path / "attempt",
        replay_faithful=True,
    )

    class _FakeAcquisitionService:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def __enter__(self) -> _FakeAcquisitionService:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def acquire(self, accession: str) -> AcquisitionResult:
            assert accession == "0001065088-24-000036"
            return fake_result

    monkeypatch.setattr("edgar.cli.AcquisitionService", _FakeAcquisitionService)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["filings", "retrieve", "--accession", "0001065088-24-000036", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert "0001065088-24-000036" in result.output
