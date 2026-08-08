"""Immutable FilingBundle domain types (ADR 0009)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from edgar.domain.identifiers import (
    SUPPORTED_FORMS,
    validate_accession,
    validate_cik,
    validate_logical_path,
)

BUNDLE_SCHEMA_VERSION = 1
ACQUISITION_POLICY_VERSION = "acq-v1"
URI_IDENTITY_VERSION = "uri-identity-v1"

ArtifactKind = Literal[
    "accession",
    "metadata",
    "external",
    "complete_submission",
    "primary_document",
    "taxonomy_schema",
    "linkbase",
    "attachment",
    "index_json",
    "index_html",
    "index_headers",
    "discovery",
    "sec_generated",
    "other",
]


@dataclass(frozen=True)
class ContentObject:
    sha256: str
    byte_size: int

    def __post_init__(self) -> None:
        digest = self.sha256.lower()
        hex_ok = len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
        if digest != self.sha256 or not hex_ok:
            raise ValueError(f"sha256 must be 64 lowercase hex chars: {self.sha256!r}")
        if self.byte_size < 0:
            raise ValueError("byte_size must be non-negative")


@dataclass(frozen=True)
class FilingIdentity:
    cik: str
    accession: str
    form_type: str
    filing_date: date
    accepted_at: datetime | None
    report_period_end: date | None
    primary_document: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "cik", validate_cik(self.cik))
        object.__setattr__(self, "accession", validate_accession(self.accession))
        if self.form_type not in SUPPORTED_FORMS:
            raise ValueError(f"unsupported form_type: {self.form_type!r}")
        primary = self.primary_document
        if not primary or "/" in primary or "\\" in primary:
            raise ValueError(f"invalid primary_document: {primary!r}")
        if self.accepted_at is not None and self.accepted_at.tzinfo is None:
            raise ValueError("accepted_at must be timezone-aware when set")

    def to_dict(self) -> dict[str, Any]:
        period = self.report_period_end.isoformat() if self.report_period_end else None
        return {
            "cik": self.cik,
            "accession": self.accession,
            "form_type": self.form_type,
            "filing_date": self.filing_date.isoformat(),
            "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
            "report_period_end": period,
            "primary_document": self.primary_document,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilingIdentity:
        from edgar.domain.validation import (
            assert_canonical_serialized_accession,
            assert_canonical_serialized_cik,
        )

        if not isinstance(data, dict):
            raise ValueError("filing identity must be an object")
        accepted = data.get("accepted_at")
        period = data.get("report_period_end")
        return cls(
            cik=assert_canonical_serialized_cik(data["cik"]),
            accession=assert_canonical_serialized_accession(data["accession"]),
            form_type=data["form_type"],
            filing_date=date.fromisoformat(data["filing_date"]),
            accepted_at=datetime.fromisoformat(accepted) if accepted else None,
            report_period_end=date.fromisoformat(period) if period else None,
            primary_document=data["primary_document"],
        )


@dataclass(frozen=True)
class BundleArtifact:
    logical_path: str
    content: ContentObject
    artifact_kind: ArtifactKind
    required: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "logical_path", validate_logical_path(self.logical_path))

    def equality_tuple(self) -> tuple[str, str, int, str, bool]:
        return (
            self.logical_path,
            self.content.sha256,
            self.content.byte_size,
            self.artifact_kind,
            self.required,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_path": self.logical_path,
            "sha256": self.content.sha256,
            "byte_size": self.content.byte_size,
            "artifact_kind": self.artifact_kind,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BundleArtifact:
        return cls(
            logical_path=data["logical_path"],
            content=ContentObject(sha256=data["sha256"], byte_size=int(data["byte_size"])),
            artifact_kind=data["artifact_kind"],
            required=bool(data["required"]),
        )


@dataclass(frozen=True)
class UriBinding:
    document_uri: str
    artifact_path: str
    content_sha256: str
    replay_aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_path", validate_logical_path(self.artifact_path))
        digest = self.content_sha256
        hex_ok = len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
        if digest != digest.lower() or not hex_ok:
            raise ValueError(
                f"content_sha256 must be 64 lowercase hex chars: {self.content_sha256!r}"
            )
        if len(self.replay_aliases) != len(set(self.replay_aliases)):
            raise ValueError("replay_aliases contains duplicates")

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_uri": self.document_uri,
            "artifact_path": self.artifact_path,
            "content_sha256": self.content_sha256,
            "replay_aliases": list(self.replay_aliases),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UriBinding:
        aliases = data.get("replay_aliases")
        if aliases is None:
            alias_tuple: tuple[str, ...] = ()
        elif not isinstance(aliases, list):
            raise ValueError("replay_aliases must be a list when present")
        else:
            alias_tuple = tuple(aliases)
        return cls(
            document_uri=data["document_uri"],
            artifact_path=data["artifact_path"],
            content_sha256=data["content_sha256"],
            replay_aliases=alias_tuple,
        )


@dataclass(frozen=True)
class InstanceReportInput:
    document_uris: tuple[str, ...]
    kind: Literal["instance"] = "instance"

    def __post_init__(self) -> None:
        if len(self.document_uris) != 1:
            raise ValueError("InstanceReportInput requires exactly one document URI")
        if not self.document_uris[0]:
            raise ValueError("document URI must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "document_uris": list(self.document_uris)}


@dataclass(frozen=True)
class IxdsReportInput:
    document_uris: tuple[str, ...]
    target: Literal["default"] = "default"
    kind: Literal["ixds"] = "ixds"

    def __post_init__(self) -> None:
        if not self.document_uris:
            raise ValueError("IxdsReportInput requires at least one document URI")
        if len(set(self.document_uris)) != len(self.document_uris):
            raise ValueError("IxdsReportInput document_uris must be unique")
        if self.target != "default":
            raise ValueError("Phase 1 only supports target='default'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "document_uris": list(self.document_uris),
            "target": self.target,
        }


XbrlReportInput = InstanceReportInput | IxdsReportInput


def report_input_from_dict(data: dict[str, Any]) -> XbrlReportInput:
    kind = data["kind"]
    uris = tuple(data["document_uris"])
    if kind == "instance":
        return InstanceReportInput(document_uris=uris)
    if kind == "ixds":
        return IxdsReportInput(document_uris=uris, target=data.get("target", "default"))
    raise ValueError(f"unknown report input kind: {kind!r}")


@dataclass(frozen=True)
class FilingBundle:
    filing: FilingIdentity
    payload_hash: str
    artifacts: tuple[BundleArtifact, ...]
    report_inputs: tuple[XbrlReportInput, ...]
    uri_bindings: tuple[UriBinding, ...]
    schema_version: int = BUNDLE_SCHEMA_VERSION
    acquisition_policy_version: str = ACQUISITION_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BUNDLE_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {self.schema_version}")
        if len(self.report_inputs) != 1:
            raise ValueError("Phase 1 FilingBundle requires exactly one primary report input")
        paths = [a.logical_path for a in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate artifact logical_path")

    def artifact_by_path(self, logical_path: str) -> BundleArtifact | None:
        for artifact in self.artifacts:
            if artifact.logical_path == logical_path:
                return artifact
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "acquisition_policy_version": self.acquisition_policy_version,
            "filing": self.filing.to_dict(),
            "payload_hash": self.payload_hash,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "report_inputs": [r.to_dict() for r in self.report_inputs],
            "uri_bindings": [b.to_dict() for b in self.uri_bindings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilingBundle:
        if not isinstance(data, dict):
            raise ValueError("bundle descriptor must be an object")
        required = {
            "schema_version",
            "acquisition_policy_version",
            "filing",
            "payload_hash",
            "artifacts",
            "report_inputs",
            "uri_bindings",
        }
        missing = required - set(data)
        if missing:
            raise ValueError(f"bundle descriptor missing fields: {sorted(missing)}")
        unknown = set(data) - required
        if unknown:
            raise ValueError(f"bundle descriptor has unknown fields: {sorted(unknown)}")
        if not isinstance(data["artifacts"], list):
            raise ValueError("artifacts must be a list")
        if not isinstance(data["report_inputs"], list):
            raise ValueError("report_inputs must be a list")
        if not isinstance(data["uri_bindings"], list):
            raise ValueError("uri_bindings must be a list")
        payload_hash = data["payload_hash"]
        if (
            not isinstance(payload_hash, str)
            or len(payload_hash) != 64
            or any(c not in "0123456789abcdef" for c in payload_hash)
        ):
            raise ValueError(f"invalid payload_hash syntax: {payload_hash!r}")
        return cls(
            schema_version=int(data["schema_version"]),
            acquisition_policy_version=data["acquisition_policy_version"],
            filing=FilingIdentity.from_dict(data["filing"]),
            payload_hash=payload_hash,
            artifacts=tuple(BundleArtifact.from_dict(a) for a in data["artifacts"]),
            report_inputs=tuple(report_input_from_dict(r) for r in data["report_inputs"]),
            uri_bindings=tuple(UriBinding.from_dict(b) for b in data["uri_bindings"]),
        )


@dataclass(frozen=True)
class AcquisitionObservation:
    """Operational retrieval provenance — outside FilingBundle identity."""

    attempt_id: str
    accession: str
    requested_uri: str
    final_uri: str | None
    observed_at: datetime
    status: str
    content_sha256: str | None = None
    byte_size: int | None = None
    http_status: int | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")


def bundle_equality_state(bundle: FilingBundle) -> dict[str, Any]:
    """Normalized domain state for equality/reuse (not raw JSON bytes)."""
    artifacts = sorted(
        (
            {
                "logical_path": a.logical_path,
                "sha256": a.content.sha256,
                "byte_size": a.content.byte_size,
                "artifact_kind": a.artifact_kind,
                "required": a.required,
            }
            for a in bundle.artifacts
        ),
        key=lambda item: item["logical_path"].encode("utf-8"),
    )
    bindings = sorted(
        (
            {
                "document_uri": b.document_uri,
                "artifact_path": b.artifact_path,
                "content_sha256": b.content_sha256,
                "replay_aliases": sorted(b.replay_aliases),
            }
            for b in bundle.uri_bindings
        ),
        key=lambda item: item["document_uri"],
    )
    report_inputs = [r.to_dict() for r in bundle.report_inputs]
    return {
        "schema_version": bundle.schema_version,
        "acquisition_policy_version": bundle.acquisition_policy_version,
        "filing": bundle.filing.to_dict(),
        "payload_hash": bundle.payload_hash,
        "artifacts": artifacts,
        "report_inputs": report_inputs,
        "uri_bindings": bindings,
    }


def bundles_equivalent(left: FilingBundle, right: FilingBundle) -> bool:
    return bundle_equality_state(left) == bundle_equality_state(right)
