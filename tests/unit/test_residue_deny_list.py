"""Executable residue must not reintroduce Phase-1 projection lifecycle paths.

This is intentionally a substring scan of comments and docstrings as well as
code, so later changes cannot "fix" the gate by switching to AST-only
inspection.
"""

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
    "SemanticProjectionService",
    "DocumentProjectionService",
    "extract_semantic_projection",
    "semantic_projection",
    "document_projection",
    "edgar.projection",
)

_SCAN_ROOTS = (
    _REPO_ROOT / "src",
    _REPO_ROOT / "tests",
    _REPO_ROOT / "scripts",
)

# Path (relative to repo) → tokens this file may mention. Only historical
# table-name literals in the clean-head gate, plus this module's own list.
_TOKEN_EXEMPTIONS: dict[str, frozenset[str]] = {
    "tests/unit/test_residue_deny_list.py": frozenset(_DENY_TOKENS),
    "tests/integration/test_v2_clean_head.py": frozenset(
        {
            "semantic_projection",
            "semantic_projection_attempt",
            "document_projection",
            "document_projection_attempt",
        }
    ),
}


def _should_scan(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    return "/spikes/" not in str(path)


def test_residue_deny_list_absent_from_live_python() -> None:
    hits: list[str] = []
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if not _should_scan(path):
                continue
            rel = str(path.relative_to(_REPO_ROOT))
            allowed = _TOKEN_EXEMPTIONS.get(rel, frozenset())
            content = path.read_text(encoding="utf-8")
            for token in _DENY_TOKENS:
                if token in allowed:
                    continue
                if token in content:
                    hits.append(f"{rel}: {token}")
    assert hits == [], "Phase-1 residue tokens found:\n" + "\n".join(hits)
