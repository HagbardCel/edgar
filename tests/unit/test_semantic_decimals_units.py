"""Unit regressions for filed decimals/precision and unresolved unit measures."""

from __future__ import annotations

from types import SimpleNamespace

from edgar.xbrl.config import build_semantic_config
from edgar.xbrl.extract import (
    UNRESOLVED_UNIT_MEASURE,
    _DocumentUriResolver,
    _Extraction,
    _measure_rows,
    _optional_str,
)
from edgar.xbrl.records import SourceLocator


def test_reported_decimals_reads_filed_attribute_only() -> None:
    """Arelle may populate ``fact.decimals`` when the filed attribute is absent."""

    class _Fact:
        decimals = "INF"
        precision = "INF"

        def get(self, name: str, default=None):  # noqa: ANN001
            return default

    fact = _Fact()
    assert fact.decimals == "INF"
    assert _optional_str(fact.get("decimals")) is None
    assert _optional_str(fact.get("precision")) is None


def test_unresolved_unit_measure_is_incoherent() -> None:
    bound = SimpleNamespace(aliases={}, documents={"https://example.com/a.xml": object()})
    resolver = _DocumentUriResolver(bound, frozenset({"https://example.com/a.xml"}))
    extraction = _Extraction(config=build_semantic_config(), resolver=resolver)
    locator = SourceLocator(
        document_uri="https://example.com/a.xml",
        scheme="unqualified_id",
        value="u1",
    )
    unit = SimpleNamespace(
        measures=([object()], ()),
        find=lambda *_a, **_k: None,
        iterchildren=lambda *_a, **_k: iter([object()]),
    )
    _measure_rows(unit, unit_locator=locator, divide=False, extraction=extraction)
    assert any(issue.code == UNRESOLVED_UNIT_MEASURE for issue in extraction.errors)
