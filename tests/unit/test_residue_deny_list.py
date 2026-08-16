"""Executable residue must not reintroduce Phase-1 projection lifecycle paths."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Tokens that must not appear in live executable surfaces (src/, tests/, scripts/
# excluding ADR historical prose and this deny-list itself).
_DENY_TOKENS = (
    "SemanticProjectionData",
    "semantic_payload",
    "source_adapt",
    "semantic_config_fingerprint",
    "SEMANTIC_PROJECTION_VERSION",
    "run_offline_semantic",
    "project_semantic",
    "project_document",
    "semantic_projection_attempt",
    "document_projection_attempt",
    "verified_reuse",
    "projection_compat",
    "v1_repository_adapter",
)

_SCAN_ROOTS = (
    _REPO_ROOT / "src",
    _REPO_ROOT / "tests",
    _REPO_ROOT / "scripts",
)

_ALLOW_PATH_SUBSTRINGS = (
    "/tests/unit/test_residue_deny_list.py",
    "/tests/integration/test_v2_clean_head.py",
)


def _should_scan(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    text = str(path)
    if any(allow in text for allow in _ALLOW_PATH_SUBSTRINGS):
        return False
    return "/spikes/" not in text


def test_residue_deny_list_absent_from_live_python() -> None:
    hits: list[str] = []
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if not _should_scan(path):
                continue
            content = path.read_text(encoding="utf-8")
            for token in _DENY_TOKENS:
                if token in content:
                    rel = path.relative_to(_REPO_ROOT)
                    hits.append(f"{rel}: {token}")
    assert hits == [], "Phase-1 residue tokens found:\n" + "\n".join(hits)
