"""Typed corpus manifest loader for Phase 1D real-corpus acceptance."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edgar.domain.identifiers import validate_accession, validate_cik

CorpusForm = Literal["10-K", "10-K/A", "10-Q", "10-Q/A"]


class CorpusFiling(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str = Field(min_length=1)
    company: str = Field(min_length=1)
    cik: str
    accession: str
    form: CorpusForm
    industry_group: str = Field(min_length=1)
    filed: str | None = None
    amends: str | None = None

    @field_validator("cik")
    @classmethod
    def _cik(cls, value: str) -> str:
        return validate_cik(value)

    @field_validator("accession")
    @classmethod
    def _accession(cls, value: str) -> str:
        return validate_accession(value)

    @field_validator("amends")
    @classmethod
    def _amends(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_accession(value)


class CorpusManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    filings: tuple[CorpusFiling, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _cross_record(self) -> Self:
        accessions = [f.accession for f in self.filings]
        if len(set(accessions)) != len(accessions):
            raise ValueError("duplicate accession in corpus manifest")

        roles = [f.role for f in self.filings]
        if len(set(roles)) != len(roles):
            raise ValueError("duplicate role in corpus manifest")

        accession_set = set(accessions)
        for filing in self.filings:
            if filing.amends is not None and filing.amends not in accession_set:
                raise ValueError(
                    f"amends accession {filing.amends!r} for role {filing.role!r} "
                    "is not present in this corpus"
                )
        return self


def load_corpus_manifest(path: Path) -> CorpusManifest:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    filings_raw = raw.get("filings")
    if not filings_raw:
        raise ValueError("corpus manifest must contain a non-empty filings array")
    return CorpusManifest(filings=tuple(CorpusFiling.model_validate(item) for item in filings_raw))
