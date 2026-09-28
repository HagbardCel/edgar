from pathlib import Path

from edgar.financials.metalinks import parse_metalinks

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "metalinks_excerpt.json"


def test_metalinks_net_income_documentation() -> None:
    view = parse_metalinks(_FIXTURE.read_bytes())
    tag = view.tags["us-gaap_NetIncomeLoss"]
    assert "attributable to the parent" in tag["documentation"]
    assert len(view.statements) == 1
    assert view.statements[0].group_type == "statement"
