"""Unit tests for regulatory section extraction."""

from __future__ import annotations

from edgar.parsing.html import parse_html_document
from edgar.parsing.sections import extract_filing_sections
from tests.helpers.document_fixtures import (
    AMBIGUOUS_END_HTML,
    LAYOUT_TABLE_ITEMS_HTML,
    PARTIAL_10KA_HTML,
    RICH_10K_HTML,
    RICH_10Q_HTML,
    SAME_ORDINAL_COLLAPSE_HTML,
)


def _section_map(sections):
    return {s.section_key: s for s in sections}


def test_10k_toc_rejected_body_selected() -> None:
    parsed = parse_html_document(RICH_10K_HTML)
    sections, issues, status, terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert "part_1.item_1.business" in by_key
    assert "part_2.item_8.financial_statements" in by_key
    item8 = by_key["part_2.item_8.financial_statements"]
    assert terminal is not None
    item9 = next(
        b.ordinal for b in parsed.blocks if b.text and b.text.upper().startswith("ITEM 9.")
    )
    assert item8.end_block_ordinal_exclusive == item9
    # Item 8 must not include SIGNATURES text
    body = " ".join(
        b.text or ""
        for b in parsed.blocks
        if item8.start_block_ordinal <= b.ordinal < item8.end_block_ordinal_exclusive
    )
    assert "SIGNATURES" not in body
    assert status in {"complete", "incomplete"}


def test_sparse_vocabulary_item_1c_ends_at_item_2() -> None:
    parsed = parse_html_document(RICH_10K_HTML)
    sections, _issues, _status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    item_1c = by_key["part_1.item_1c.cybersecurity"]
    # Find Item 2 ordinal
    item2 = next(
        b.ordinal for b in parsed.blocks if b.text and b.text.upper().startswith("ITEM 2.")
    )
    assert item_1c.end_block_ordinal_exclusive == item2


def test_10q_part_item_reset() -> None:
    parsed = parse_html_document(RICH_10Q_HTML)
    sections, _issues, _status, _terminal = extract_filing_sections(
        parsed, form_type="10-Q", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert "part_1.item_1.financial_statements" in by_key
    assert "part_2.item_1.legal_proceedings" in by_key
    assert (
        by_key["part_1.item_1.financial_statements"].start_block_ordinal
        < by_key["part_2.item_1.legal_proceedings"].start_block_ordinal
    )


def test_partial_amendment_no_missing_spam() -> None:
    parsed = parse_html_document(PARTIAL_10KA_HTML)
    sections, issues, _status, _terminal = extract_filing_sections(
        parsed, form_type="10-K/A", extract_regulatory_sections=True
    )
    assert any(s.section_key == "part_1.item_1a.risk_factors" for s in sections)
    assert not any(i.code == "SECTION_NOT_FOUND" for i in issues)


def test_attachment_skips_sections() -> None:
    parsed = parse_html_document(RICH_10K_HTML)
    sections, issues, status, terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=False
    )
    assert sections == []
    assert issues == []
    assert status == "complete"
    assert terminal is None


def test_ambiguous_intervening_end_unresolved() -> None:
    parsed = parse_html_document(AMBIGUOUS_END_HTML)
    sections, issues, status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    # Item 1C end depends on ambiguous Item 2
    assert "part_1.item_1c.cybersecurity" not in by_key
    assert any(i.code == "SECTION_BOUNDARY_UNRESOLVED" for i in issues)
    assert status == "incomplete"


def test_same_ordinal_collapse() -> None:
    parsed = parse_html_document(SAME_ORDINAL_COLLAPSE_HTML)
    sections, issues, status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    # Cannot represent two boundaries on one ordinal as a range
    assert "part_1.item_1.business" not in _section_map(sections) or any(
        i.code == "SECTION_BOUNDARY_UNRESOLVED" for i in issues
    )


def test_layout_table_sections_addressable() -> None:
    parsed = parse_html_document(LAYOUT_TABLE_ITEMS_HTML)
    sections, _issues, _status, terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert "part_2.item_7.mda" in by_key
    assert "part_2.item_7a.market_risk" in by_key
    assert terminal is not None
    assert (
        by_key["part_2.item_7.mda"].end_block_ordinal_exclusive
        == by_key["part_2.item_7a.market_risk"].start_block_ordinal
    )
