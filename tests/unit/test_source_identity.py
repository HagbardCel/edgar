"""Unit tests for Phase 2B concept and report identity contracts."""

from __future__ import annotations

from edgar.domain.bundle import InstanceReportInput, IxdsReportInput
from edgar.domain.concept_id import (
    EDGAR_CONCEPT_NAMESPACE_UUID,
    clark_qname,
    concept_id,
)
from edgar.domain.report_key import (
    canonical_report_input_bytes,
    report_input_payload,
    report_key,
)

# Frozen compatibility fixtures — do not regenerate casually.
_FROZEN_CASH_CONCEPT_ID = "f0415219-e4b2-51c0-a00c-9f2d03423233"
_FROZEN_INSTANCE_REPORT_KEY = "d8f9331677b35bc461d25b057a8e6785d1cea8face0bc68cc3b8f9fce72820ff"
_FROZEN_IXDS_REPORT_KEY = "403d0aac2b03d79627614241699109947e19dd442092c5f0dd96e15286e48f39"


def test_clark_qname_encoding() -> None:
    assert (
        clark_qname("http://fasb.org/us-gaap/2023", "CashAndCashEquivalentsAtCarryingValue")
        == "{http://fasb.org/us-gaap/2023}CashAndCashEquivalentsAtCarryingValue"
    )


def test_concept_id_rejects_ambiguous_concatenation() -> None:
    """``ab``+``c`` and ``a``+``bc`` must not collide under Clark encoding."""
    left = concept_id("ab", "c")
    right = concept_id("a", "bc")
    assert left != right


def test_frozen_cash_concept_uuid() -> None:
    cid = concept_id(
        "http://fasb.org/us-gaap/2023",
        "CashAndCashEquivalentsAtCarryingValue",
    )
    assert str(cid) == _FROZEN_CASH_CONCEPT_ID
    assert cid.version == 5
    assert EDGAR_CONCEPT_NAMESPACE_UUID.version == 4


def test_concept_id_deterministic() -> None:
    a = concept_id("http://example.com/ns", "Foo")
    b = concept_id("http://example.com/ns", "Foo")
    assert a == b


def test_instance_report_key_frozen() -> None:
    inst = InstanceReportInput(
        document_uris=(
            "https://www.sec.gov/Archives/edgar/data/1065088/000106508824000036/ebay-20231231.htm",
        )
    )
    assert report_key(inst) == _FROZEN_INSTANCE_REPORT_KEY
    expected_bytes = (
        b'{"document_uris":["https://www.sec.gov/Archives/edgar/data/1065088/'
        b'000106508824000036/ebay-20231231.htm"],"kind":"instance"}'
    )
    assert canonical_report_input_bytes(inst) == expected_bytes


def test_ixds_report_key_preserves_uri_order() -> None:
    ixds = IxdsReportInput(document_uris=("https://a.example/x.htm", "https://a.example/y.htm"))
    assert report_key(ixds) == _FROZEN_IXDS_REPORT_KEY
    reversed_ixds = IxdsReportInput(
        document_uris=("https://a.example/y.htm", "https://a.example/x.htm")
    )
    assert report_key(reversed_ixds) != report_key(ixds)


def test_report_input_payload_from_mapping() -> None:
    payload = report_input_payload(
        {"kind": "instance", "document_uris": ["https://example.com/a.htm"]}
    )
    assert payload == {"kind": "instance", "document_uris": ["https://example.com/a.htm"]}
