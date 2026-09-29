"""Orchestrate edgar build."""

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import Engine

from edgar.corpus_manifest import load_corpus_manifest
from edgar.financials.cohort import load_m0_cohort
from edgar.financials.decisions import load_decisions
from edgar.financials.gold import GoldFile, load_gold
from edgar.financials.models import Observation
from edgar.financials.period import MetricPeriodType, resolve_required_reporting_period
from edgar.financials.resolve import resolve_supports
from edgar.financials.select import ANNUAL_FORMS, select_metric
from edgar.financials.source_load import load_filing, load_filing_metadata
from edgar.financials.validate import check_gold_assertions, run_identity_checks
from edgar.xbrl.source_records import EXTRACTOR_VERSION


@dataclass(frozen=True)
class BuildResult:
    observations: tuple[Observation, ...]
    findings: tuple[dict[str, str], ...]
    manifest: dict[str, object]
    gold_assertions_checked: int
    gold_errors: tuple[str, ...]


def default_accessions(repo_root: Path) -> tuple[str, ...]:
    manifest = load_corpus_manifest(repo_root / "fixtures" / "corpus.toml")
    return tuple(f.accession for f in manifest.filings)


def resolve_build_accessions(
    repo_root: Path,
    *,
    accession: Sequence[str] | None,
    accessions_file: Path | None,
) -> tuple[str, ...]:
    """Resolve build population from corpus default, CLI accessions, or a file."""
    from edgar.ingestion.accession_file import parse_accession_file

    if accession and accessions_file is not None:
        raise ValueError("pass at most one of --accession and --accessions-file")
    if accessions_file is not None:
        return parse_accession_file(accessions_file)
    if accession:
        return tuple(accession)
    return default_accessions(repo_root)


def run_build(
    engine: Engine,
    registry_dir: Path,
    repo_root: Path,
    accessions: tuple[str, ...],
    *,
    check_gold: bool = False,
) -> BuildResult:
    cohort = load_m0_cohort(registry_dir)
    registry = load_decisions(registry_dir, fatal_stale_accepted=True)
    gold_file: GoldFile | None = None
    if check_gold:
        gold_path = registry_dir / "gold" / "m0-annual.yml"
        if not gold_path.is_file():
            raise ValueError(f"gold file missing for --check-gold: {gold_path}")
        gold_file = load_gold(gold_path)

    observations: list[Observation] = []
    findings: list[dict[str, str]] = []

    with engine.connect() as conn:
        for accession in accessions:
            meta = load_filing_metadata(conn, accession)
            if meta is None:
                raise ValueError(f"accession not in source.*: {accession}")
            if meta.form not in ANNUAL_FORMS:
                for metric in cohort.metrics:
                    period_type: MetricPeriodType = registry.metrics_by_key[metric].period_type
                    observations.append(
                        select_metric(
                            metric,
                            meta.form,
                            meta.cik,
                            accession,
                            None,
                            (),
                            (),
                            registry,
                            meta.accepted_at,
                            metric_period_type=period_type,
                        )
                    )
                continue
            loaded = load_filing(conn, accession)
            assert loaded is not None
            supports = resolve_supports(loaded.facts, registry, accession, loaded.cik)
            period = resolve_required_reporting_period(
                loaded.dei_candidates, loaded.cik, loaded.facts
            )
            for finding in run_identity_checks(accession, loaded.cik, period, loaded.facts):
                findings.append(
                    {
                        "accession": finding.accession,
                        "name": finding.name,
                        "status": finding.status,
                        "detail": finding.detail or "",
                    }
                )
            for metric in cohort.metrics:
                period_type = registry.metrics_by_key[metric].period_type
                obs = select_metric(
                    metric,
                    loaded.form,
                    loaded.cik,
                    accession,
                    period,
                    loaded.facts,
                    supports,
                    registry,
                    loaded.accepted_at,
                    metric_period_type=period_type,
                )
                observations.append(obs)

    obs_tuple = tuple(observations)
    gold_checked = 0
    gold_errors: list[str] = []
    if check_gold:
        assert gold_file is not None
        gold_checked, gold_errors = check_gold_assertions(
            gold_file.assertions,
            obs_tuple,
            frozenset(accessions),
        )
        if gold_errors:
            raise ValueError("gold check failed: " + "; ".join(gold_errors))

    manifest = _build_manifest(registry_dir, repo_root, accessions)
    return BuildResult(
        observations=obs_tuple,
        findings=tuple(findings),
        manifest=manifest,
        gold_assertions_checked=gold_checked,
        gold_errors=tuple(gold_errors),
    )


def write_build_output(
    result: BuildResult,
    output_dir: Path,
    cohort_metrics: tuple[str, ...],
    accession_order: tuple[str, ...],
) -> None:
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".edgar-build-", dir=parent) as tmp:
        tmp_path = Path(tmp)
        _write_observations_csv(
            tmp_path / "observations.csv",
            result.observations,
            cohort_metrics,
            accession_order,
        )
        _write_observations_json(tmp_path / "observations.json", result.observations)
        (tmp_path / "findings.json").write_text(
            json.dumps(list(result.findings), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (tmp_path / "manifest.json").write_text(
            json.dumps(result.manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.rename(output_dir)


def _write_observations_json(path: Path, observations: tuple[Observation, ...]) -> None:
    rows = [_observation_dict(o) for o in observations]
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


def _observation_dict(obs: Observation) -> dict[str, object]:
    return {
        "cik": obs.cik,
        "accession": obs.accession,
        "metric": obs.metric,
        "fy": obs.fy,
        "report_focus": obs.report_focus,
        "period_role": obs.period_role,
        "period_start": obs.period_start,
        "period_end": obs.period_end,
        "status": obs.status,
        "reason": obs.reason,
        "numeric": str(obs.numeric) if obs.numeric is not None else None,
        "decimals": obs.decimals,
        "unit": obs.unit,
        "decision_ids": list(obs.decision_ids),
        "fact_ids": list(obs.fact_ids),
        "supports": [
            {
                "fact_id": s.fact_id,
                "decision_id": s.decision_id,
                "relation": s.relation,
                "tier": s.tier,
                "source_qname": s.source_qname,
                "application_method": s.application_method,
            }
            for s in obs.supports
        ],
        "relation": obs.relation,
        "tier": obs.tier,
        "available_at": obs.available_at,
        "view": obs.view,
    }


def _write_observations_csv(
    path: Path,
    observations: tuple[Observation, ...],
    cohort_metrics: tuple[str, ...],
    accession_order: tuple[str, ...],
) -> None:
    acc_order = {a: i for i, a in enumerate(accession_order)}
    metric_order = {m: i for i, m in enumerate(cohort_metrics)}
    sorted_obs = sorted(
        observations,
        key=lambda o: (acc_order.get(o.accession, 0), metric_order.get(o.metric, 0)),
    )
    fieldnames = [
        "cik",
        "accession",
        "metric",
        "period_start",
        "period_end",
        "status",
        "reason",
        "numeric",
        "decimals",
        "unit",
        "decision_ids",
        "fact_ids",
        "available_at",
        "view",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for obs in sorted_obs:
            writer.writerow(
                {
                    "cik": obs.cik,
                    "accession": obs.accession,
                    "metric": obs.metric,
                    "period_start": obs.period_start or "",
                    "period_end": obs.period_end or "",
                    "status": obs.status,
                    "reason": obs.reason or "",
                    "numeric": str(obs.numeric) if obs.numeric is not None else "",
                    "decimals": obs.decimals or "",
                    "unit": obs.unit or "",
                    "decision_ids": json.dumps(list(obs.decision_ids)),
                    "fact_ids": json.dumps(list(obs.fact_ids)),
                    "available_at": obs.available_at or "",
                    "view": obs.view,
                }
            )


def _build_manifest(
    registry_dir: Path,
    repo_root: Path,
    accessions: tuple[str, ...],
) -> dict[str, object]:
    commit, dirty = _git_state(repo_root)
    decision_hashes: dict[str, str] = {}
    decisions_dir = registry_dir / "decisions"
    if decisions_dir.is_dir():
        for path in sorted(decisions_dir.rglob("*.yml")):
            import hashlib

            rel = path.relative_to(registry_dir).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            decision_hashes[rel] = digest
    return {
        "git_commit": commit,
        "git_dirty": dirty,
        "extractor_version": EXTRACTOR_VERSION,
        "accessions": list(accessions),
        "decision_file_hashes": decision_hashes,
        "built_at": datetime.now(UTC).isoformat(),
    }


def _git_state(repo_root: Path) -> tuple[str | None, bool]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        dirty = bool(status.strip())
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, False
