"""Unit tests for build orchestration edges."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from edgar.financials.build import run_build

_REPO = Path(__file__).resolve().parents[2]


def test_check_gold_requires_m0_annual_file(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    shutil.copytree(_REPO / "registry", registry_dir)
    (registry_dir / "gold" / "m0-annual.yml").unlink()
    engine = MagicMock()
    with pytest.raises(ValueError, match="gold file missing"):
        run_build(engine, registry_dir, _REPO, (), check_gold=True)
