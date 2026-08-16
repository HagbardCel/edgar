"""Direct unit tests for arelle-semantic-v2 resolved-text encoders."""

from __future__ import annotations

import json
from datetime import UTC, timedelta, timezone
from decimal import Decimal

from arelle.ModelValue import IsoDuration, QName, gMonthDay, gYear

from edgar.xbrl.resolved_text import (
    encode_g_month_day,
    encode_g_year,
    encode_iso_duration,
    encode_list,
)


def test_encode_g_year_includes_timezone_and_negative_year() -> None:
    assert encode_g_year(gYear(2024, UTC)) == "2024Z"
    assert encode_g_year(gYear(2024, None)) == "2024"
    assert encode_g_year(gYear(-3, UTC)) == "-0003Z"
    assert encode_g_year(gYear(2024, timezone(timedelta(hours=-5)))) == "2024-05:00"


def test_encode_g_month_day_includes_timezone() -> None:
    assert encode_g_month_day(gMonthDay(1, 15, UTC)) == "--01-15Z"
    assert encode_g_month_day(gMonthDay(1, 15, None)) == "--01-15"
    assert (
        encode_g_month_day(gMonthDay(1, 2, timezone(timedelta(hours=5, minutes=30))))
        == "--01-02+05:30"
    )


def test_encode_iso_duration_structural_json_not_source_value() -> None:
    a = IsoDuration(
        years=Decimal("1"),
        months=Decimal("2"),
        days=3,
        seconds=14706,
        microseconds=500000,
        sourceValue="P1Y2M3DT4H5M6.5S",
    )
    b = IsoDuration(
        years=Decimal("1"),
        months=Decimal("2"),
        days=3,
        seconds=14706,
        microseconds=500000,
        sourceValue="COMPLETELY-DIFFERENT-LEXICAL",
    )
    expected = '{"days":3,"microseconds":500000,"months":"2","seconds":14706,"years":"1"}'
    assert encode_iso_duration(a) == expected
    assert encode_iso_duration(b) == expected
    assert encode_iso_duration(a) == encode_iso_duration(b)
    assert "COMPLETELY-DIFFERENT-LEXICAL" not in encode_iso_duration(b)
    assert str(a) == "P1Y2M3DT4H5M6.5S"  # Arelle still exposes source lexical via str()


def test_encode_iso_duration_never_float() -> None:
    text = encode_iso_duration(
        IsoDuration(years=Decimal("1.5"), months=Decimal("0"), sourceValue="ignored")
    )
    payload = json.loads(text)
    assert payload["years"] == "1.5"
    assert isinstance(payload["years"], str)
    assert isinstance(payload["months"], str)
    assert isinstance(payload["days"], int)


def test_encode_list_preserves_order_and_clark_qnames() -> None:
    q1 = QName("ex", "http://example.com", "First")
    q2 = QName("other", "http://example.com", "Second")
    assert encode_list([q1, q2]) == ('["{http://example.com}First","{http://example.com}Second"]')
    # Prefix must not affect output
    q2_alt = QName("zzz", "http://example.com", "Second")
    assert encode_list([q1, q2]) == encode_list([q1, q2_alt])
    assert encode_list([q2, q1]) != encode_list([q1, q2])


def test_encode_list_unsupported_member_fail_closed() -> None:
    q = QName("ex", "http://example.com", "Member")
    assert encode_list([q, None]) is None
    assert encode_list([q, "plain-string"]) is None
    assert encode_list([q, 1]) is None
