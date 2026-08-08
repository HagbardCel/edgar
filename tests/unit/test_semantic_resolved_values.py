"""Unit tests for resolved-value kind/text/numeric coherence."""

from __future__ import annotations

from decimal import Decimal

import pytest

from edgar.db.semantic import (
    SemanticProjectionConflict,
    _resolved_value_fields,
    _validate_resolved_value_fields,
)
from edgar.xbrl.records import ExpandedQName, FactRecord, SourceLocator


def _loc(name: str) -> SourceLocator:
    return SourceLocator(
        document_uri="https://example.com/a.xml",
        scheme="unqualified_id",
        value=name,
    )


def _q(local: str) -> ExpandedQName:
    return ExpandedQName(namespace_uri="http://example.com", local_name=local)


def test_validate_accepts_coherent_states() -> None:
    assert _validate_resolved_value_fields(None, None, None) == (None, None, None)
    assert _validate_resolved_value_fields("numeric", None, Decimal("100")) == (
        "numeric",
        None,
        Decimal("100"),
    )
    assert _validate_resolved_value_fields("text", "hello", None) == ("text", "hello", None)
    assert _validate_resolved_value_fields("boolean", "true", None) == ("boolean", "true", None)


@pytest.mark.parametrize(
    ("kind", "text", "numeric"),
    [
        (None, None, Decimal("1")),
        ("numeric", "1", Decimal("1")),
        ("text", None, None),
        ("text", "hello", Decimal("1")),
        ("garbage", "foo", None),
    ],
)
def test_validate_rejects_incoherent_triples(
    kind: str | None, text: str | None, numeric: Decimal | None
) -> None:
    with pytest.raises(SemanticProjectionConflict):
        _validate_resolved_value_fields(kind, text, numeric)


def test_resolved_value_fields_numeric_does_not_dual_store() -> None:
    fact = FactRecord(
        concept_qname=_q("Assets"),
        context_locator=_loc("c1"),
        source_locator=_loc("f1"),
        value_status="valid",
        unit_locator=_loc("u1"),
        raw_lexical_value="100",
        resolved_numeric_value=Decimal("100"),
        resolved_value_kind="numeric",
    )
    assert _resolved_value_fields(fact) == ("numeric", None, Decimal("100"))


def test_resolved_value_fields_rejects_kind_none_with_numeric() -> None:
    fact = FactRecord(
        concept_qname=_q("Assets"),
        context_locator=_loc("c1"),
        source_locator=_loc("f1"),
        value_status="valid",
        unit_locator=_loc("u1"),
        raw_lexical_value="100",
        resolved_numeric_value=Decimal("100"),
        resolved_value_kind=None,
    )
    with pytest.raises(SemanticProjectionConflict):
        _resolved_value_fields(fact)
