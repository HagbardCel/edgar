"""Content-addressed object store and atomic writers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SizeLimitExceeded(RuntimeError):
    """Raised when a streamed write exceeds the configured byte limit."""


@dataclass(frozen=True)
class StoredObject:
    sha256: str
    byte_size: int
    storage_path: Path


class ObjectStore:
    """Content-addressed store at ``{root}/objects/sha256/{aa}/{sha256}``."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.objects_dir = data_root / "objects" / "sha256"
        self.objects_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, digest: str) -> Path:
        digest = digest.lower()
        return self.objects_dir / digest[:2] / digest

    def put_bytes(self, data: bytes) -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        dest = self.path_for(digest)
        if dest.exists():
            existing = dest.read_bytes()
            if existing != data:
                raise ValueError(f"content-address collision for {digest}: existing bytes differ")
            return StoredObject(sha256=digest, byte_size=len(data), storage_path=dest)

        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{digest}.", suffix=".tmp")
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, dest)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise
        return StoredObject(sha256=digest, byte_size=len(data), storage_path=dest)

    def put_stream(self, chunks: Iterable[bytes], *, max_bytes: int) -> StoredObject:
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.objects_dir, prefix=".stream.", suffix=".tmp")
        tmp_path = Path(tmp_name)
        digest = hashlib.sha256()
        total = 0
        try:
            with os.fdopen(fd, "wb") as handle:
                for chunk in chunks:
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise SizeLimitExceeded(f"streamed response exceeded max_bytes={max_bytes}")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            sha = digest.hexdigest()
            dest = self.path_for(sha)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                existing = dest.read_bytes()
                candidate = tmp_path.read_bytes()
                if existing != candidate:
                    raise ValueError(f"content-address collision for {sha}: existing bytes differ")
                tmp_path.unlink(missing_ok=True)
                return StoredObject(sha256=sha, byte_size=total, storage_path=dest)
            os.replace(tmp_path, dest)
            return StoredObject(sha256=sha, byte_size=total, storage_path=dest)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def open_bytes(self, digest: str) -> bytes:
        path = self.path_for(digest)
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest.lower():
            raise ValueError(f"CAS integrity failure for {digest}: got {actual}")
        return data

    def exists(self, digest: str) -> bool:
        return self.path_for(digest).is_file()


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        # Parent directory fsync for crash durability.
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def write_json_atomic(
    path: Path,
    payload: Mapping[str, Any] | list[Any],
    *,
    indent: int = 2,
) -> bytes:
    data = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=indent).encode("utf-8")
        + b"\n"
    )
    write_bytes_atomic(path, data)
    return data
