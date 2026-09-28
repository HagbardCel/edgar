"""SEC companyfacts oracle. A differ does not change an observation.

Numbers are parsed as ``Decimal`` from the JSON token. The lookup identity is
CIK, taxonomy family, local name, accession, period, and unit. Identical
matching points collapse to one hit. Distinct values are ambiguous.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from edgar.domain.identifiers import validate_accession, validate_cik
from edgar.financials.models import FactRow, Observation
from edgar.financials.select import _is_pure_usd
from edgar.xbrl.taxonomy_family import classify

OracleResult = "OracleHit | OracleAbsent | OracleAmbiguous"
ORACLE_LABELS = frozenset({"agree", "differ", "absent", "ambiguous", "na"})
_STANDARD_FAMILIES = frozenset({"us-gaap", "dei", "srt"})


class OracleInputError(ValueError):
    """The companyfacts payload cannot be compared without losing fidelity."""


@dataclass(frozen=True)
class OracleHit:
    value: Decimal


@dataclass(frozen=True)
class OracleAbsent:
    pass


@dataclass(frozen=True)
class OracleAmbiguous:
    values: tuple[Decimal, ...]


@dataclass(frozen=True)
class OracleComparison:
    """Slot comparison. ``differ`` and ``ambiguous`` carry inspectable values."""

    status: str
    family: str | None = None
    local_name: str | None = None
    observation: str | None = None
    oracle_values: tuple[str, ...] = ()

    def finding(self, observation: Observation) -> dict[str, object]:
        return {
            "accession": observation.accession,
            "metric": observation.metric,
            "status": self.status,
            "family": self.family or "",
            "local_name": self.local_name or "",
            "observation": self.observation or "",
            "oracle_values": list(self.oracle_values),
        }


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _json_decimal(value: object) -> Decimal:
    if isinstance(value, bool | float):
        raise OracleInputError("companyfacts numbers must not pass through a binary float")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise OracleInputError(f"unsupported companyfacts number: {type(value).__name__}")


def _load_payload(companyfacts_json: str | bytes | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(companyfacts_json, Mapping):
        _reject_floats(companyfacts_json)
        return companyfacts_json
    text = (
        companyfacts_json.decode("utf-8")
        if isinstance(companyfacts_json, bytes)
        else companyfacts_json
    )
    loaded = json.loads(text, parse_float=Decimal)
    if not isinstance(loaded, dict):
        raise OracleInputError("companyfacts payload must be a JSON object")
    return loaded


def _reject_floats(value: object) -> None:
    if isinstance(value, float):
        raise OracleInputError("companyfacts numbers must not pass through a binary float")
    if isinstance(value, dict):
        for item in value.values():
            _reject_floats(item)
    elif isinstance(value, list):
        for item in value:
            _reject_floats(item)


def _record_period_matches(
    record: Mapping[str, Any],
    *,
    period_start: str | None,
    period_end: str,
) -> bool:
    end = record.get("end")
    if end != period_end:
        return False
    start = record.get("start")
    if period_start is None:
        return start is None
    return start == period_start


def oracle_value(
    companyfacts_json: str | bytes | Mapping[str, Any],
    *,
    cik: str,
    taxonomy_family: str,
    local_name: str,
    accession: str,
    period_end: str,
    unit: str,
    period_start: str | None = None,
) -> OracleHit | OracleAbsent | OracleAmbiguous:
    """Look up one companyfacts point.

    ``taxonomy_family`` is required. A local name alone is not an identity.
    ``period_start is None`` matches an instant point whose ``end`` is
    ``period_end``. A duration point must match both dates.
    """
    if not taxonomy_family or not local_name:
        raise OracleInputError("taxonomy_family and local_name are required")
    if not period_end or not unit:
        raise OracleInputError("period_end and unit are required")
    wanted_cik = validate_cik(cik)
    wanted_accession = validate_accession(accession)
    payload = _load_payload(companyfacts_json)
    raw_cik = payload.get("cik")
    if raw_cik is None:
        return OracleAbsent()
    if validate_cik(str(raw_cik)) != wanted_cik:
        return OracleAbsent()
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return OracleAbsent()
    family_facts = facts.get(taxonomy_family)
    if not isinstance(family_facts, dict):
        return OracleAbsent()
    concept = family_facts.get(local_name)
    if not isinstance(concept, dict):
        return OracleAbsent()
    units = concept.get("units")
    if not isinstance(units, dict):
        return OracleAbsent()
    points = units.get(unit)
    if not isinstance(points, list):
        return OracleAbsent()

    values: set[Decimal] = set()
    for point in points:
        if not isinstance(point, dict):
            continue
        accn = point.get("accn")
        if not isinstance(accn, str):
            continue
        try:
            if validate_accession(accn) != wanted_accession:
                continue
        except ValueError:
            continue
        if not _record_period_matches(point, period_start=period_start, period_end=period_end):
            continue
        if "val" not in point:
            continue
        values.add(_json_decimal(point["val"]))

    if not values:
        return OracleAbsent()
    if len(values) == 1:
        return OracleHit(value=next(iter(values)))
    return OracleAmbiguous(values=tuple(sorted(values)))


def source_fact_oracle_eligible(fact: FactRow) -> bool:
    """Companyfacts does not carry XBRL dimensions. Eligibility is the source fact."""
    classification = classify(fact.concept_namespace)
    if classification.origin != "standard":
        return False
    if classification.semantic_family not in _STANDARD_FAMILIES:
        return False
    if fact.has_dimensions:
        return False
    return _is_pure_usd(fact.unit_measures)


def oracle_comparison_for_observation(
    observation: Observation,
    facts_by_id: Mapping[int, FactRow],
    companyfacts_payload: str | bytes | Mapping[str, Any] | None,
) -> OracleComparison:
    """Compare one observation. Does not mutate it.

    ``na`` covers a non-value observation, an ineligible source fact, or a
    missing cache. ``differ`` and ``ambiguous`` keep the oracle decimals.
    """
    if observation.status != "value" or observation.numeric is None or not observation.period_end:
        return OracleComparison(status="na")
    eligible = [
        fact
        for fid in observation.fact_ids
        if (fact := facts_by_id.get(fid)) is not None
        and source_fact_oracle_eligible(fact)
        and fact.resolved_numeric == observation.numeric
    ]
    if not eligible or companyfacts_payload is None:
        return OracleComparison(status="na")
    fact = min(eligible, key=lambda item: item.fact_id)
    family = classify(fact.concept_namespace).semantic_family
    unit = observation.unit or "USD"
    observed = _decimal_text(observation.numeric)
    try:
        result = oracle_value(
            companyfacts_payload,
            cik=observation.cik,
            taxonomy_family=family,
            local_name=fact.concept_local_name,
            accession=observation.accession,
            period_end=observation.period_end,
            period_start=observation.period_start,
            unit=unit,
        )
    except (OracleInputError, ValueError):
        return OracleComparison(status="na")
    if isinstance(result, OracleAbsent):
        return OracleComparison(
            status="absent",
            family=family,
            local_name=fact.concept_local_name,
            observation=observed,
        )
    if isinstance(result, OracleAmbiguous):
        return OracleComparison(
            status="ambiguous",
            family=family,
            local_name=fact.concept_local_name,
            observation=observed,
            oracle_values=tuple(_decimal_text(value) for value in result.values),
        )
    if result.value == observation.numeric:
        return OracleComparison(
            status="agree",
            family=family,
            local_name=fact.concept_local_name,
            observation=observed,
            oracle_values=(_decimal_text(result.value),),
        )
    return OracleComparison(
        status="differ",
        family=family,
        local_name=fact.concept_local_name,
        observation=observed,
        oracle_values=(_decimal_text(result.value),),
    )


def oracle_label_for_observation(
    observation: Observation,
    facts_by_id: Mapping[int, FactRow],
    companyfacts_payload: str | bytes | Mapping[str, Any] | None,
) -> str:
    """One of agree, differ, absent, ambiguous, na. Does not mutate the observation."""
    return oracle_comparison_for_observation(
        observation,
        facts_by_id,
        companyfacts_payload,
    ).status
