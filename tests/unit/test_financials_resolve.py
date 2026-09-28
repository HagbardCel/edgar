from decimal import Decimal
from pathlib import Path

from edgar.financials.decisions import load_decisions
from edgar.financials.models import FactRow, UnitMeasureRow
from edgar.financials.resolve import resolve_supports

_REGISTRY = Path(__file__).resolve().parents[2] / "registry"


def test_support_carries_clark_qname() -> None:
    registry = load_decisions(_REGISTRY)
    ns = "http://fasb.org/us-gaap/2023"
    fact = FactRow(
        fact_id=1,
        concept_namespace=ns,
        concept_local_name="Assets",
        source_qname=f"{{{ns}}}Assets",
        context_id=1,
        value_status="valid",
        resolved_numeric=Decimal("1"),
        is_nil=False,
        decimals="0",
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier="0001065088",
        period_kind="instant",
        instant_lexical="2023-12-31",
        start_lexical=None,
        end_lexical=None,
        has_dimensions=False,
        unit_measures=(
            UnitMeasureRow("numerator", 1, "http://www.xbrl.org/2003/iso4217", "USD"),
        ),
    )
    supports = resolve_supports((fact,), registry, "acc", "0001065088")
    assert supports
    assert supports[0].source_qname == f"{{{ns}}}Assets"
