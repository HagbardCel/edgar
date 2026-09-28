from pathlib import Path

import yaml

from edgar.financials.cohort import M0_METRICS_ORDER, load_m0_cohort
from edgar.financials.gold import load_gold

_REPO = Path(__file__).resolve().parents[2]


def test_m0_gold_schema() -> None:
    gold = load_gold(_REPO / "registry" / "gold" / "m0-annual.yml")
    cohort = load_m0_cohort(_REPO / "registry")
    assert tuple(cohort.metrics) == M0_METRICS_ORDER
    value_rows = [a for a in gold.assertions if a.status == "value"]
    assert len(value_rows) == 15
    ids = {a.id for a in gold.assertions}
    assert ids == set(cohort.slots)
    assert len(ids) == len(gold.assertions)
    walmart_rnd = next(a for a in gold.assertions if a.id == "walmart_fy2024_rnd")
    assert walmart_rnd.status == "missing"
    assert walmart_rnd.reason is None
    raw = yaml.safe_load((_REPO / "registry" / "gold" / "m0-annual.yml").read_text())
    text = yaml.dump(raw)
    assert "capability_state" not in text
    assert "metric-v2" not in text
