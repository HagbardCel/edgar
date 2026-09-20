"""Implementation and dependency-lock identity for extraction receipts (M1A)."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TreeState = Literal["clean", "dirty", "unknown"]


@dataclass(frozen=True)
class ImplementationIdentity:
    revision: str | None
    tree_state: TreeState
    dirty_tree_digest: str | None = None


def _repo_root(start: Path | None = None) -> Path | None:
    cursor = (start or Path.cwd()).resolve()
    for parent in (cursor, *cursor.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gather_implementation_identity(repo_root: Path | None = None) -> ImplementationIdentity:
    """Best-effort git identity; unknown when not in a git checkout."""
    root = repo_root or _repo_root()
    if root is None:
        return ImplementationIdentity(revision=None, tree_state="unknown", dirty_tree_digest=None)
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        revision = rev.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return ImplementationIdentity(revision=None, tree_state="unknown", dirty_tree_digest=None)
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        dirty = bool(status.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return ImplementationIdentity(
            revision=revision,
            tree_state="unknown",
            dirty_tree_digest=None,
        )
    dirty_digest: str | None = None
    if dirty:
        try:
            diff = subprocess.run(
                ["git", "diff", "--no-ext-diff", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            dirty_digest = hashlib.sha256(diff.stdout).hexdigest()
        except (OSError, subprocess.CalledProcessError):
            dirty_digest = None
    return ImplementationIdentity(
        revision=revision,
        tree_state="dirty" if dirty else "clean",
        dirty_tree_digest=dirty_digest,
    )


def gather_dependency_lock_sha256(repo_root: Path | None = None) -> str | None:
    """SHA-256 of ``uv.lock`` when present at the repository root."""
    root = repo_root or _repo_root()
    if root is None:
        return None
    lock_path = root / "uv.lock"
    if not lock_path.is_file():
        return None
    return _sha256_file(lock_path)


__all__ = [
    "ImplementationIdentity",
    "TreeState",
    "gather_dependency_lock_sha256",
    "gather_implementation_identity",
]
