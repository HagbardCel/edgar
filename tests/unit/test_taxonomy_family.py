"""Unit tests for taxonomy namespace family classification."""

from __future__ import annotations

from edgar.xbrl.taxonomy_family import classify


def test_us_gaap_families() -> None:
    assert classify("http://xbrl.us/us-gaap/2009-01-31").semantic_family == "us-gaap"
    assert classify("http://fasb.org/us-gaap/2023").semantic_family == "us-gaap"
    assert classify("http://xbrl.us/us-gaap/2009-01-31").origin == "standard"
    assert classify("http://fasb.org/us-gaap/2023").origin == "standard"


def test_srt_family() -> None:
    http = classify("http://fasb.org/srt/2024")
    assert http.semantic_family == "srt"
    assert http.origin == "standard"
    https = classify("https://fasb.org/srt/2024")
    assert https.semantic_family == "srt"
    assert https.origin == "standard"


def test_dei_families() -> None:
    assert classify("http://xbrl.us/dei/2009-01-31").semantic_family == "dei"
    assert classify("http://xbrl.sec.gov/dei/2023").semantic_family == "dei"


def test_other_standard_hosts() -> None:
    country = classify("http://xbrl.sec.gov/country/2023")
    assert country.semantic_family == "other"
    assert country.origin == "standard"
    cyd = classify("http://xbrl.sec.gov/cyd/2026")
    assert cyd.semantic_family == "other"
    assert cyd.origin == "standard"
    sic = classify("http://xbrl.us/sic/2009-01-31")
    assert sic.semantic_family == "other"
    assert sic.origin == "standard"


def test_issuer_extension() -> None:
    ebay = classify("http://ebay.com/20131231")
    assert ebay.semantic_family == "other"
    assert ebay.origin == "issuer"


def test_missing_namespace_is_issuer() -> None:
    result = classify(None)
    assert result.semantic_family == "other"
    assert result.origin == "issuer"
