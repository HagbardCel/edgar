"""Unit tests for mapping assertion Pydantic contracts."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from edgar.registry.mapping import (
    MappingAssertionCreate,
    MappingEvidenceItem,
    parse_clark_qname,
)


def _create(**overrides: object) -> MappingAssertionCreate:
    payload: dict[str, object] = {
        "concept": "{http://example.com/ns}NetSales",
        "target_metric_key": "revenue",
        "relation": "exact",
        "scope_kind": "global",
        "method": "curated",
        "created_by": "human:test",
    }
    payload.update(overrides)
    return MappingAssertionCreate.model_validate(payload)


def test_parse_clark_qname_requires_namespace() -> None:
    ns, local = parse_clark_qname("{http://example.com/ns}NetSales")
    assert ns == "http://example.com/ns"
    assert local == "NetSales"
    with pytest.raises(ValueError, match="expanded QName"):
        parse_clark_qname("NetSales")
    with pytest.raises(ValueError, match="expanded QName"):
        parse_clark_qname("us-gaap:NetSales")


def test_global_scope_rejects_issuer() -> None:
    with pytest.raises(ValidationError, match="issuer_cik"):
        _create(scope_kind="global", issuer_cik="0000123456")


def test_issuer_scope_requires_issuer() -> None:
    with pytest.raises(ValidationError, match="issuer_cik"):
        _create(scope_kind="issuer")
    created = _create(scope_kind="issuer", issuer_cik="0000123456")
    assert created.issuer_cik == "0000123456"


def test_valid_from_after_valid_to_rejected() -> None:
    with pytest.raises(ValidationError, match="valid_from"):
        _create(valid_from=date(2021, 1, 1), valid_to=date(2020, 1, 1))


def test_evidence_forbids_fact_ids() -> None:
    with pytest.raises(ValidationError, match="source fact ids"):
        MappingEvidenceItem.model_validate(
            {"kind": "label", "data": {"fact_id": 12}, "summary": "label"}
        )


def test_unknown_relation_rejected() -> None:
    with pytest.raises(ValidationError):
        _create(relation="equivalent")
