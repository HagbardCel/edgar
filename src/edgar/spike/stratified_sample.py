"""Stratified 10-K accession selection for the P2 measurement list."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from edgar.spike.submissions_filings import SubmissionsFilingRow

FISCAL_YEAR_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("2010-2012", 2010, 2012),
    ("2013-2015", 2013, 2015),
    ("2016-2018", 2016, 2018),
    ("2019-2021", 2019, 2021),
    ("2022-2025", 2022, 2025),
)


@dataclass(frozen=True)
class IssuerSeed:
    cik: str
    industry_bucket: str
    size: str


@dataclass(frozen=True)
class SpikeFilingPick:
    accession: str
    cik: str
    form: str
    fiscal_year: int | None
    filing_date: date | None
    sic: str | None
    industry_bucket: str
    issuer_size: str


def fiscal_year_bucket(year: int | None) -> str | None:
    if year is None:
        return None
    for label, start, end in FISCAL_YEAR_BUCKETS:
        if start <= year <= end:
            return label
    return None


def _fiscal_year(row: SubmissionsFilingRow) -> int | None:
    if row.report_period_end is not None:
        return row.report_period_end.year
    if row.filing_date is not None:
        return row.filing_date.year
    return None


def _to_pick(row: SubmissionsFilingRow, seed: IssuerSeed) -> SpikeFilingPick:
    return SpikeFilingPick(
        accession=row.accession,
        cik=row.cik,
        form=row.form,
        fiscal_year=_fiscal_year(row),
        filing_date=row.filing_date,
        sic=row.sic,
        industry_bucket=seed.industry_bucket,
        issuer_size=seed.size,
    )


def select_stratified_filings(
    rows: Sequence[SubmissionsFilingRow],
    seeds: Mapping[str, IssuerSeed],
    *,
    target_min: int = 500,
    target_max: int = 1000,
    per_bucket_min: int = 20,
) -> tuple[SpikeFilingPick, ...]:
    """Greedy stratified sample across fiscal-year and industry buckets."""
    if target_min > target_max:
        raise ValueError("target_min cannot exceed target_max")
    candidates: list[SpikeFilingPick] = []
    for row in rows:
        seed = seeds.get(row.cik)
        if seed is None:
            continue
        candidates.append(_to_pick(row, seed))
    candidates.sort(
        key=lambda item: (item.cik, item.fiscal_year or 0, item.accession),
        reverse=True,
    )
    unique: list[SpikeFilingPick] = []
    seen: set[str] = set()
    for pick in candidates:
        if pick.accession in seen:
            continue
        seen.add(pick.accession)
        unique.append(pick)

    industries = sorted({pick.industry_bucket for pick in unique})
    bucket_counts: dict[tuple[str, str], int] = {
        (fy_label, industry): 0 for fy_label, _, _ in FISCAL_YEAR_BUCKETS for industry in industries
    }
    selected: list[SpikeFilingPick] = []
    selected_accessions: set[str] = set()

    def _add(pick: SpikeFilingPick) -> None:
        if pick.accession in selected_accessions or len(selected) >= target_max:
            return
        selected.append(pick)
        selected_accessions.add(pick.accession)
        label = fiscal_year_bucket(pick.fiscal_year)
        if label is not None:
            bucket_counts[(label, pick.industry_bucket)] += 1

    for fy_label, _, _ in FISCAL_YEAR_BUCKETS:
        for industry in industries:
            need = per_bucket_min - bucket_counts[(fy_label, industry)]
            while need > 0 and len(selected) < target_max:
                added = False
                for pick in unique:
                    if pick.accession in selected_accessions:
                        continue
                    if fiscal_year_bucket(pick.fiscal_year) != fy_label:
                        continue
                    if pick.industry_bucket != industry:
                        continue
                    _add(pick)
                    need -= 1
                    added = True
                    break
                if not added:
                    break

    for pick in unique:
        if len(selected) >= target_max:
            break
        _add(pick)

    if len(selected) < target_min:
        raise ValueError(
            f"stratified sample produced {len(selected)} filings; need at least {target_min}",
        )
    selected.sort(key=lambda item: item.accession)
    return tuple(selected)


def load_issuer_seeds(toml_rows: Iterable[Mapping[str, str]]) -> dict[str, IssuerSeed]:
    seeds: dict[str, IssuerSeed] = {}
    for row in toml_rows:
        cik = str(row["cik"]).strip()
        seeds[cik] = IssuerSeed(
            cik=cik,
            industry_bucket=str(row["industry_bucket"]).strip(),
            size=str(row.get("size") or "unknown").strip(),
        )
    return seeds


def write_spike_outputs(
    picks: Sequence[SpikeFilingPick],
    *,
    accessions_path: str,
    sample_csv_path: str,
) -> None:
    from pathlib import Path

    acc_path = Path(accessions_path)
    acc_path.write_text("".join(f"{pick.accession}\n" for pick in picks), encoding="utf-8")
    lines = [
        "accession,cik,form,fiscal_year,sic,industry_bucket,taxonomy_era_note",
    ]
    for pick in picks:
        fy = str(pick.fiscal_year) if pick.fiscal_year is not None else ""
        sic = pick.sic or ""
        lines.append(
            f"{pick.accession},{pick.cik},{pick.form},{fy},{sic},{pick.industry_bucket},",
        )
    Path(sample_csv_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
