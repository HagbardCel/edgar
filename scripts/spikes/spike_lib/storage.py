"""Content-addressed object store and atomic evidence writers for spikes."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spike_lib.hashing import sha256_hex
from spike_lib.sec import SizeLimitExceeded


@dataclass(frozen=True)
class ContentObject:
    sha256: str
    byte_size: int
    storage_path: Path


class ObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects_dir = root / "objects" / "sha256"
        self.objects_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, digest: str) -> Path:
        digest = digest.lower()
        return self.objects_dir / digest[:2] / digest

    def put_bytes(self, data: bytes) -> ContentObject:
        digest = sha256_hex(data)
        dest = self.path_for(digest)
        if dest.exists():
            existing = dest.read_bytes()
            if existing != data:
                raise ValueError(f"content-address collision for {digest}: existing bytes differ")
            return ContentObject(sha256=digest, byte_size=len(data), storage_path=dest)

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
        return ContentObject(sha256=digest, byte_size=len(data), storage_path=dest)

    def put_stream(
        self,
        chunks: Iterable[bytes],
        *,
        max_bytes: int,
    ) -> ContentObject:
        """Write streamed chunks to a temp file with incremental SHA-256.

        Aborts and deletes the temp file if max_bytes is exceeded.
        """
        import hashlib

        self.objects_dir.mkdir(parents=True, exist_ok=True)
        # Temp lives under objects_dir so rename stays on the same filesystem.
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
                with tmp_path.open("rb") as handle:
                    candidate = handle.read()
                if existing != candidate:
                    raise ValueError(f"content-address collision for {sha}: existing bytes differ")
                tmp_path.unlink(missing_ok=True)
                return ContentObject(sha256=sha, byte_size=total, storage_path=dest)
            os.replace(tmp_path, dest)
            return ContentObject(sha256=sha, byte_size=total, storage_path=dest)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def put_file(self, source: Path) -> ContentObject:
        return self.put_bytes(source.read_bytes())

    def open_bytes(self, digest: str) -> bytes:
        return self.path_for(digest).read_bytes()

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


def write_text_atomic(path: Path, text: str) -> bytes:
    data = text.encode("utf-8")
    write_bytes_atomic(path, data)
    return data
