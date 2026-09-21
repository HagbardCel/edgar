"""Implementation and dependency-lock identity for extraction receipts (M1A)."""

from __future__ import annotations

import hashlib
import os
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _imported_edgar_init() -> Path:
    import edgar

    init_path = Path(edgar.__file__).resolve()
    if init_path.name != "__init__.py":
        raise RuntimeError(f"unexpected edgar package entry: {init_path}")
    return init_path


def _source_tree_matches_running_package(candidate: Path) -> bool:
    """True when candidate/src/edgar/__init__.py is the running package."""
    expected = (candidate / "src" / "edgar" / "__init__.py").resolve()
    try:
        return expected.is_file() and expected.samefile(_imported_edgar_init())
    except OSError:
        return False


def resolve_edgar_repo_root(*, explicit: Path | None = None) -> Path | None:
    """Resolve a trusted EDGAR source checkout for the running package.

    Accepts a candidate only when ``candidate/src/edgar/__init__.py`` resolves
    to the same file as the imported ``edgar`` package. ``EDGAR_REPO_ROOT`` (or
    ``explicit``) must pass the same check; otherwise returns ``None``.
    """
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        return candidate if _source_tree_matches_running_package(candidate) else None

    env = os.environ.get("EDGAR_REPO_ROOT", "").strip()
    if env:
        candidate = Path(env).expanduser().resolve()
        return candidate if _source_tree_matches_running_package(candidate) else None

    try:
        start = _imported_edgar_init().parent
    except Exception:  # noqa: BLE001 — unknown when package layout is unexpected
        return None
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").is_file() and _source_tree_matches_running_package(parent):
            return parent
    return None


def gather_implementation_identity(repo_root: Path | None = None) -> ImplementationIdentity:
    """Best-effort git identity; unknown when not in a trusted EDGAR checkout."""
    root = (
        resolve_edgar_repo_root(explicit=repo_root)
        if repo_root is not None
        else (resolve_edgar_repo_root())
    )
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
        porcelain = status.stdout.strip()
        dirty = bool(porcelain)
    except (OSError, subprocess.CalledProcessError):
        return ImplementationIdentity(
            revision=revision,
            tree_state="unknown",
            dirty_tree_digest=None,
        )
    if not dirty:
        return ImplementationIdentity(revision=revision, tree_state="clean", dirty_tree_digest=None)

    # Porcelain: "??" means untracked. Decline an exact digest when present.
    has_untracked = any(line.startswith("??") for line in porcelain.splitlines() if line)
    if has_untracked:
        return ImplementationIdentity(
            revision=revision,
            tree_state="dirty",
            dirty_tree_digest=None,
        )
    try:
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        dirty_digest = hashlib.sha256(diff.stdout).hexdigest()
    except (OSError, subprocess.CalledProcessError):
        dirty_digest = None
    return ImplementationIdentity(
        revision=revision,
        tree_state="dirty",
        dirty_tree_digest=dirty_digest,
    )


def gather_dependency_lock_sha256(repo_root: Path | None = None) -> str | None:
    """SHA-256 of ``uv.lock`` when present at a trusted repository root."""
    root = (
        resolve_edgar_repo_root(explicit=repo_root)
        if repo_root is not None
        else (resolve_edgar_repo_root())
    )
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
    "resolve_edgar_repo_root",
]
