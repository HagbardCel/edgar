"""SIC → P2 industry bucket mapping."""

from __future__ import annotations

from edgar.spike.sic_industry import industry_bucket_from_sic


def test_retail_and_energy_from_known_sics() -> None:
    assert industry_bucket_from_sic("5961") == "retail"
    assert industry_bucket_from_sic("2911") == "energy"


def test_amazon_retail_not_energy() -> None:
    assert industry_bucket_from_sic("5961") == "retail"
