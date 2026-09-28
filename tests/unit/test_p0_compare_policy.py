"""Unit tests for P0 v5→v6 baseline comparison policy."""

from __future__ import annotations

from collections import Counter

from edgar.p0_compare_policy import (
    compare_v6_filter,
    issue_delta,
    normalized_resource_sequence,
)


def _qname(ns: str, local: str) -> dict[str, str]:
    return {"namespace_uri": ns, "local_name": local}


def _declaration(ns: str, local: str) -> dict:
    return {"concept": _qname(ns, local), "period_type": "instant"}


def _label(ns: str, local: str, text: str, order: int) -> dict:
    return {
        "concept": _qname(ns, local),
        "text": text,
        "source_order": order,
        "link_role_uri": "http://example.com/role",
        "arcrole_uri": "http://www.xbrl.org/2003/arcrole/concept-label",
        "link_qname": _qname("http://www.xbrl.org/2003/linkbase", "labelLink"),
        "arc_qname": _qname("http://www.xbrl.org/2003/linkbase", "labelArc"),
    }


def test_issue_delta_multiplicity() -> None:
    added, removed = issue_delta(Counter({"A": 1}), Counter({"A": 2}))
    assert added == Counter({"A": 1})
    assert removed == Counter()
    added, removed = issue_delta(Counter({"A": 2}), Counter({"A": 1}))
    assert added == Counter()
    assert removed == Counter({"A": 1})
    added, removed = issue_delta(Counter({"A": 1}), Counter({"A": 1, "B": 1}))
    assert added == Counter({"B": 1})
    added, removed = issue_delta(Counter({"A": 1}), Counter({"A": 1}))
    assert added == Counter()
    assert removed == Counter()


def test_compare_v6_filter_stable() -> None:
    us = "http://fasb.org/us-gaap/2023"
    issuer = "http://issuer.example.com/2024"
    baseline = {
        "facts": [{"concept": _qname(us, "Used")}],
        "relationships": [],
        "dimensions": [],
        "declarations": [
            _declaration(us, "Used"),
            _declaration(us, "Unused"),
            _declaration(issuer, "Ext"),
        ],
        "concepts": [_qname(us, "Used"), _qname(us, "Unused"), _qname(issuer, "Ext")],
        "labels": [
            _label(us, "Used", "a", 0),
            _label(us, "Unused", "b", 1),
            _label(issuer, "Ext", "c", 2),
        ],
        "references": [],
    }
    keep_decl = [_declaration(us, "Used"), _declaration(issuer, "Ext")]
    keep_concepts = [_qname(us, "Used"), _qname(issuer, "Ext")]
    keep_labels = [
        _label(us, "Used", "a", 0),
        _label(issuer, "Ext", "c", 1),
    ]
    current = {
        "declarations": keep_decl,
        "concepts": keep_concepts,
        "labels": keep_labels,
        "references": [],
    }
    result = compare_v6_filter(baseline, current)
    assert result.errors == ()
    assert result.issuer_only == 1


def test_compare_v6_filter_omitted_eligible_label_fails() -> None:
    us = "http://fasb.org/us-gaap/2023"
    baseline = {
        "facts": [{"concept": _qname(us, "A")}, {"concept": _qname(us, "B")}],
        "relationships": [],
        "dimensions": [],
        "declarations": [_declaration(us, "A"), _declaration(us, "B")],
        "concepts": [_qname(us, "A"), _qname(us, "B")],
        "labels": [_label(us, "A", "a", 0), _label(us, "B", "b", 1)],
        "references": [],
    }
    current = {
        "declarations": [_declaration(us, "A"), _declaration(us, "B")],
        "concepts": [_qname(us, "A"), _qname(us, "B")],
        "labels": [_label(us, "A", "a", 0)],
        "references": [],
    }
    result = compare_v6_filter(baseline, current)
    assert any("labels" in err for err in result.errors)


def test_compare_v6_filter_extra_resource_fails() -> None:
    us = "http://fasb.org/us-gaap/2023"
    baseline = {
        "facts": [{"concept": _qname(us, "A")}],
        "relationships": [],
        "dimensions": [],
        "declarations": [_declaration(us, "A")],
        "concepts": [_qname(us, "A")],
        "labels": [_label(us, "A", "a", 0)],
        "references": [],
    }
    current = {
        "declarations": [_declaration(us, "A")],
        "concepts": [_qname(us, "A")],
        "labels": [_label(us, "A", "a", 0), _label(us, "A", "extra", 1)],
        "references": [],
    }
    result = compare_v6_filter(baseline, current)
    assert result.errors


def test_normalized_resource_sequence_preserves_duplicates() -> None:
    records = [
        {"concept": _qname("http://a", "X"), "text": "1", "source_order": 0},
        {"concept": _qname("http://a", "X"), "text": "1", "source_order": 1},
    ]
    normed = normalized_resource_sequence(records)
    assert len(normed) == 2
    assert normed[0] == normed[1]
