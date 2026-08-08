"""Immutable FilingBundle domain types (ADR 0009)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, get_args

from edgar.domain.decode import (
    BundleDecodeError,
    require_bool,
    require_exact_keys,
    require_int,
    require_list,
    require_list_of_str,
    require_nullable_canonical_date,
    require_nullable_canonical_datetime,
    require_object,
    require_str,
)
from edgar.domain.identifiers import (
    SUPPORTED_FORMS,
    assert_cik_accession_consistent,
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

ARTIFACT_KINDS: frozenset[str] = frozenset(get_args(ArtifactKind))

_FILING_KEYS = frozenset(
    {
        "cik",
        "accession",
        "form_type",
        "filing_date",
        "accepted_at",
        "report_period_end",
        "primary_document",
    }
)
_ARTIFACT_KEYS = frozenset({"logical_path", "sha256", "byte_size", "artifact_kind", "required"})
_BINDING_KEYS = frozenset({"document_uri", "artifact_path", "content_sha256", "replay_aliases"})
_INSTANCE_KEYS = frozenset({"kind", "document_uris"})
_IXDS_KEYS = frozenset({"kind", "document_uris", "target"})
_BUNDLE_KEYS = frozenset(
    {
        "schema_version",
        "acquisition_policy_version",
        "filing",
        "payload_hash",
        "artifacts",
        "report_inputs",
        "uri_bindings",
    }
)


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
        assert_cik_accession_consistent(self.cik, self.accession)
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
        from edgar.domain.decode import require_canonical_date
        from edgar.domain.validation import (
            assert_canonical_serialized_accession,
            assert_canonical_serialized_cik,
        )

        obj = require_object(data, label="filing")
        require_exact_keys(obj, _FILING_KEYS, label="filing")
        return cls(
            cik=assert_canonical_serialized_cik(require_str(obj["cik"], label="filing.cik")),
            accession=assert_canonical_serialized_accession(
                require_str(obj["accession"], label="filing.accession")
            ),
            form_type=require_str(obj["form_type"], label="filing.form_type"),
            filing_date=require_canonical_date(obj["filing_date"], label="filing.filing_date"),
            accepted_at=require_nullable_canonical_datetime(
                obj["accepted_at"], label="filing.accepted_at"
            ),
            report_period_end=require_nullable_canonical_date(
                obj["report_period_end"], label="filing.report_period_end"
            ),
            primary_document=require_str(obj["primary_document"], label="filing.primary_document"),
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
        obj = require_object(data, label="artifact")
        require_exact_keys(obj, _ARTIFACT_KEYS, label="artifact")
        kind = require_str(obj["artifact_kind"], label="artifact.artifact_kind")
        if kind not in ARTIFACT_KINDS:
            raise BundleDecodeError(f"invalid artifact_kind: {kind!r}")
        return cls(
            logical_path=require_str(obj["logical_path"], label="artifact.logical_path"),
            content=ContentObject(
                sha256=require_str(obj["sha256"], label="artifact.sha256"),
                byte_size=require_int(obj["byte_size"], label="artifact.byte_size"),
            ),
            artifact_kind=kind,  # type: ignore[arg-type]
            required=require_bool(obj["required"], label="artifact.required"),
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
        obj = require_object(data, label="uri_binding")
        require_exact_keys(obj, _BINDING_KEYS, label="uri_binding")
        aliases = require_list_of_str(obj["replay_aliases"], label="uri_binding.replay_aliases")
        return cls(
            document_uri=require_str(obj["document_uri"], label="uri_binding.document_uri"),
            artifact_path=require_str(obj["artifact_path"], label="uri_binding.artifact_path"),
            content_sha256=require_str(obj["content_sha256"], label="uri_binding.content_sha256"),
            replay_aliases=tuple(aliases),
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
    obj = require_object(data, label="report_input")
    if "kind" not in obj:
        raise BundleDecodeError("report_input missing fields: ['kind']")
    kind = require_str(obj["kind"], label="report_input.kind")
    if kind == "instance":
        require_exact_keys(obj, _INSTANCE_KEYS, label="report_input")
        uris = require_list_of_str(obj["document_uris"], label="report_input.document_uris")
        return InstanceReportInput(document_uris=tuple(uris))
    if kind == "ixds":
        require_exact_keys(obj, _IXDS_KEYS, label="report_input")
        uris = require_list_of_str(obj["document_uris"], label="report_input.document_uris")
        target = require_str(obj["target"], label="report_input.target")
        if target != "default":
            raise BundleDecodeError(f"unsupported IXDS target: {target!r}")
        return IxdsReportInput(document_uris=tuple(uris), target="default")
    raise BundleDecodeError(f"unknown report input kind: {kind!r}")


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
        obj = require_object(data, label="bundle")
        require_exact_keys(obj, _BUNDLE_KEYS, label="bundle")
        schema_version = require_int(obj["schema_version"], label="bundle.schema_version")
        payload_hash = require_str(obj["payload_hash"], label="bundle.payload_hash")
        if len(payload_hash) != 64 or any(c not in "0123456789abcdef" for c in payload_hash):
            raise BundleDecodeError(f"invalid payload_hash syntax: {payload_hash!r}")
        artifacts = require_list(obj["artifacts"], label="bundle.artifacts")
        report_inputs = require_list(obj["report_inputs"], label="bundle.report_inputs")
        uri_bindings = require_list(obj["uri_bindings"], label="bundle.uri_bindings")
        return cls(
            schema_version=schema_version,
            acquisition_policy_version=require_str(
                obj["acquisition_policy_version"], label="bundle.acquisition_policy_version"
            ),
            filing=FilingIdentity.from_dict(obj["filing"]),
            payload_hash=payload_hash,
            artifacts=tuple(BundleArtifact.from_dict(a) for a in artifacts),
            report_inputs=tuple(report_input_from_dict(r) for r in report_inputs),
            uri_bindings=tuple(UriBinding.from_dict(b) for b in uri_bindings),
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
    """Normalized domain state for equality/reuse (not raw JSON bytes).

    Equality compares timezone-aware accepted_at by UTC instant, not lexical offset.
    """
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
    filing_state = bundle.filing.to_dict()
    if bundle.filing.accepted_at is not None:
        filing_state["accepted_at"] = bundle.filing.accepted_at.astimezone(UTC).isoformat()
    return {
        "schema_version": bundle.schema_version,
        "acquisition_policy_version": bundle.acquisition_policy_version,
        "filing": filing_state,
        "payload_hash": bundle.payload_hash,
        "artifacts": artifacts,
        "report_inputs": report_inputs,
        "uri_bindings": bindings,
    }


def bundles_equivalent(left: FilingBundle, right: FilingBundle) -> bool:
    return bundle_equality_state(left) == bundle_equality_state(right)
