"""Stratified 10-K accession selection for the P2 measurement list."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from edgar.spike.sic_industry import industry_bucket_from_sic
from edgar.spike.submissions_filings import SubmissionsFilingRow

PRIMARY_FORM = "10-K"
AMENDMENT_FORM = "10-K/A"

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
    size: str
    expected_name: str | None = None


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


@dataclass(frozen=True)
class SpikeSampleResult:
    """Primary 10-K corpus plus supplemental amendments (not counted toward target)."""

    primary: tuple[SpikeFilingPick, ...]
    amendments: tuple[SpikeFilingPick, ...]
    primary_stratum_counts: dict[tuple[str, str], int]
    amendment_count: int

    @property
    def all_picks(self) -> tuple[SpikeFilingPick, ...]:
        return self.primary + self.amendments


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


def is_primary_eligible(row: SubmissionsFilingRow) -> bool:
    if row.form != PRIMARY_FORM:
        return False
    return fiscal_year_bucket(_fiscal_year(row)) is not None


def is_amendment_eligible(row: SubmissionsFilingRow) -> bool:
    if row.form != AMENDMENT_FORM:
        return False
    return fiscal_year_bucket(_fiscal_year(row)) is not None


def _to_pick(row: SubmissionsFilingRow, seed: IssuerSeed) -> SpikeFilingPick:
    return SpikeFilingPick(
        accession=row.accession,
        cik=row.cik,
        form=row.form,
        fiscal_year=_fiscal_year(row),
        filing_date=row.filing_date,
        sic=row.sic,
        industry_bucket=industry_bucket_from_sic(row.sic),
        issuer_size=seed.size,
    )


def _dedupe_picks(candidates: Sequence[SpikeFilingPick]) -> tuple[SpikeFilingPick, ...]:
    unique: list[SpikeFilingPick] = []
    seen: set[str] = set()
    for pick in candidates:
        if pick.accession in seen:
            continue
        seen.add(pick.accession)
        unique.append(pick)
    return tuple(unique)


def _select_primary(
    unique_primary: Sequence[SpikeFilingPick],
    *,
    target_min: int,
    target_max: int,
    per_bucket_min: int,
) -> tuple[list[SpikeFilingPick], dict[tuple[str, str], int]]:
    industries = sorted({pick.industry_bucket for pick in unique_primary})
    bucket_counts: dict[tuple[str, str], int] = {
        (fy_label, industry): 0 for fy_label, _, _ in FISCAL_YEAR_BUCKETS for industry in industries
    }
    selected: list[SpikeFilingPick] = []
    selected_accessions: set[str] = set()

    def _add(pick: SpikeFilingPick) -> None:
        if pick.accession in selected_accessions or len(selected) >= target_max:
            return
        if pick.form != PRIMARY_FORM:
            return
        if fiscal_year_bucket(pick.fiscal_year) is None:
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
                for pick in unique_primary:
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

    for pick in unique_primary:
        if len(selected) >= target_max:
            break
        _add(pick)

    return selected, bucket_counts


def select_stratified_filings(
    rows: Sequence[SubmissionsFilingRow],
    seeds: Mapping[str, IssuerSeed],
    *,
    target_min: int = 500,
    target_max: int = 1000,
    per_bucket_min: int = 20,
    max_amendments: int = 100,
) -> SpikeSampleResult:
    """Build primary 10-K corpus (2010–2025) then add bounded 10-K/A amendments."""
    if target_min > target_max:
        raise ValueError("target_min cannot exceed target_max")
    primary_rows: list[SpikeFilingPick] = []
    amendment_rows: list[SpikeFilingPick] = []
    for row in rows:
        seed = seeds.get(row.cik)
        if seed is None:
            continue
        pick = _to_pick(row, seed)
        if is_primary_eligible(row):
            primary_rows.append(pick)
        elif is_amendment_eligible(row):
            amendment_rows.append(pick)

    primary_rows.sort(
        key=lambda item: (item.cik, item.fiscal_year or 0, item.accession),
        reverse=True,
    )
    amendment_rows.sort(
        key=lambda item: (item.cik, item.fiscal_year or 0, item.accession),
        reverse=True,
    )
    unique_primary = _dedupe_picks(primary_rows)
    unique_amendments = _dedupe_picks(amendment_rows)

    selected, bucket_counts = _select_primary(
        unique_primary,
        target_min=target_min,
        target_max=target_max,
        per_bucket_min=per_bucket_min,
    )
    if len(selected) < target_min:
        raise ValueError(
            f"primary 10-K sample has {len(selected)} filings; need at least {target_min}",
        )

    primary_accessions = {pick.accession for pick in selected}
    amendments: list[SpikeFilingPick] = []
    for pick in unique_amendments:
        if pick.accession in primary_accessions:
            continue
        if len(amendments) >= max_amendments:
            break
        amendments.append(pick)

    primary_tuple = tuple(sorted(selected, key=lambda item: item.accession))
    amendment_tuple = tuple(sorted(amendments, key=lambda item: item.accession))
    return SpikeSampleResult(
        primary=primary_tuple,
        amendments=amendment_tuple,
        primary_stratum_counts=dict(bucket_counts),
        amendment_count=len(amendment_tuple),
    )


def format_stratum_report(result: SpikeSampleResult) -> str:
    lines = [
        f"primary_10k={len(result.primary)} amendments_10ka={result.amendment_count}",
        "primary_strata (fiscal_year_bucket × industry_bucket):",
    ]
    for key in sorted(result.primary_stratum_counts):
        count = result.primary_stratum_counts[key]
        lines.append(f"  {key[0]} × {key[1]}: {count}")
    forms = Counter(pick.form for pick in result.all_picks)
    lines.append(f"forms_in_output: {dict(forms)}")
    return "\n".join(lines)


def load_issuer_seeds(toml_rows: Iterable[Mapping[str, str]]) -> dict[str, IssuerSeed]:
    seeds: dict[str, IssuerSeed] = {}
    for row in toml_rows:
        cik = str(row["cik"]).strip()
        expected = row.get("expected_name")
        name = str(expected).strip() if expected else None
        seeds[cik] = IssuerSeed(
            cik=cik,
            size=str(row.get("size") or "unknown").strip(),
            expected_name=name or None,
        )
    return seeds


def write_spike_outputs(
    result: SpikeSampleResult,
    *,
    accessions_path: str,
    sample_csv_path: str,
) -> None:
    from pathlib import Path

    picks = result.all_picks
    acc_path = Path(accessions_path)
    acc_path.write_text("".join(f"{pick.accession}\n" for pick in picks), encoding="utf-8")
    lines = [
        "accession,cik,form,fiscal_year,sic,industry_bucket,issuer_size,taxonomy_era_note",
    ]
    for pick in picks:
        fy = str(pick.fiscal_year) if pick.fiscal_year is not None else ""
        sic = pick.sic or ""
        lines.append(
            f"{pick.accession},{pick.cik},{pick.form},{fy},{sic},"
            f"{pick.industry_bucket},{pick.issuer_size},",
        )
    Path(sample_csv_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
