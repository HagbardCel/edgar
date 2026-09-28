"""P1 gold build against corpus (opt-in via EDGAR_DATA_ROOT + bundles)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine

from edgar.corpus_manifest import load_corpus_manifest
from edgar.financials.build import default_accessions, run_build
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


def test_p1_gold_build(engine) -> None:  # noqa: ANN001
    data_root = os.environ.get("EDGAR_DATA_ROOT", "").strip()
    if not data_root:
        pytest.skip("EDGAR_DATA_ROOT not set")
    root = Path(data_root)
    if not _corpus_bundles_present(root):
        pytest.skip("corpus bundles not present under EDGAR_DATA_ROOT")
    registry_dir = _REPO / "registry"
    accessions = default_accessions(_REPO)
    run_build(engine, registry_dir, _REPO, accessions, check_gold=True)
