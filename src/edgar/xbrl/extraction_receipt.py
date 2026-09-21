"""Extraction receipt schema and validation (M1A-1).

Receipt-v1 owns the serialized shapes of nested provenance structures
(``bundle_ref.manifest``, ``semantic_config``, ``report_input``, …). Today's
decoder may delegate to live ``FilingBundle`` / ``SemanticConfig`` /
``report_input_from_dict`` codecs while those codecs still accept the
persisted v1 shapes. A future incompatible nested schema must either preserve
a receipt-v1 nested decoder or bump ``receipt_version``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from edgar.domain.bundle import FilingBundle, FilingIdentity, report_input_from_dict
from edgar.domain.decode import (
    BundleDecodeError,
    require_exact_keys,
    require_int,
    require_object,
    require_str,
)
from edgar.domain.identifiers import assert_path_under, validate_logical_path
from edgar.domain.report_key import report_input_payload
from edgar.domain.report_key import report_key as compute_report_key
from edgar.provenance import ImplementationIdentity
from edgar.storage.bundles import (
    BundleStorageError,
    validate_bundle_integrity,
    validate_published_bundle_path,
)
from edgar.storage.objects import ObjectStore
from edgar.xbrl.config import SemanticConfig
from edgar.xbrl.source_records import EXTRACTOR_VERSION, SOURCE_RECORDS_SCHEMA_VERSION

RECEIPT_VERSION = "extraction-receipt-v1"

_RECEIPT_KEYS: frozenset[str] = frozenset(
    {
        "receipt_version",
        "bundle_ref",
        "report_input",
        "semantic_config",
        "semantic_config_sha256",
        "extractor_version",
        "source_records_schema_version",
        "worker_protocol_version",
        "arelle_version",
        "implementation",
        "dependency_lock_sha256",
    }
)
_BUNDLE_REF_KEYS: frozenset[str] = frozenset(
    {"descriptor_relative_path", "descriptor_sha256", "manifest"}
)
_IMPLEMENTATION_KEYS: frozenset[str] = frozenset({"revision", "tree_state", "dirty_tree_digest"})
_TREE_STATES: frozenset[str] = frozenset({"clean", "dirty", "unknown"})


class ReceiptValidationError(ValueError):
    """Receipt binding or artifact verification failed."""


def _sha256_hex(value: object, *, label: str) -> str:
    raw = require_str(value, label=label)
    if len(raw) != 64 or any(c not in "0123456789abcdef" for c in raw):
        raise ReceiptValidationError(f"{label} must be 64 lowercase hex chars")
    return raw


def _optional_sha256_hex(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _sha256_hex(value, label=label)


@dataclass(frozen=True)
class BundleRef:
    descriptor_relative_path: str
    descriptor_sha256: str
    manifest: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptor_relative_path": self.descriptor_relative_path,
            "descriptor_sha256": self.descriptor_sha256,
            "manifest": self.manifest,
        }


@dataclass(frozen=True)
class LoadedBundleRef:
    bundle_ref: BundleRef
    bundle: FilingBundle


@dataclass(frozen=True)
class ExtractionReceipt:
    receipt_version: str
    bundle_ref: BundleRef
    report_input: dict[str, Any]
    semantic_config: dict[str, Any]
    extractor_version: str
    source_records_schema_version: int
    worker_protocol_version: str
    arelle_version: str
    implementation: ImplementationIdentity
    dependency_lock_sha256: str | None
    semantic_config_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        impl = self.implementation
        return {
            "receipt_version": self.receipt_version,
            "bundle_ref": self.bundle_ref.to_dict(),
            "report_input": self.report_input,
            "semantic_config": self.semantic_config,
            "semantic_config_sha256": self.semantic_config_sha256,
            "extractor_version": self.extractor_version,
            "source_records_schema_version": self.source_records_schema_version,
            "worker_protocol_version": self.worker_protocol_version,
            "arelle_version": self.arelle_version,
            "implementation": {
                "revision": impl.revision,
                "tree_state": impl.tree_state,
                "dirty_tree_digest": impl.dirty_tree_digest,
            },
            "dependency_lock_sha256": self.dependency_lock_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExtractionReceipt:
        return decode_extraction_receipt(data)


@dataclass(frozen=True)
class PersistedReportRow:
    """Columns from ``source.xbrl_report`` plus owning filing identity."""

    report_input: dict[str, Any]
    report_key: str
    extractor_version: str
    arelle_version: str
    filing: FilingIdentity


@dataclass(frozen=True)
class ProvenanceEvidence:
    implementation: ImplementationIdentity
    dependency_lock_sha256: str


def semantic_config_canonical_digest(config: Mapping[str, Any]) -> str:
    cfg = SemanticConfig.from_dict(config)
    payload = json.dumps(cfg.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_published_descriptor(data_root: Path, bundle_dir: Path) -> Path:
    """Resolve ``bundle.json`` under a canonical published bundle directory."""
    try:
        root = data_root.expanduser().resolve()
        validate_published_bundle_path(root, bundle_dir)
        published_dir = assert_path_under(
            bundle_dir.expanduser().resolve(),
            root / "bundles",
        )
        descriptor = assert_path_under(published_dir / "bundle.json", root)
    except ValueError as exc:
        raise ReceiptValidationError(str(exc)) from exc
    if descriptor.name != "bundle.json":
        raise ReceiptValidationError(
            f"descriptor must be named bundle.json, got {descriptor.name!r}"
        )
    return descriptor


def load_bundle_ref(*, data_root: Path, bundle_dir: Path) -> LoadedBundleRef:
    """Single authoritative descriptor read → BundleRef + FilingBundle."""
    root = data_root.expanduser().resolve()
    descriptor = resolve_published_descriptor(root, bundle_dir)
    try:
        raw = descriptor.read_bytes()
        decoded = FilingBundle.from_dict(json.loads(raw.decode("utf-8")))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        BundleDecodeError,
        ValueError,
    ) as exc:
        raise ReceiptValidationError(f"descriptor is not a valid bundle: {exc}") from exc
    return LoadedBundleRef(
        bundle_ref=BundleRef(
            descriptor_relative_path=descriptor.relative_to(root).as_posix(),
            descriptor_sha256=hashlib.sha256(raw).hexdigest(),
            manifest=decoded.to_dict(),
        ),
        bundle=decoded,
    )


def _decode_implementation(data: Mapping[str, Any]) -> ImplementationIdentity:
    obj = require_object(data, label="implementation")
    require_exact_keys(obj, _IMPLEMENTATION_KEYS, label="implementation")
    revision = obj["revision"]
    if revision is not None:
        revision = require_str(revision, label="implementation.revision")
        if not revision:
            raise ReceiptValidationError("implementation.revision must be non-empty when set")
    tree_state = require_str(obj["tree_state"], label="implementation.tree_state")
    if tree_state not in _TREE_STATES:
        raise ReceiptValidationError(f"invalid implementation.tree_state: {tree_state!r}")
    dirty = _optional_sha256_hex(obj["dirty_tree_digest"], label="implementation.dirty_tree_digest")
    return ImplementationIdentity(
        revision=revision,
        tree_state=tree_state,  # type: ignore[arg-type]
        dirty_tree_digest=dirty,
    )


def _decode_bundle_ref(data: Mapping[str, Any]) -> BundleRef:
    obj = require_object(data, label="bundle_ref")
    require_exact_keys(obj, _BUNDLE_REF_KEYS, label="bundle_ref")
    relative = require_str(
        obj["descriptor_relative_path"],
        label="bundle_ref.descriptor_relative_path",
    )
    try:
        validate_logical_path(relative)
    except ValueError as exc:
        raise ReceiptValidationError(str(exc)) from exc
    if ".." in relative.split("/"):
        raise ReceiptValidationError("descriptor_relative_path must not contain '..'")
    digest = _sha256_hex(obj["descriptor_sha256"], label="bundle_ref.descriptor_sha256")
    manifest_obj = require_object(obj["manifest"], label="bundle_ref.manifest")
    # Strict codec for nested FilingBundle shape (receipt-v1 compatibility).
    FilingBundle.from_dict(manifest_obj)
    return BundleRef(
        descriptor_relative_path=relative,
        descriptor_sha256=digest,
        manifest=dict(manifest_obj),
    )


def decode_extraction_receipt(data: Mapping[str, Any]) -> ExtractionReceipt:
    """Strict receipt-v1 decode. Does not require current EXTRACTOR/SCHEMA/WORKER versions."""
    try:
        obj = require_object(data, label="extraction_receipt")
        require_exact_keys(obj, _RECEIPT_KEYS, label="extraction_receipt")
        receipt_version = require_str(obj["receipt_version"], label="receipt_version")
        if receipt_version != RECEIPT_VERSION:
            raise ReceiptValidationError(f"unsupported receipt_version: {receipt_version!r}")
        report_input = report_input_from_dict(obj["report_input"]).to_dict()
        semantic_config = SemanticConfig.from_dict(obj["semantic_config"]).to_dict()
        return ExtractionReceipt(
            receipt_version=receipt_version,
            bundle_ref=_decode_bundle_ref(obj["bundle_ref"]),
            report_input=report_input,
            semantic_config=semantic_config,
            semantic_config_sha256=_optional_sha256_hex(
                obj["semantic_config_sha256"], label="semantic_config_sha256"
            ),
            extractor_version=require_str(obj["extractor_version"], label="extractor_version"),
            source_records_schema_version=require_int(
                obj["source_records_schema_version"],
                label="source_records_schema_version",
            ),
            worker_protocol_version=require_str(
                obj["worker_protocol_version"], label="worker_protocol_version"
            ),
            arelle_version=require_str(obj["arelle_version"], label="arelle_version"),
            implementation=_decode_implementation(obj["implementation"]),
            dependency_lock_sha256=_optional_sha256_hex(
                obj["dependency_lock_sha256"], label="dependency_lock_sha256"
            ),
        )
    except (BundleDecodeError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, ReceiptValidationError):
            raise
        raise ReceiptValidationError(str(exc)) from exc


def _normalize_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def filing_identity_semantically_equal(left: FilingIdentity, right: FilingIdentity) -> bool:
    if left.cik != right.cik or left.accession != right.accession:
        return False
    if left.form_type != right.form_type:
        return False
    if left.filing_date != right.filing_date:
        return False
    if left.primary_document != right.primary_document:
        return False
    if _normalize_date(left.report_period_end) != _normalize_date(right.report_period_end):
        return False
    left_accepted = left.accepted_at
    right_accepted = right.accepted_at
    if left_accepted is None and right_accepted is None:
        return True
    if left_accepted is None or right_accepted is None:
        return False
    return left_accepted.astimezone(UTC) == right_accepted.astimezone(UTC)


def validate_persisted_receipt_semantics(receipt: ExtractionReceipt) -> None:
    """Deserialize receipt config and optional digest (post-persist / read path)."""
    try:
        cfg = SemanticConfig.from_dict(receipt.semantic_config)
    except ValueError as exc:
        raise ReceiptValidationError(str(exc)) from exc
    round_trip = cfg.to_dict()
    if round_trip != receipt.semantic_config:
        raise ReceiptValidationError("receipt semantic_config is not canonical typed form")
    if receipt.semantic_config_sha256 is not None:
        expected = semantic_config_canonical_digest(receipt.semantic_config)
        if receipt.semantic_config_sha256 != expected:
            raise ReceiptValidationError("semantic_config_sha256 does not match receipt config")


def validate_receipt_binding(row: PersistedReportRow, receipt: ExtractionReceipt) -> None:
    """Structural binding between a persisted report row and its receipt."""
    validate_persisted_receipt_semantics(receipt)
    if row.report_input != receipt.report_input:
        raise ReceiptValidationError("report_input mismatch between row and receipt")
    if compute_report_key(receipt.report_input) != row.report_key:
        raise ReceiptValidationError("report_key does not match receipt report_input")
    if row.extractor_version != receipt.extractor_version:
        raise ReceiptValidationError("extractor_version mismatch")
    if row.arelle_version != receipt.arelle_version:
        raise ReceiptValidationError("arelle_version mismatch")
    manifest_inputs = receipt.bundle_ref.manifest.get("report_inputs")
    if not isinstance(manifest_inputs, list):
        raise ReceiptValidationError("bundle manifest missing report_inputs")
    canonical = report_input_payload(receipt.report_input)
    occurrences = sum(1 for item in manifest_inputs if report_input_payload(item) == canonical)
    if occurrences != 1:
        raise ReceiptValidationError(
            "receipt report_input must occur exactly once in bundle manifest report_inputs"
        )
    manifest_filing = receipt.bundle_ref.manifest.get("filing")
    if not isinstance(manifest_filing, dict):
        raise ReceiptValidationError("bundle manifest missing filing")
    try:
        bundle_filing = FilingIdentity.from_dict(manifest_filing)
    except (BundleDecodeError, ValueError) as exc:
        raise ReceiptValidationError(str(exc)) from exc
    if not filing_identity_semantically_equal(bundle_filing, row.filing):
        raise ReceiptValidationError("bundle manifest filing does not match owning source.filing")


def verify_receipt_artifacts(
    receipt: ExtractionReceipt,
    *,
    data_root: Path,
    store: ObjectStore,
) -> None:
    """Descriptor bytes, published layout, manifest equivalence, and CAS artifacts."""
    try:
        root = data_root.expanduser().resolve()
        relative = receipt.bundle_ref.descriptor_relative_path
        try:
            validate_logical_path(relative)
            descriptor_path = assert_path_under(
                (root / relative).resolve(),
                root,
            )
        except ValueError as exc:
            raise ReceiptValidationError(str(exc)) from exc
        canonical = resolve_published_descriptor(root, descriptor_path.parent)
        canonical_relative = canonical.relative_to(root).as_posix()
        if relative != canonical_relative:
            raise ReceiptValidationError(
                "descriptor_relative_path is not the canonical published bundle.json"
            )
        _, path_cik, path_accession = validate_published_bundle_path(root, canonical.parent)
        if not descriptor_path.is_file():
            raise ReceiptValidationError(f"missing descriptor at {descriptor_path}")
        raw = descriptor_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != receipt.bundle_ref.descriptor_sha256:
            raise ReceiptValidationError("descriptor_sha256 mismatch")
        parsed = json.loads(raw.decode("utf-8"))
        bundle = FilingBundle.from_dict(parsed)
        if bundle.filing.cik != path_cik:
            raise ReceiptValidationError(
                "descriptor filing CIK does not match publication path CIK"
            )
        if bundle.filing.accession != path_accession:
            raise ReceiptValidationError(
                "descriptor filing accession does not match publication path accession"
            )
        if bundle.to_dict() != receipt.bundle_ref.manifest:
            raise ReceiptValidationError("receipt manifest does not match descriptor content")
        validate_bundle_integrity(bundle, store)
    except ReceiptValidationError:
        raise
    except (
        BundleStorageError,
        BundleDecodeError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ReceiptValidationError(str(exc)) from exc


def verify_extraction_config_chain(
    *,
    job_semantic_config: Mapping[str, Any],
    worker_effective_semantic_config: Mapping[str, Any],
    receipt_semantic_config: Mapping[str, Any],
    worker_protocol_version: str,
    expected_worker_protocol_version: str,
    receipt_worker_protocol_version: str,
) -> None:
    """Pre-persist equality proof for config and worker protocol (not row-vs-receipt)."""
    if worker_protocol_version != expected_worker_protocol_version:
        raise ReceiptValidationError("worker result protocol_version mismatch")
    if receipt_worker_protocol_version != expected_worker_protocol_version:
        raise ReceiptValidationError("receipt worker_protocol_version mismatch")
    try:
        job_cfg = SemanticConfig.from_dict(job_semantic_config).to_dict()
        worker_cfg = SemanticConfig.from_dict(worker_effective_semantic_config).to_dict()
        receipt_cfg = SemanticConfig.from_dict(receipt_semantic_config).to_dict()
    except ValueError as exc:
        raise ReceiptValidationError(str(exc)) from exc
    if job_cfg != worker_cfg or job_cfg != receipt_cfg:
        raise ReceiptValidationError("semantic_config chain mismatch (job, worker, receipt)")


def verify_provenance_evidence(
    receipt: ExtractionReceipt,
    expected: ProvenanceEvidence,
    *,
    require_clean: bool = False,
) -> None:
    """Compare full ImplementationIdentity + lock; dirty without digest is unverifiable."""
    impl = receipt.implementation
    if not impl.revision or impl.tree_state == "unknown":
        raise ReceiptValidationError("implementation identity is unknown")
    if impl.tree_state == "dirty" and impl.dirty_tree_digest is None:
        raise ReceiptValidationError(
            "dirty implementation without dirty_tree_digest is unverifiable"
        )
    if impl != expected.implementation:
        raise ReceiptValidationError("implementation identity does not match expected evidence")
    if receipt.dependency_lock_sha256 != expected.dependency_lock_sha256:
        raise ReceiptValidationError("dependency_lock_sha256 does not match expected evidence")
    if require_clean and impl.tree_state != "clean":
        raise ReceiptValidationError("require_clean demands tree_state=clean")


def receipt_verified(
    row: PersistedReportRow,
    payload: Mapping[str, Any],
    *,
    data_root: Path,
    store: ObjectStore,
    expected: ProvenanceEvidence,
    require_clean: bool = False,
) -> bool:
    """Whether the receipt is publication-eligible under M1A rules."""
    try:
        receipt = decode_extraction_receipt(payload)
        validate_receipt_binding(row, receipt)
        verify_receipt_artifacts(receipt, data_root=data_root, store=store)
        verify_provenance_evidence(receipt, expected, require_clean=require_clean)
    except ReceiptValidationError:
        return False
    return True


def build_extraction_receipt(
    *,
    bundle_ref: BundleRef,
    report_input: dict[str, Any],
    semantic_config: dict[str, Any],
    arelle_version: str,
    worker_protocol_version: str,
    implementation: ImplementationIdentity,
    dependency_lock_sha256: str | None,
    include_config_digest: bool = True,
) -> ExtractionReceipt:
    SemanticConfig.from_dict(semantic_config)
    digest = semantic_config_canonical_digest(semantic_config) if include_config_digest else None
    return ExtractionReceipt(
        receipt_version=RECEIPT_VERSION,
        bundle_ref=bundle_ref,
        report_input=dict(report_input),
        semantic_config=dict(semantic_config),
        semantic_config_sha256=digest,
        extractor_version=EXTRACTOR_VERSION,
        source_records_schema_version=SOURCE_RECORDS_SCHEMA_VERSION,
        worker_protocol_version=worker_protocol_version,
        arelle_version=arelle_version,
        implementation=implementation,
        dependency_lock_sha256=dependency_lock_sha256,
    )


__all__ = [
    "BundleRef",
    "ExtractionReceipt",
    "LoadedBundleRef",
    "PersistedReportRow",
    "ProvenanceEvidence",
    "RECEIPT_VERSION",
    "ReceiptValidationError",
    "build_extraction_receipt",
    "decode_extraction_receipt",
    "filing_identity_semantically_equal",
    "load_bundle_ref",
    "receipt_verified",
    "resolve_published_descriptor",
    "semantic_config_canonical_digest",
    "validate_persisted_receipt_semantics",
    "validate_receipt_binding",
    "verify_extraction_config_chain",
    "verify_provenance_evidence",
    "verify_receipt_artifacts",
]
