"""Fail-closed parsing of numeric fields in P2 JSON reports."""

from __future__ import annotations


class ReportFieldError(ValueError):
    """A report field has an unexpected shape or value."""


def parse_report_float(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise ReportFieldError(f"{field}: boolean is not a number")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ReportFieldError(f"{field}: empty string")
        try:
            return float(text)
        except ValueError as exc:
            raise ReportFieldError(f"{field}: not a float: {value!r}") from exc
    raise ReportFieldError(f"{field}: expected number, got {type(value).__name__}")


def parse_report_int(value: object, *, field: str) -> int:
    if isinstance(value, bool):
        raise ReportFieldError(f"{field}: boolean is not a number")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            raise ReportFieldError(f"{field}: non-integral float {value}")
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ReportFieldError(f"{field}: empty string")
        try:
            return int(text)
        except ValueError as exc:
            raise ReportFieldError(f"{field}: not an int: {value!r}") from exc
    raise ReportFieldError(f"{field}: expected int, got {type(value).__name__}")


def optional_report_float(row: dict[str, object], field: str) -> float | None:
    if field not in row or row[field] is None:
        return None
    return parse_report_float(row[field], field=field)


def optional_report_int(row: dict[str, object], field: str) -> int | None:
    if field not in row or row[field] is None:
        return None
    return parse_report_int(row[field], field=field)


def parse_report_int_field(
    payload: dict[str, object],
    field: str,
    *,
    fallback_field: str | None = None,
) -> int:
    if field in payload and payload[field] is not None:
        return parse_report_int(payload[field], field=field)
    if (
        fallback_field is not None
        and fallback_field in payload
        and payload[fallback_field] is not None
    ):
        return parse_report_int(payload[fallback_field], field=fallback_field)
    return 0
