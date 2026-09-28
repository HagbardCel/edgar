"""Git decision records and QName expansion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edgar.domain.concept_id import clark_qname
from edgar.domain.identifiers import validate_cik
from edgar.registry.hashing import definition_hash
from edgar.registry.loader import load_canonical_registry
from edgar.registry.models import CanonicalMetric
from edgar.xbrl.taxonomy_family import classify

DecisionFamily = Literal["us-gaap", "dei", "srt", "issuer"]
DecisionRelation = Literal["exact", "narrower", "broader", "related"]
DecisionStatus = Literal["accepted", "rejected"]
DecisionMethod = Literal["curated", "reviewed"]


class DecisionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    source: str | None = None
    artifact_sha256: str | None = None
    concept: str | None = None
    accession: str | None = None
    locator: str | None = None
    quote: str | None = None


class DecisionReviewed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: str
    on: date


class DecisionSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: DecisionFamily
    local_name: str
    issuer_cik: str | None = None
    exclude_qnames: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _issuer_cik_required(self) -> DecisionSource:
        if self.family == "issuer" and not self.issuer_cik:
            raise ValueError("issuer family decisions require source.issuer_cik")
        if self.issuer_cik is not None:
            validate_cik(self.issuer_cik)
        return self


class DecisionScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exclude_ciks: tuple[str, ...] = ()
    exclude_sic_divisions: tuple[str, ...] = ()


class DecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    metric: str
    source: DecisionSource
    relation: DecisionRelation
    scope: DecisionScope = Field(default_factory=DecisionScope)
    status: DecisionStatus
    method: DecisionMethod
    rationale: str
    evidence: tuple[DecisionEvidence, ...]
    reviewed: DecisionReviewed
    contract_hash: str

    @field_validator("rationale")
    @classmethod
    def _rationale_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must be non-empty")
        return value

    @model_validator(mode="after")
    def _evidence_when_operational(self) -> DecisionRecord:
        if self.status in ("accepted", "rejected") and not self.evidence:
            raise ValueError(f"{self.id}: operational decisions require evidence")
        substantive = False
        for ev in self.evidence:
            if ev.accession and ev.locator:
                substantive = True
                break
            if ev.concept and (ev.quote or ev.artifact_sha256):
                substantive = True
                break
            if ev.kind in ("filing_fact", "taxonomy", "metalinks"):
                substantive = True
                break
        if self.status in ("accepted", "rejected") and not substantive:
            raise ValueError(
                f"{self.id}: evidence must point at filing or taxonomy facts, not metric defs alone"
            )
        return self


@dataclass(frozen=True)
class LoadedDecision:
    record: DecisionRecord
    path: Path
    stale_inactive: bool = False


@dataclass(frozen=True)
class DecisionRegistry:
    decisions: tuple[LoadedDecision, ...]
    metrics_by_key: dict[str, CanonicalMetric]

    def by_id(self) -> dict[str, LoadedDecision]:
        return {d.record.id: d for d in self.decisions}


class StaleAcceptedDecisionError(ValueError):
    """Accepted decision contract_hash does not match current metric definition."""


def _decision_key(record: DecisionRecord) -> tuple[str, str, str, str]:
    issuer = record.source.issuer_cik or ""
    return (record.metric, record.source.family, issuer, record.source.local_name)


def _issuer_namespace_matches_cik(namespace_uri: str, issuer_cik: str) -> bool:
    cik = validate_cik(issuer_cik)
    dashless = cik.lstrip("0") or "0"
    return cik in namespace_uri or dashless in namespace_uri


def concept_matches_decision(
    record: DecisionRecord,
    filing_cik: str,
    namespace_uri: str,
    local_name: str,
) -> bool:
    if record.source.local_name != local_name:
        return False
    qname = clark_qname(namespace_uri, local_name)
    if qname in record.source.exclude_qnames:
        return False
    clf = classify(namespace_uri)
    family = record.source.family
    if family in ("us-gaap", "dei", "srt"):
        return clf.semantic_family == family
    if family == "issuer":
        if record.source.issuer_cik is None:
            return False
        if validate_cik(record.source.issuer_cik) != validate_cik(filing_cik):
            return False
        return clf.origin == "issuer" and _issuer_namespace_matches_cik(
            namespace_uri, record.source.issuer_cik
        )
    return False


def issuer_excluded(record: DecisionRecord, filing_cik: str) -> bool:
    normalized = validate_cik(filing_cik)
    return any(validate_cik(c) == normalized for c in record.scope.exclude_ciks)


def decision_applies_to_filing(record: DecisionRecord, filing_cik: str) -> bool:
    if issuer_excluded(record, filing_cik):
        return False
    if record.source.family == "issuer":
        assert record.source.issuer_cik is not None
        return validate_cik(record.source.issuer_cik) == validate_cik(filing_cik)
    return True


def load_decisions(
    registry_dir: Path,
    *,
    metrics: dict[str, CanonicalMetric] | None = None,
    fatal_stale_accepted: bool = True,
) -> DecisionRegistry:
    if metrics is None:
        loaded = load_canonical_registry(registry_dir)
        metrics = {m.key: m for m in loaded.metrics}
    decisions_dir = registry_dir / "decisions"
    loaded_decisions: list[LoadedDecision] = []
    if decisions_dir.is_dir():
        for path in sorted(decisions_dir.rglob("*.yml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            record = DecisionRecord.model_validate(raw)
            if record.metric not in metrics:
                raise ValueError(f"unknown metric {record.metric!r} in {path}")
            current_hash = definition_hash(metrics[record.metric])
            stale = record.contract_hash != current_hash
            if stale and record.status == "accepted" and fatal_stale_accepted:
                raise StaleAcceptedDecisionError(f"stale accepted decision {record.id} in {path}")
            loaded_decisions.append(LoadedDecision(record=record, path=path, stale_inactive=stale))
    keys_seen: set[tuple[str, str, str, str]] = set()
    for ld in loaded_decisions:
        if ld.stale_inactive:
            continue
        key = _decision_key(ld.record)
        if key in keys_seen:
            raise ValueError(f"duplicate decision key {key}")
        keys_seen.add(key)
    return DecisionRegistry(decisions=tuple(loaded_decisions), metrics_by_key=metrics)


def expand_clark_qnames_for_decision(
    record: DecisionRecord,
    filing_cik: str,
    namespace_uris: tuple[str, ...],
) -> frozenset[str]:
    result: set[str] = set()
    for ns in namespace_uris:
        if concept_matches_decision(record, filing_cik, ns, record.source.local_name):
            q = clark_qname(ns, record.source.local_name)
            if q not in record.source.exclude_qnames:
                result.add(q)
    return frozenset(result)
