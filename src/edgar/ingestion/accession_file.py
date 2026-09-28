"""Accession list parser for batch extract.

One canonical dashed accession per line. Metadata belongs in a separate file.
"""

from __future__ import annotations

from pathlib import Path

from edgar.domain.identifiers import validate_accession


class AccessionFileError(ValueError):
    """The accession list is empty or contains a line that is not one accession."""


def parse_accession_file(path: Path) -> tuple[str, ...]:
    return parse_accession_lines(path.read_text(encoding="utf-8"))


def parse_accession_lines(text: str) -> tuple[str, ...]:
    if text == "":
        raise AccessionFileError("accession file is empty")
    lines = text.splitlines()
    if not lines:
        raise AccessionFileError("accession file is empty")
    accessions: list[str] = []
    seen: set[str] = set()
    for index, line in enumerate(lines, start=1):
        if line.strip() == "":
            raise AccessionFileError(f"line {index}: blank line")
        if line.lstrip().startswith("#"):
            raise AccessionFileError(f"line {index}: comments are not allowed")
        try:
            accession = validate_accession(line)
        except ValueError as exc:
            raise AccessionFileError(f"line {index}: malformed accession") from exc
        if accession in seen:
            raise AccessionFileError(f"line {index}: duplicate accession {accession}")
        seen.add(accession)
        accessions.append(accession)
    return tuple(accessions)
