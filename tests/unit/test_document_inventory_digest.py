"""Canonical document-inventory digest used by corpus Layer A."""

from __future__ import annotations

from edgar.corpus_acceptance import canonical_document_inventory_digest


def test_inventory_digest_is_order_independent_and_stable() -> None:
    a = {("b.xml", "aa" * 32, 2), ("a.xml", "bb" * 32, 1)}
    b = {("a.xml", "bb" * 32, 1), ("b.xml", "aa" * 32, 2)}
    digest = canonical_document_inventory_digest(a)
    assert digest == canonical_document_inventory_digest(b)
    assert len(digest) == 64
    extra = {("a.xml", "bb" * 32, 1), ("b.xml", "aa" * 32, 2), ("c.xml", "cc" * 32, 3)}
    assert canonical_document_inventory_digest(extra) != digest
