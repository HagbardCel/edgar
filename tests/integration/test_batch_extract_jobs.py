"""Batch extract: two fixture bundles, jobs=2, and a partial failure."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, func, select

from edgar.db import source_schema as src
from edgar.ingestion.batch_extract import run_batch_extract
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables
from tests.helpers.xbrl_bundles import INSTANCE, SCHEMA, _bundle_from_parts

pytestmark = pytest.mark.database

_ACC_A = "0000000001-00-000001"
_ACC_B = "0000000001-00-000002"
_ACC_MISSING = "0000000001-00-000099"


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


def _publish_two(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    repo = BundleRepository(tmp_path, store)
    for accession in (_ACC_A, _ACC_B):
        bundle = _bundle_from_parts(
            store=store,
            instance_bytes=INSTANCE,
            schema_bytes=SCHEMA,
            accession=accession,
        )
        repo.publish(bundle)


def _fact_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(src.source_filing.c.accession, func.count(src.source_fact.c.id))
            .join(
                src.source_xbrl_report,
                src.source_xbrl_report.c.filing_id == src.source_filing.c.id,
            )
            .join(src.source_fact, src.source_fact.c.report_id == src.source_xbrl_report.c.id)
            .group_by(src.source_filing.c.accession)
        )
    return {accession: int(count) for accession, count in rows}


def test_jobs_two_matches_jobs_one(engine: Engine, tmp_path: Path) -> None:
    _publish_two(tmp_path)
    url = test_database_url()
    first = run_batch_extract(
        data_root=tmp_path,
        database_url=url,
        accessions=(_ACC_B, _ACC_A),
        jobs=1,
    )
    assert first.ok
    counts_one = _fact_counts(engine)
    second = run_batch_extract(
        data_root=tmp_path,
        database_url=url,
        accessions=(_ACC_A, _ACC_B),
        jobs=2,
    )
    assert second.ok
    counts_two = _fact_counts(engine)
    assert counts_two == counts_one
    assert set(counts_two) == {_ACC_A, _ACC_B}
    assert all(count >= 1 for count in counts_two.values())
    assert [record.accession for record in second.records] == [_ACC_A, _ACC_B]


def test_failed_accession_leaves_sibling_committed(engine: Engine, tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    repo = BundleRepository(tmp_path, store)
    bundle = _bundle_from_parts(
        store=store,
        instance_bytes=INSTANCE,
        schema_bytes=SCHEMA,
        accession=_ACC_A,
    )
    repo.publish(bundle)
    url = test_database_url()
    result = run_batch_extract(
        data_root=tmp_path,
        database_url=url,
        accessions=(_ACC_MISSING, _ACC_A),
        jobs=2,
    )
    assert result.ok is False
    assert [record.accession for record in result.records] == [_ACC_A, _ACC_MISSING]
    assert result.records[0].success is True
    assert result.records[1].success is False
    assert result.records[1].failure_class == "BundleResolutionError"
    counts = _fact_counts(engine)
    assert counts[_ACC_A] >= 1
    assert _ACC_MISSING not in counts
