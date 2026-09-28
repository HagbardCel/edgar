from pathlib import Path

from edgar.financials.rules_check import run_rules_check

_REPO = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO / "registry"


def test_stale_rejected_emits_warning(tmp_path: Path) -> None:
    import shutil

    registry_dir = tmp_path / "registry"
    shutil.copytree(_REGISTRY, registry_dir)
    rejected = (
        registry_dir
        / "decisions"
        / "revenue"
        / "revenue.us-gaap.GrossProfit.rejected.yml"
    )
    text = rejected.read_text(encoding="utf-8")
    rejected.write_text(
        text.replace(
            "contract_hash: ba6bdf8e41ec0789a0acdb855b971aed4bca023c6b76b5eca531e7d76cd683d1",
            'contract_hash: "' + "0" * 64 + '"',
        ),
        encoding="utf-8",
    )
    warnings = [
        f
        for f in run_rules_check(registry_dir)
        if f.level == "warning" and "stale rejected" in f.message
    ]
    assert warnings
