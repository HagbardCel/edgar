"""P1 gold build against corpus (opt-in).

Requires:
- EDGAR_TEST_DATABASE_URL targeting database ``edgar_test`` (see tests/helpers/database.py)
- EDGAR_DATA_ROOT with all six corpus bundles under ``bundles/{cik}/{accession}/…``

Skips when either prerequisite is missing. Does not use EDGAR_DATABASE_URL; use
``edgar build --check-gold`` against ``edgar`` for the CLI phase-exit gate.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine

from edgar.config import Settings
from edgar.corpus_manifest import load_corpus_manifest
from edgar.financials.build import default_accessions, run_build
from edgar.financials.gold import load_gold
from edgar.ingestion.source_extract import SourceExtractService
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from tests.helpers.database import reset_test_database, test_database_url

pytestmark = pytest.mark.database


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = test_database_url()
    eng = create_engine(url, future=True)
    reset_test_database(eng, database_url=url)
    yield eng
    eng.dispose()


_REPO = Path(__file__).resolve().parents[2]


def _corpus_bundles_present(data_root: Path) -> bool:
    manifest = load_corpus_manifest(_REPO / "fixtures" / "corpus.toml")
    for filing in manifest.filings:
        pattern = f"bundles/{filing.cik}/{filing.accession}"
        if not any(data_root.glob(f"{pattern}/*")):
            return False
    return True


def _published_bundle_dir(data_root: Path, cik: str, accession: str) -> Path:
    base = data_root / "bundles" / cik / accession
    candidates = [p for p in base.iterdir() if p.is_dir() and (p / "bundle.json").is_file()]
    if len(candidates) != 1:
        raise AssertionError(f"expected one published bundle under {base}, got {candidates}")
    return candidates[0]


def _extract_corpus(engine: Engine, data_root: Path) -> int:
    manifest = load_corpus_manifest(_REPO / "fixtures" / "corpus.toml")
    store = ObjectStore(data_root)
    repo = BundleRepository(data_root, store)
    settings = Settings().model_copy(update={"edgar_data_root": data_root})
    service = SourceExtractService(settings, engine=engine, bundles=repo)
    extracted = 0
    for filing in manifest.filings:
        bundle_dir = _published_bundle_dir(data_root, filing.cik, filing.accession)
        service.extract_published_bundle(bundle_dir)
        extracted += 1
    return extracted


def test_p1_gold_build(engine) -> None:  # noqa: ANN001
    data_root = os.environ.get("EDGAR_DATA_ROOT", "").strip()
    if not data_root:
        pytest.skip("EDGAR_DATA_ROOT not set")
    root = Path(data_root)
    if not _corpus_bundles_present(root):
        pytest.skip("corpus bundles not present under EDGAR_DATA_ROOT")
    registry_dir = _REPO / "registry"
    accessions = default_accessions(_REPO)
    assert len(accessions) == 6
    extracted = _extract_corpus(engine, root)
    assert extracted == 6
    result = run_build(engine, registry_dir, _REPO, accessions, check_gold=True)
    assert len(result.observations) == 48
    assert result.gold_assertions_checked == 19
    assert not result.gold_errors
    gold = load_gold(registry_dir / "gold" / "m0-annual.yml")
    value_assertions = [a for a in gold.assertions if a.status == "value"]
    assert len(value_assertions) == 15
