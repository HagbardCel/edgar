"""Extraction receipt schema and validation (M1A-1)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from edgar.domain.bundle import FilingBundle, FilingIdentity
from edgar.domain.report_key import report_input_payload
from edgar.domain.report_key import report_key as compute_report_key
from edgar.provenance import ImplementationIdentity
from edgar.storage.bundles import validate_bundle_integrity
from edgar.storage.objects import ObjectStore
from edgar.xbrl.config import SemanticConfig
from edgar.xbrl.source_records import EXTRACTOR_VERSION, SOURCE_RECORDS_SCHEMA_VERSION

RECEIPT_VERSION = "extraction-receipt-v1"


class ReceiptValidationError(ValueError):
    """Receipt binding or artifact verification failed."""


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

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BundleRef:
        return cls(
            descriptor_relative_path=str(data["descriptor_relative_path"]),
            descriptor_sha256=str(data["descriptor_sha256"]).lower(),
            manifest=dict(data["manifest"]),
        )


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
        impl_raw = data["implementation"]
        implementation = ImplementationIdentity(
            revision=impl_raw.get("revision"),
            tree_state=impl_raw.get("tree_state", "unknown"),
            dirty_tree_digest=impl_raw.get("dirty_tree_digest"),
        )
        return cls(
            receipt_version=str(data["receipt_version"]),
            bundle_ref=BundleRef.from_dict(data["bundle_ref"]),
            report_input=dict(data["report_input"]),
            semantic_config=dict(data["semantic_config"]),
            semantic_config_sha256=(
                str(data["semantic_config_sha256"]).lower()
                if data.get("semantic_config_sha256")
                else None
            ),
            extractor_version=str(data["extractor_version"]),
            source_records_schema_version=int(data["source_records_schema_version"]),
            worker_protocol_version=str(data["worker_protocol_version"]),
            arelle_version=str(data["arelle_version"]),
            implementation=implementation,
            dependency_lock_sha256=(
                str(data["dependency_lock_sha256"]).lower()
                if data.get("dependency_lock_sha256")
                else None
            ),
        )


def semantic_config_canonical_digest(config: Mapping[str, Any]) -> str:
    cfg = SemanticConfig.from_dict(config)
    payload = json.dumps(cfg.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_bundle_ref(
    *,
    data_root: Path,
    bundle_dir: Path,
    bundle: FilingBundle,
) -> BundleRef:
    descriptor = bundle_dir / "bundle.json"
    relative = descriptor.relative_to(data_root.resolve())
    raw = descriptor.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    return BundleRef(
        descriptor_relative_path=relative.as_posix(),
        descriptor_sha256=digest,
        manifest=bundle.to_dict(),
    )


@dataclass(frozen=True)
class PersistedReportRow:
    """Columns from ``source.xbrl_report`` plus owning filing identity."""

    report_input: dict[str, Any]
    report_key: str
    extractor_version: str
    arelle_version: str
    filing: FilingIdentity


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
    cfg = SemanticConfig.from_dict(receipt.semantic_config)
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
    bundle_filing = FilingIdentity.from_dict(manifest_filing)
    if not filing_identity_semantically_equal(bundle_filing, row.filing):
        raise ReceiptValidationError("bundle manifest filing does not match owning source.filing")


def verify_receipt_artifacts(
    receipt: ExtractionReceipt,
    *,
    data_root: Path,
    store: ObjectStore,
) -> None:
    """Descriptor bytes, manifest equivalence, and CAS artifact presence."""
    descriptor_path = (data_root / receipt.bundle_ref.descriptor_relative_path).resolve()
    if not descriptor_path.is_file():
        raise ReceiptValidationError(f"missing descriptor at {descriptor_path}")
    raw = descriptor_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != receipt.bundle_ref.descriptor_sha256:
        raise ReceiptValidationError("descriptor_sha256 mismatch")
    try:
        parsed = json.loads(raw.decode("utf-8"))
        bundle = FilingBundle.from_dict(parsed)
    except Exception as exc:
        raise ReceiptValidationError(f"descriptor is not a valid bundle: {exc}") from exc
    if bundle.to_dict() != receipt.bundle_ref.manifest:
        raise ReceiptValidationError("receipt manifest does not match descriptor content")
    validate_bundle_integrity(bundle, store)


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
    job_cfg = SemanticConfig.from_dict(job_semantic_config).to_dict()
    worker_cfg = SemanticConfig.from_dict(worker_effective_semantic_config).to_dict()
    receipt_cfg = SemanticConfig.from_dict(receipt_semantic_config).to_dict()
    if job_cfg != worker_cfg or job_cfg != receipt_cfg:
        raise ReceiptValidationError("semantic_config chain mismatch (job, worker, receipt)")


def receipt_verified(
    row: PersistedReportRow,
    receipt: ExtractionReceipt,
    *,
    data_root: Path,
    store: ObjectStore,
    require_clean_implementation: bool = False,
) -> bool:
    """Whether the receipt is publication-eligible under M1A rules."""
    try:
        validate_receipt_binding(row, receipt)
        verify_receipt_artifacts(receipt, data_root=data_root, store=store)
    except ReceiptValidationError:
        return False
    impl = receipt.implementation
    if impl.revision is None or impl.tree_state == "unknown":
        return False
    if require_clean_implementation and impl.tree_state != "clean":
        return False
    return receipt.dependency_lock_sha256 is not None


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
    "PersistedReportRow",
    "ReceiptValidationError",
    "RECEIPT_VERSION",
    "build_bundle_ref",
    "build_extraction_receipt",
    "filing_identity_semantically_equal",
    "receipt_verified",
    "semantic_config_canonical_digest",
    "validate_persisted_receipt_semantics",
    "validate_receipt_binding",
    "verify_extraction_config_chain",
    "verify_receipt_artifacts",
]
