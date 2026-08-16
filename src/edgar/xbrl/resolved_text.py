"""Deterministic resolved-text encoders for Arelle runtime value families (v2).

These serialize Arelle *resolved runtime state* into ``resolved_text_value``
with ``resolved_value_kind="text"``. They must never reuse filed lexical forms
(``raw_lexical_value`` / Arelle ``sourceValue``).

Invariant: the same represented Arelle runtime state serializes identically,
and every semantically relevant field of the supported object is preserved.
``resolved_text_value`` is not a canonical XSD value-space equality key.
"""

from __future__ import annotations

import json
from datetime import tzinfo
from decimal import Decimal
from typing import Any


def _tz_suffix(tz: tzinfo | None) -> str:
    """Serialize timezone offset from ``utcoffset``; empty when absent."""
    if tz is None:
        return ""
    offset = tz.utcoffset(None)
    if offset is None:
        return ""
    total = int(offset.total_seconds())
    if total == 0:
        return "Z"
    sign = "+" if total > 0 else "-"
    total = abs(total)
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def encode_g_year(value: Any) -> str:
    """Encode Arelle ``gYear`` from ``year`` + ``tzinfo`` fields."""
    year = int(value.year)
    width = 5 if year < 0 else 4
    return f"{year:0{width}d}{_tz_suffix(value.tzinfo)}"


def encode_g_month_day(value: Any) -> str:
    """Encode Arelle ``gMonthDay`` from ``month`` + ``day`` + ``tzinfo``."""
    return f"--{int(value.month):02d}-{int(value.day):02d}{_tz_suffix(value.tzinfo)}"


def encode_iso_duration(value: Any) -> str:
    """Encode Arelle ``IsoDuration`` as compact structural JSON.

    Never uses ``str(value)`` / ``sourceValue``. Years and months are exact
    Decimal strings (never float). Timedelta components are integers.
    """
    years = value.years if isinstance(value.years, Decimal) else Decimal(str(value.years))
    months = value.months if isinstance(value.months, Decimal) else Decimal(str(value.months))
    tdelta = value.tdelta
    payload = {
        "days": int(tdelta.days),
        "microseconds": int(tdelta.microseconds),
        "months": format(months, "f"),
        "seconds": int(tdelta.seconds),
        "years": format(years, "f"),
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _clark_qname(value: Any) -> str | None:
    namespace_uri = getattr(value, "namespaceURI", None)
    local_name = getattr(value, "localName", None)
    if not isinstance(local_name, str) or not local_name:
        return None
    if namespace_uri is None:
        return f"{{}}{local_name}"
    if not isinstance(namespace_uri, str):
        return None
    return f"{{{namespace_uri}}}{local_name}"


def encode_list(value: Any) -> str | None:
    """Encode an ordered list as compact JSON; fail closed on unsupported members.

    Supported members: Arelle/XML QNames (Clark notation). ``None`` and any
    other runtime type return ``None`` (caller emits UNSUPPORTED_RESOLVED_VALUE).
    """
    if not isinstance(value, list):
        return None
    encoded: list[str] = []
    for member in value:
        if member is None:
            return None
        clark = _clark_qname(member)
        if clark is None:
            return None
        encoded.append(clark)
    return json.dumps(
        encoded,
        sort_keys=False,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def encode_supported_resolved(value: Any) -> tuple[str | None, bool]:
    """Return ``(text, supported)`` for known Arelle runtime families."""
    type_name = type(value).__name__
    module = type(value).__module__
    if module != "arelle.ModelValue":
        if isinstance(value, list):
            text = encode_list(value)
            return (text, text is not None)
        return None, False
    if type_name == "gYear":
        return encode_g_year(value), True
    if type_name == "gMonthDay":
        return encode_g_month_day(value), True
    if type_name == "IsoDuration":
        return encode_iso_duration(value), True
    return None, False
