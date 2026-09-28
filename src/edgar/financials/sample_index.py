"""Join metadata for the frozen spike sample. Not an accession list."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

_COLUMNS = (
    "accession",
    "cik",
    "form",
    "fiscal_year",
    "sic",
    "industry_bucket",
    "taxonomy_era_note",
)


@dataclass(frozen=True)
class SampleRow:
    accession: str
    cik: str
    form: str
    fiscal_year: str
    sic: str
    industry_bucket: str
    taxonomy_era_note: str


def load_sample_csv(path: Path) -> dict[str, SampleRow]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"sample csv has no header: {path}")
        missing = [name for name in _COLUMNS if name not in reader.fieldnames]
        if missing:
            raise ValueError(f"sample csv missing columns {missing}: {path}")
        rows: dict[str, SampleRow] = {}
        for raw in reader:
            accession = (raw.get("accession") or "").strip()
            if not accession:
                raise ValueError("sample csv row missing accession")
            if accession in rows:
                raise ValueError(f"duplicate sample accession {accession}")
            industry = (raw.get("industry_bucket") or "").strip() or "unknown"
            rows[accession] = SampleRow(
                accession=accession,
                cik=(raw.get("cik") or "").strip(),
                form=(raw.get("form") or "").strip(),
                fiscal_year=(raw.get("fiscal_year") or "").strip(),
                sic=(raw.get("sic") or "").strip(),
                industry_bucket=industry,
                taxonomy_era_note=(raw.get("taxonomy_era_note") or "").strip(),
            )
    return rows
