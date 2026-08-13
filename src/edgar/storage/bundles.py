"""Filesystem FilingBundle publication with accession-scoped locking."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock

from edgar.domain.bundle import FilingBundle, bundles_equivalent
from edgar.domain.identifiers import (
    assert_path_under,
    validate_accession,
    validate_cik,
    validate_uuid4_hex,
)
from edgar.domain.validation import BundleStructureError, validate_bundle_structure
from edgar.storage.objects import ObjectStore, write_json_atomic


class BundleStorageError(RuntimeError):
    """Raised for publication / reuse integrity failures."""


@dataclass(frozen=True)
class PublishResult:
    bundle: FilingBundle
    bundle_dir: Path
    opaque_id: str
    reused: bool


def validate_published_bundle_path(data_root: Path, bundle_dir: Path) -> tuple[str, str, str]:
    """Validate ``bundles/{cik}/{accession}/{opaque_id}/`` under ``data_root``.

    Returns ``(opaque_id, cik, accession)``.
    """
    bundles_root = (data_root / "bundles").resolve()
    resolved = assert_path_under(bundle_dir, bundles_root)
    relative = resolved.relative_to(bundles_root)
    if len(relative.parts) != 3:
        raise ValueError(
            "bundle_dir must be bundles/{cik}/{accession}/{opaque_id}/ "
            f"under {bundles_root}, got {relative}"
        )
    cik, accession, opaque_id = relative.parts
    canonical_cik = validate_cik(cik)
    if canonical_cik != cik:
        raise ValueError(f"noncanonical CIK in publication path: {cik!r}")
    validate_accession(accession)
    validate_uuid4_hex(opaque_id)
    return opaque_id, cik, accession


def _is_uuid4_hex(name: str) -> bool:
    try:
        validate_uuid4_hex(name)
    except ValueError:
        return False
    return True


def validate_bundle_integrity(bundle: FilingBundle, store: ObjectStore) -> None:
    """Structural validation plus CAS existence / SHA / size checks.

    Hashes each unique content SHA once per call.
    """
    try:
        validate_bundle_structure(bundle)
    except BundleStructureError as exc:
        raise BundleStorageError(str(exc)) from exc

    measured: dict[str, tuple[str, int]] = {}
    for artifact in bundle.artifacts:
        digest = artifact.content.sha256
        if digest not in measured:
            if not store.exists(digest):
                raise BundleStorageError(f"missing CAS object {digest} for {artifact.logical_path}")
            try:
                data = store.open_bytes(digest)
            except (OSError, ValueError) as exc:
                raise BundleStorageError(
                    f"cannot validate CAS object {digest} for {artifact.logical_path}: {exc}"
                ) from exc
            measured[digest] = (digest, len(data))
        _sha, size = measured[digest]
        if size != artifact.content.byte_size:
            raise BundleStorageError(
                f"CAS size mismatch for {artifact.logical_path}: "
                f"{size} != {artifact.content.byte_size}"
            )


class BundleRepository:
    def __init__(self, data_root: Path, store: ObjectStore) -> None:
        self.data_root = data_root
        self.store = store
        self.bundles_root = data_root / "bundles"
        self.locks_root = data_root / "locks"

    def _accession_dir(self, cik: str, accession: str) -> Path:
        return self.bundles_root / cik / accession

    def _lock_path(self, cik: str, accession: str) -> Path:
        path = self.locks_root / cik / f"{accession}.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _clean_orphan_staging(self, root: Path) -> None:
        for child in list(root.iterdir()):
            if child.is_dir() and child.name.startswith(".staging-"):
                shutil.rmtree(child, ignore_errors=True)

    def list_published(self, cik: str, accession: str) -> list[tuple[Path, FilingBundle]]:
        root = self._accession_dir(cik, accession)
        if not root.is_dir():
            return []
        found: list[tuple[Path, FilingBundle]] = []
        for child in sorted(root.iterdir()):
            if child.is_file():
                # Noise such as .DS_Store
                continue
            if not child.is_dir():
                continue
            if child.name.startswith(".staging-"):
                continue
            if not _is_uuid4_hex(child.name):
                raise BundleStorageError(
                    f"unexpected directory under published accession path: {child}"
                )
            descriptor = child / "bundle.json"
            if not descriptor.is_file():
                raise BundleStorageError(
                    f"canonical publish directory missing bundle.json: {child}"
                )
            try:
                data = json.loads(descriptor.read_text(encoding="utf-8"))
                bundle = FilingBundle.from_dict(data)
            except Exception as exc:
                raise BundleStorageError(
                    f"corrupt published bundle descriptor at {descriptor}: {exc}"
                ) from exc
            if bundle.filing.cik != cik or bundle.filing.accession != accession:
                raise BundleStorageError(
                    f"bundle filing identity does not match directory path {child}: "
                    f"{bundle.filing.cik}/{bundle.filing.accession}"
                )
            validate_bundle_integrity(bundle, self.store)
            found.append((child, bundle))
        return found

    def publish(self, bundle: FilingBundle) -> PublishResult:
        validate_bundle_structure(bundle)
        cik = bundle.filing.cik
        accession = bundle.filing.accession
        lock = FileLock(str(self._lock_path(cik, accession)))
        with lock:
            root = self._accession_dir(cik, accession)
            root.mkdir(parents=True, exist_ok=True)
            self._clean_orphan_staging(root)
            for path, existing in self.list_published(cik, accession):
                if bundles_equivalent(existing, bundle):
                    # Already fully validated during list_published.
                    return PublishResult(
                        bundle=existing,
                        bundle_dir=path,
                        opaque_id=path.name,
                        reused=True,
                    )
            # Full CAS validation once at publication boundary.
            validate_bundle_integrity(bundle, self.store)
            opaque_id = uuid.uuid4().hex
            final_dir = root / opaque_id
            staging = root / f".staging-{opaque_id}"
            if staging.exists():
                raise BundleStorageError(f"staging directory already exists: {staging}")
            staging.mkdir(parents=True)
            try:
                write_json_atomic(staging / "bundle.json", bundle.to_dict())
                staging.rename(final_dir)
                import os

                dir_fd = os.open(str(final_dir.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                raise
            return PublishResult(
                bundle=bundle,
                bundle_dir=final_dir,
                opaque_id=opaque_id,
                reused=False,
            )

    def load(self, bundle_dir: Path) -> FilingBundle:
        data = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
        bundle = FilingBundle.from_dict(data)
        # Path components when under bundles/{cik}/{accession}/{uuid}
        parts = bundle_dir.resolve().parts
        if len(parts) >= 3:
            accession = parts[-2]
            cik = parts[-3]
            if bundle.filing.cik != cik or bundle.filing.accession != accession:
                raise BundleStorageError(
                    f"bundle filing identity does not match directory path {bundle_dir}"
                )
        validate_bundle_integrity(bundle, self.store)
        return bundle
