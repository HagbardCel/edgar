"""Content-addressed object store for spike evidence."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from spike_lib.hashing import sha256_hex


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
                raise ValueError(
                    f"content-address collision for {digest}: existing bytes differ"
                )
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

    def put_file(self, source: Path) -> ContentObject:
        return self.put_bytes(source.read_bytes())

    def open_bytes(self, digest: str) -> bytes:
        return self.path_for(digest).read_bytes()
