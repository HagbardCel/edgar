"""CIK/accession validation and SEC archive URL construction."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
CIK_DIGITS_RE = re.compile(r"^\d{1,10}$")

SUPPORTED_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A"})


def validate_uuid4_hex(name: str) -> str:
    """Validate a lowercase UUID4 hex string (no hyphens); return it unchanged."""
    if not isinstance(name, str):
        raise ValueError(f"uuid4 hex must be a string, got {type(name).__name__}")
    if len(name) != 32 or any(c not in "0123456789abcdef" for c in name):
        raise ValueError(f"uuid4 hex must be 32 lowercase hex chars: {name!r}")
    try:
        value = uuid.UUID(hex=name)
    except ValueError as exc:
        raise ValueError(f"invalid uuid4 hex: {name!r}") from exc
    if value.version != 4:
        raise ValueError(f"uuid must be version 4: {name!r}")
    return name


def validate_cik(cik: str) -> str:
    """Validate and normalize a CIK to a zero-padded ten-digit string."""
    if not isinstance(cik, str):
        raise ValueError(f"CIK must be a string, got {type(cik).__name__}")
    cleaned = cik.strip()
    if cleaned != cik or not cleaned:
        raise ValueError(f"CIK rejected (whitespace or empty): {cik!r}")
    if any(ch in cleaned for ch in "/\\."):
        raise ValueError(f"CIK rejected (path characters): {cik!r}")
    if cleaned.startswith(("+", "-")):
        raise ValueError(f"CIK rejected (signed): {cik!r}")
    if not CIK_DIGITS_RE.fullmatch(cleaned):
        raise ValueError(f"CIK must be 1-10 decimal digits: {cik!r}")
    return f"{int(cleaned):010d}"


def validate_accession(accession: str) -> str:
    """Validate accession in canonical dashed form."""
    if not isinstance(accession, str):
        raise ValueError(f"accession must be a string, got {type(accession).__name__}")
    cleaned = accession.strip()
    if cleaned != accession:
        raise ValueError(f"accession rejected (surrounding whitespace): {accession!r}")
    if not ACCESSION_RE.fullmatch(cleaned):
        raise ValueError(f"accession must match ^\\d{{10}}-\\d{{2}}-\\d{{6}}$: {accession!r}")
    return cleaned


def accession_to_cik(accession: str) -> str:
    """Derive the zero-padded CIK from a canonical dashed accession."""
    acc = validate_accession(accession)
    return acc.split("-", 1)[0]


def assert_cik_accession_consistent(cik: str, accession: str) -> None:
    """Fail when the accession prefix does not match the normalized CIK."""
    cik_n = validate_cik(cik)
    acc = validate_accession(accession)
    prefix = acc.split("-", 1)[0]
    if prefix != cik_n:
        raise ValueError(f"accession CIK prefix {prefix} does not match normalized CIK {cik_n}")


def cik_int(cik: str) -> int:
    return int(validate_cik(cik))


def accession_dashless(accession: str) -> str:
    return validate_accession(accession).replace("-", "")


def accession_archive_base(cik: str, accession: str) -> str:
    assert_cik_accession_consistent(cik, accession)
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik_int(cik)}/{accession_dashless(accession)}/"
    )


def submissions_url(cik: str) -> str:
    return f"https://data.sec.gov/submissions/CIK{validate_cik(cik)}.json"


def sanitize_basename(name: str) -> str:
    cleaned = name.replace("\\", "/").split("/")[-1].strip()
    if not cleaned or cleaned in {".", ".."}:
        return "unnamed"
    out: list[str] = []
    for ch in cleaned:
        if ch.isalnum() or ch in {".", "-", "_"}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:180] or "unnamed"


def validate_logical_path(logical_path: str) -> str:
    if logical_path.startswith("/") or logical_path.startswith("\\"):
        raise ValueError(f"absolute logical path rejected: {logical_path}")
    parts = logical_path.split("/")
    if any(p in {"", ".", ".."} for p in parts):
        raise ValueError(f"unsafe logical path rejected: {logical_path}")
    return logical_path


def assert_path_under(path: Path, root: Path) -> Path:
    """Resolve path and assert it is a strict descendant of root."""
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"path {resolved} escapes root {root_resolved}") from exc
    if resolved == root_resolved:
        raise ValueError(f"path {resolved} is not a strict descendant of {root_resolved}")
    return resolved
