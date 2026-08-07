"""Unit tests for semantic-run-v1 identity and non-circular hashing (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
sys.path.insert(0, str(SPIKE_DIR))

from spike_lib.semantic import (  # noqa: E402
    build_semantic_run_identity,
    semantic_run_hash,
    strict_comparison_projection,
)


def _snapshot(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "concept_count": 10,
        "context_count": 2,
        "unit_count": 1,
        "fact_count": 20,
        "relationship_counts": {"presentation": 3},
        "resource_relationship_counts": {"concept_label": 4},
        "concept_relationship_occurrence_hash": "a" * 64,
        "resource_relationship_occurrence_hash": "b" * 64,
        "documents": [],
        "edges": [],
        "synthetic_document_set_hash": "c" * 64,
        "synthetic_document_count": 0,
        "synthetic_edge_set_hash": "d" * 64,
        "synthetic_edge_count": 0,
        "entry_points": ["https://example.com/a.htm"],
        "unresolved_uris": [],
        "unsupported_inventory": {},
        "extraction": {"extraction_complete": True},
        "error_summary": {"unallowlisted_warning_count": 7},
    }
    base.update(overrides)
    return base


def _criteria(repeat_passed: bool = False) -> list[dict[str, object]]:
    return [
        {"id": i, "name": f"c{i}", "passed": True, "detail": {"x": i}}
        for i in range(1, 11)
        if i != 9 or repeat_passed
    ]


def _compare() -> dict[str, object]:
    return {
        "strict_diffs": [],
        "allowed_diffs": [],
        "unexplained_diffs": [],
        "strict_ok": True,
        "criterion_10_ok": True,
    }


def _identity(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "cik": "0001065088",
        "accession": "0001065088-24-000036",
        "payload_hash": "1" * 64,
        "closure_hash": "2" * 64,
        "engine": {"name": "arelle", "version": "9.9.9", "config": {"work_offline": True}},
        "online_snapshot": _snapshot(),
        "offline_snapshot": _snapshot(),
        "strict_comparison": strict_comparison_projection(_compare()),
        "criteria": _criteria(),
    }
    kwargs.update(overrides)
    return build_semantic_run_identity(**kwargs)  # type: ignore[arg-type]


def test_semantic_hash_stable_and_excludes_criterion_9() -> None:
    h1 = semantic_run_hash(_identity())
    h2 = semantic_run_hash(_identity())
    assert h1 == h2
    # Criterion 9 (repeat) must not be part of the hashed identity.
    h3 = semantic_run_hash(_identity(criteria=_criteria(repeat_passed=True)))
    assert h1 == h3


def test_semantic_hash_changes_with_relationships() -> None:
    h1 = semantic_run_hash(_identity())
    h2 = semantic_run_hash(
        _identity(online_snapshot=_snapshot(concept_relationship_occurrence_hash="e" * 64))
    )
    assert h1 != h2


def test_semantic_hash_excludes_raw_warnings() -> None:
    h1 = semantic_run_hash(_identity())
    h2 = semantic_run_hash(
        _identity(online_snapshot=_snapshot(error_summary={"unallowlisted_warning_count": 99}))
    )
    assert h1 == h2


def test_semantic_hash_includes_criteria_outcomes() -> None:
    criteria = _criteria()
    criteria[0] = {"id": 1, "name": "c1", "passed": False, "detail": {"x": 1}}
    h1 = semantic_run_hash(_identity())
    h2 = semantic_run_hash(_identity(criteria=criteria))
    assert h1 != h2


def test_strict_comparison_projection_stable() -> None:
    compare = _compare()
    projection = strict_comparison_projection(compare)  # type: ignore[arg-type]
    assert set(projection) == {
        "strict_diffs",
        "allowed_diffs",
        "unexplained_diffs",
        "strict_ok",
        "criterion_10_ok",
    }
