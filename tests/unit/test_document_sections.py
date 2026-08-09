"""Unit tests for regulatory section extraction."""

from __future__ import annotations

from edgar.parsing.html import parse_html_document
from edgar.parsing.sections import (
    BODY_SELECTION_BASELINE,
    SCORE_GAP,
    _assign_item_parts,
    _Candidate,
    _global_monotonic_dp,
    _RawOccurrence,
    extract_filing_sections,
)
from tests.helpers.document_fixtures import (
    ADVERSARIAL_GLOBAL_HTML,
    AMBIGUOUS_END_HTML,
    COMPACT_TOC_BODY_HTML,
    DISTANT_LINK_HEAVY_TOC_CLUSTER_HTML,
    INTERVENING_COLLAPSE_HTML,
    LAYOUT_TABLE_ITEMS_HTML,
    LAYOUT_TABLE_SIGNATURES_HTML,
    MISSING_INTERMEDIATE_HTML,
    NO_TERMINAL_END_HTML,
    ORDINARY_MISSING_START_HTML,
    PART_I_ONLY_RESET_10Q_HTML,
    PARTIAL_10KA_HTML,
    PLAIN_SHORT_ITEM_HTML,
    PROSE_CROSSREF_10Q_HTML,
    RESOLVED_PART_II_DESPITE_AMB_PART_I_HTML,
    RICH_10K_HTML,
    RICH_10Q_HTML,
    SAME_ORDINAL_COLLAPSE_HTML,
    TOC_ONLY_HTML,
    TOC_PART_II_NOT_BODY_HTML,
    WEAK_CANDIDATE_HTML,
)


def _section_map(sections):
    return {s.section_key: s for s in sections}


def _ord(parsed, prefix: str) -> int:
    return next(
        b.ordinal for b in parsed.blocks if b.text and b.text.upper().startswith(prefix.upper())
    )


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


def test_prose_crossref_does_not_flip_part() -> None:
    parsed = parse_html_document(PROSE_CROSSREF_10Q_HTML)
    sections, _issues, _status, _terminal = extract_filing_sections(
        parsed, form_type="10-Q", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert "part_1.item_2.mda" in by_key
    assert by_key["part_1.item_2.mda"].start_block_ordinal == _ord(parsed, "Item 2. Management")


def test_prose_see_item_not_candidate() -> None:
    html = b"""<html><body>
    <h2>Item 1. Business</h2>
    <p>See Item 7 below.</p>
    <h2>Item 7. MD&amp;A</h2>
    <p>MD&amp;A.</p>
    <h2>Item 8. Financial Statements</h2>
    <p>FS.</p>
    <h2>SIGNATURES</h2>
    </body></html>"""
    parsed = parse_html_document(html)
    sections, _issues, _status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert by_key["part_2.item_7.mda"].start_block_ordinal == _ord(parsed, "Item 7. MD")


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
    assert "part_1.item_1c.cybersecurity" not in by_key
    assert any(i.code == "SECTION_BOUNDARY_UNRESOLVED" for i in issues)
    assert status == "incomplete"


def test_same_ordinal_collapse() -> None:
    parsed = parse_html_document(SAME_ORDINAL_COLLAPSE_HTML)
    sections, issues, status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    assert "part_1.item_1.business" not in _section_map(sections)
    assert any(
        i.code == "SECTION_BOUNDARY_UNRESOLVED"
        and i.context.get("reason") == "same_ordinal_collapse"
        for i in issues
    )
    assert status == "incomplete"


def test_intervening_same_ordinal_collapse_contaminates_prior_end() -> None:
    parsed = parse_html_document(INTERVENING_COLLAPSE_HTML)
    sections, issues, status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert "part_1.item_1c.cybersecurity" not in by_key
    assert any(
        i.code == "SECTION_BOUNDARY_UNRESOLVED"
        and i.context.get("reason") == "same_ordinal_collapse"
        for i in issues
    )
    assert status == "incomplete"


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


def test_layout_table_signatures_terminal() -> None:
    parsed = parse_html_document(LAYOUT_TABLE_SIGNATURES_HTML)
    sections, _issues, _status, terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert "part_2.item_7.mda" in by_key
    assert "part_2.item_8.financial_statements" in by_key
    assert terminal is not None
    assert terminal > by_key["part_2.item_8.financial_statements"].start_block_ordinal


def test_compact_toc_body_selects_exact_body_ordinal() -> None:
    parsed = parse_html_document(COMPACT_TOC_BODY_HTML)
    sections, _issues, _status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    body_item1 = next(
        b.ordinal
        for b in parsed.blocks
        if b.text and b.text.upper().startswith("ITEM 1. BUSINESS") and b.kind == "heading"
    )
    assert by_key["part_1.item_1.business"].start_block_ordinal == body_item1


def test_missing_intermediate_ok() -> None:
    parsed = parse_html_document(MISSING_INTERMEDIATE_HTML)
    sections, issues, status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert "part_1.item_1a.risk_factors" in by_key
    assert "part_1.item_1c.cybersecurity" in by_key
    assert (
        by_key["part_1.item_1a.risk_factors"].end_block_ordinal_exclusive
        == by_key["part_1.item_1c.cybersecurity"].start_block_ordinal
    )
    assert "part_1.item_1b.unresolved_staff_comments" not in by_key
    assert any(
        i.code == "SECTION_NOT_FOUND" and "item_1b" in i.context.get("section_key", "")
        for i in issues
    )
    # Missing intermediate alone does not force incomplete if other sections resolve;
    # other missing persisted keys may still leave complete if only NOT_FOUND.
    assert status == "complete"


def test_ordinary_missing_start_warning_complete() -> None:
    parsed = parse_html_document(ORDINARY_MISSING_START_HTML)
    sections, issues, status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert "part_1.item_1.business" not in by_key
    assert any(
        i.code == "SECTION_NOT_FOUND" and i.context.get("section_key") == "part_1.item_1.business"
        for i in issues
    )
    assert "part_2.item_7.mda" in by_key
    assert status == "complete"


def test_no_terminal_final_section_unresolved() -> None:
    parsed = parse_html_document(NO_TERMINAL_END_HTML)
    sections, issues, status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    assert "part_2.item_8.financial_statements" not in _section_map(sections)
    assert any(i.code == "SECTION_BOUNDARY_UNRESOLVED" for i in issues)
    assert status == "incomplete"


def test_part_i_only_reset_leaves_later_unresolved() -> None:
    parsed = parse_html_document(PART_I_ONLY_RESET_10Q_HTML)
    sections, issues, status, _terminal = extract_filing_sections(
        parsed, form_type="10-Q", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert "part_1.item_1.financial_statements" in by_key
    assert "part_2.item_1.legal_proceedings" not in by_key
    assert any(
        i.code == "SECTION_AMBIGUOUS" and i.context.get("reason") == "part_context_unresolved"
        for i in issues
    )
    assert status == "incomplete"


def test_plain_short_item_selectable() -> None:
    parsed = parse_html_document(PLAIN_SHORT_ITEM_HTML)
    sections, _issues, _status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert "part_2.item_7.mda" in by_key
    assert "part_2.item_8.financial_statements" in by_key


def test_weak_toc_like_candidate_skipped_for_body() -> None:
    parsed = parse_html_document(WEAK_CANDIDATE_HTML)
    sections, _issues, _status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    body7 = next(
        b.ordinal
        for b in parsed.blocks
        if b.text and "MANAGEMENT" in b.text.upper() and b.kind == "heading"
    )
    assert by_key["part_2.item_7.mda"].start_block_ordinal == body7


def test_adversarial_global_sequence_prefers_earlier_path() -> None:
    parsed = parse_html_document(ADVERSARIAL_GLOBAL_HTML)
    sections, _issues, _status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    early_item1 = next(
        b.ordinal
        for b in parsed.blocks
        if b.text and b.text.upper().startswith("ITEM 1. BUSINESS") and b.kind == "heading"
    )
    early_item1a = next(
        b.ordinal
        for b in parsed.blocks
        if b.text and b.text.upper().startswith("ITEM 1A.") and b.kind == "heading"
    )
    assert by_key["part_1.item_1.business"].start_block_ordinal == early_item1
    assert by_key["part_1.item_1a.risk_factors"].start_block_ordinal == early_item1a


def test_toc_only_section_match_incomplete() -> None:
    parsed = parse_html_document(TOC_ONLY_HTML)
    sections, issues, status, _terminal = extract_filing_sections(
        parsed, form_type="10-K", extract_regulatory_sections=True
    )
    assert "part_1.item_1.business" not in _section_map(sections)
    assert any(i.code == "TOC_ONLY_SECTION_MATCH" for i in issues)
    assert status == "incomplete"
    assert not (
        status == "complete"
        and all(i.code == "SECTION_NOT_FOUND" for i in issues if i.code.startswith("SECTION"))
    )


def test_toc_part_ii_does_not_establish_body_part() -> None:
    parsed = parse_html_document(TOC_PART_II_NOT_BODY_HTML)
    sections, _issues, _status, _terminal = extract_filing_sections(
        parsed, form_type="10-Q", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    assert "part_1.item_1.financial_statements" in by_key
    assert "part_2.item_1.legal_proceedings" in by_key
    body_p1 = next(
        b.ordinal
        for b in parsed.blocks
        if b.text and b.text.upper().startswith("ITEM 1. FINANCIAL") and b.kind == "heading"
    )
    body_p2 = next(
        b.ordinal
        for b in parsed.blocks
        if b.text and b.text.upper().startswith("ITEM 1. LEGAL") and b.kind == "heading"
    )
    assert by_key["part_1.item_1.financial_statements"].start_block_ordinal == body_p1
    assert by_key["part_2.item_1.legal_proceedings"].start_block_ordinal == body_p2
    assert body_p1 < body_p2


def test_distant_link_heavy_toc_cluster_does_not_swallow_body_parts() -> None:
    parsed = parse_html_document(DISTANT_LINK_HEAVY_TOC_CLUSTER_HTML)
    sections, _issues, _status, _terminal = extract_filing_sections(
        parsed, form_type="10-Q", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    body_p1 = next(
        b.ordinal
        for b in parsed.blocks
        if b.text and b.text.upper().startswith("ITEM 1. FINANCIAL") and b.kind == "heading"
    )
    body_p2 = next(
        b.ordinal
        for b in parsed.blocks
        if b.text and b.text.upper().startswith("ITEM 1. LEGAL") and b.kind == "heading"
    )
    assert by_key["part_1.item_1.financial_statements"].start_block_ordinal == body_p1
    assert by_key["part_2.item_1.legal_proceedings"].start_block_ordinal == body_p2
    assert body_p1 < body_p2


def test_resolved_part_ii_despite_ambiguous_part_i() -> None:
    parsed = parse_html_document(RESOLVED_PART_II_DESPITE_AMB_PART_I_HTML)
    sections, issues, status, _terminal = extract_filing_sections(
        parsed, form_type="10-Q", extract_regulatory_sections=True
    )
    by_key = _section_map(sections)
    body_p2_i1 = next(
        b.ordinal
        for b in parsed.blocks
        if b.text and b.text.upper().startswith("ITEM 1. LEGAL") and b.kind == "heading"
    )
    body_p2_i1a = next(
        b.ordinal
        for b in parsed.blocks
        if b.text and b.text.upper().startswith("ITEM 1A. RISK") and b.kind == "heading"
    )
    assert "part_1.item_1.financial_statements" not in by_key
    assert by_key["part_2.item_1.legal_proceedings"].start_block_ordinal == body_p2_i1
    assert by_key["part_2.item_1a.risk_factors"].start_block_ordinal == body_p2_i1a
    assert any(
        i.code == "SECTION_AMBIGUOUS" and i.context.get("reason") == "part_context_unresolved"
        for i in issues
    )
    assert status == "incomplete"


def test_skip_ambiguity_threshold_45_vs_46() -> None:
    order = ("part_1.item_1",)

    def run(score: int) -> tuple[dict[str, _Candidate | None], dict[str, bool]]:
        cands = {
            "part_1.item_1": [
                _Candidate(
                    boundary_key="part_1.item_1",
                    block_ordinal=10,
                    score=score,
                    toc_like=False,
                )
            ]
        }
        selected, ambiguous, _alts = _global_monotonic_dp(order, cands)
        return selected, ambiguous

    assert BODY_SELECTION_BASELINE + SCORE_GAP == 45
    selected_45, amb_45 = run(45)
    assert selected_45["part_1.item_1"] is None
    assert amb_45["part_1.item_1"] is True

    selected_46, amb_46 = run(46)
    assert selected_46["part_1.item_1"] is not None
    assert amb_46["part_1.item_1"] is False


def test_alt_ordinals_exclude_far_worse_decoy() -> None:
    order = ("part_1.item_1", "part_1.item_1a")
    cands = {
        "part_1.item_1": [
            _Candidate("part_1.item_1", 10, 50, False),  # contrib 20
            _Candidate("part_1.item_1", 30, 46, False),  # contrib 16
            _Candidate("part_1.item_1", 80, 55, False),  # decoy; forces weak later path
        ],
        "part_1.item_1a": [
            _Candidate("part_1.item_1a", 20, 90, False),  # contrib 60
            _Candidate("part_1.item_1a", 90, 40, False),  # contrib 10 — only after decoy@80
        ],
    }
    # S* ≈ Item1@10 + Item1A@20 = 20+60 = 80
    # Force Item1@80 → Item1A@90 = 25+10 = 35; gap 45 > SCORE_GAP
    _selected, _ambiguous, alts = _global_monotonic_dp(order, cands)
    assert 80 not in alts.get("part_1.item_1", [])


def test_unambiguous_part_ii_survives_ambiguous_part_i() -> None:
    items = [
        _RawOccurrence(kind="item", block_ordinal=50, score=50, item_tokens=("1",)),
        _RawOccurrence(kind="item", block_ordinal=520, score=50, item_tokens=("1",)),
        _RawOccurrence(kind="item", block_ordinal=530, score=50, item_tokens=("1a",)),
    ]
    cands, unresolved = _assign_item_parts(
        "10-Q",
        items,
        toc_ords=set(),
        part1_ord=None,
        part2_ord=500,
        part1_ambiguous=True,
        part2_ambiguous=False,
        part1_alt_ordinals=(10, 40),
        part2_alt_ordinals=(),
    )
    keys = {(c.boundary_key, c.block_ordinal) for c in cands}
    assert ("part_2.item_1", 520) in keys
    assert ("part_2.item_1a", 530) in keys
    assert ("part_1.item_1", 50) not in keys
    assert "part_1.item_1" in unresolved


def test_ambiguous_part_ii_cuts_before_earliest_alt() -> None:
    items = [
        _RawOccurrence(kind="item", block_ordinal=110, score=50, item_tokens=("1",)),
        _RawOccurrence(kind="item", block_ordinal=120, score=50, item_tokens=("2",)),
        _RawOccurrence(kind="item", block_ordinal=400, score=50, item_tokens=("3",)),
    ]
    cands, unresolved = _assign_item_parts(
        "10-Q",
        items,
        toc_ords=set(),
        part1_ord=100,
        part2_ord=None,
        part1_ambiguous=False,
        part2_ambiguous=True,
        part1_alt_ordinals=(),
        part2_alt_ordinals=(300, 500),
    )
    keys = {(c.boundary_key, c.block_ordinal) for c in cands}
    assert ("part_1.item_1", 110) in keys
    assert ("part_1.item_2", 120) in keys
    assert ("part_1.item_3", 400) not in keys
    assert "part_1.item_3" in unresolved or "part_2.item_3" in unresolved


def test_ambiguous_part_ii_monotonic_reset_before_transition() -> None:
    items = [
        _RawOccurrence(kind="item", block_ordinal=110, score=50, item_tokens=("1",)),
        _RawOccurrence(kind="item", block_ordinal=120, score=50, item_tokens=("2",)),
        _RawOccurrence(kind="item", block_ordinal=130, score=50, item_tokens=("3",)),
        _RawOccurrence(kind="item", block_ordinal=140, score=50, item_tokens=("4",)),
        _RawOccurrence(kind="item", block_ordinal=400, score=50, item_tokens=("1",)),
    ]
    cands, unresolved = _assign_item_parts(
        "10-Q",
        items,
        toc_ords=set(),
        part1_ord=100,
        part2_ord=None,
        part1_ambiguous=False,
        part2_ambiguous=True,
        part1_alt_ordinals=(),
        part2_alt_ordinals=(500, 700),
    )
    keys = {(c.boundary_key, c.block_ordinal) for c in cands}
    assert ("part_1.item_4", 140) in keys
    assert ("part_1.item_1", 400) not in keys
    assert min((500, 700)) > 400
    assert "part_1.item_1" in unresolved or "part_2.item_1" in unresolved
