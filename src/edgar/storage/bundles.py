"""Filesystem FilingBundle publication with accession-scoped locking."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock

from edgar.domain.bundle import FilingBundle, bundles_equivalent
from edgar.storage.objects import ObjectStore, write_json_atomic


class BundleStorageError(RuntimeError):
    """Raised for publication / reuse integrity failures."""


@dataclass(frozen=True)
class PublishResult:
    bundle: FilingBundle
    bundle_dir: Path
    opaque_id: str
    reused: bool


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

    def list_published(self, cik: str, accession: str) -> list[tuple[Path, FilingBundle]]:
        root = self._accession_dir(cik, accession)
        if not root.is_dir():
            return []
        found: list[tuple[Path, FilingBundle]] = []
        for child in sorted(root.iterdir()):
            descriptor = child / "bundle.json"
            if not descriptor.is_file():
                continue
            try:
                data = json.loads(descriptor.read_text(encoding="utf-8"))
                bundle = FilingBundle.from_dict(data)
            except Exception as exc:
                raise BundleStorageError(
                    f"corrupt published bundle descriptor at {descriptor}: {exc}"
                ) from exc
            self._revalidate(bundle)
            found.append((child, bundle))
        return found

    def _revalidate(self, bundle: FilingBundle) -> None:
        for artifact in bundle.artifacts:
            if not self.store.exists(artifact.content.sha256):
                raise BundleStorageError(
                    f"missing CAS object {artifact.content.sha256} for {artifact.logical_path}"
                )
            data = self.store.open_bytes(artifact.content.sha256)
            if len(data) != artifact.content.byte_size:
                raise BundleStorageError(
                    f"CAS size mismatch for {artifact.logical_path}: "
                    f"{len(data)} != {artifact.content.byte_size}"
                )

    def publish(self, bundle: FilingBundle) -> PublishResult:
        cik = bundle.filing.cik
        accession = bundle.filing.accession
        lock = FileLock(str(self._lock_path(cik, accession)))
        with lock:
            for path, existing in self.list_published(cik, accession):
                if bundles_equivalent(existing, bundle):
                    self._revalidate(existing)
                    return PublishResult(
                        bundle=existing,
                        bundle_dir=path,
                        opaque_id=path.name,
                        reused=True,
                    )
            opaque_id = uuid.uuid4().hex
            final_dir = self._accession_dir(cik, accession) / opaque_id
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            staging = final_dir.parent / f".staging-{opaque_id}"
            if staging.exists():
                raise BundleStorageError(f"staging directory already exists: {staging}")
            staging.mkdir(parents=True)
            try:
                write_json_atomic(staging / "bundle.json", bundle.to_dict())
                staging.rename(final_dir)
                # Parent dir fsync after rename (write_json_atomic already fsynced file+dir
                # of staging; fsync accession parent for visibility durability).
                import os

                dir_fd = os.open(str(final_dir.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except Exception:
                if staging.exists():
                    for child in staging.iterdir():
                        child.unlink()
                    staging.rmdir()
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
        self._revalidate(bundle)
        return bundle
