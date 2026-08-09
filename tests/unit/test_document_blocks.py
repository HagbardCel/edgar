"""Unit tests for deterministic HTML block extraction."""

from __future__ import annotations

from edgar.parsing.html import normalize_whitespace, parse_html_document, resolve_xpath
from edgar.parsing.records import DocumentParseError
from tests.helpers.document_fixtures import (
    LAYOUT_TABLE_ITEMS_HTML,
    MIXED_CONTENT_HTML,
    RICH_10K_HTML,
)


def test_whitespace_normalization() -> None:
    assert normalize_whitespace("Revenue\u00a0increased\n  12%") == "Revenue increased 12%"


def test_script_style_and_hidden_excluded() -> None:
    html = b"""<html><body>
    <script>Item 1. Fake</script>
    <style>.x{}</style>
    <div style="display: none">Item 1. Hidden</div>
    <p>Visible paragraph.</p>
    </body></html>"""
    parsed = parse_html_document(html)
    texts = [b.text for b in parsed.blocks if b.text]
    assert "Visible paragraph." in texts
    assert not any(t and "Fake" in t for t in texts)
    assert not any(t and "Hidden" in t for t in texts)


def test_mixed_content_before_and_after_child() -> None:
    parsed = parse_html_document(MIXED_CONTENT_HTML)
    texts = [b.text for b in parsed.blocks if b.text]
    assert texts == ["Introductory text.", "Paragraph text.", "Trailing text."]


def test_list_parent_has_null_text_no_duplication() -> None:
    html = b"""<html><body>
    <ul><li>Apple</li><li>Banana</li><li>Cherry</li></ul>
    </body></html>"""
    parsed = parse_html_document(html)
    lists = [b for b in parsed.blocks if b.kind == "list"]
    items = [b for b in parsed.blocks if b.kind == "list_item"]
    assert len(lists) == 1
    assert lists[0].text is None
    assert [i.text for i in items] == ["Apple", "Banana", "Cherry"]
    joined = " ".join(b.text for b in parsed.blocks if b.text)
    assert joined.count("Apple") == 1


def test_layout_table_preserves_item_boundaries() -> None:
    parsed = parse_html_document(LAYOUT_TABLE_ITEMS_HTML)
    texts = [b.text for b in parsed.blocks if b.text]
    assert any(t and t.upper().startswith("ITEM 7.") for t in texts)
    assert any(t and "ITEM 7A." in t.upper() for t in texts)
    item7 = next(
        b
        for b in parsed.blocks
        if b.text and "ITEM 7." in b.text.upper() and "7A" not in b.text.upper()
    )
    item7a = next(b for b in parsed.blocks if b.text and "ITEM 7A." in b.text.upper())
    assert item7.ordinal != item7a.ordinal


def test_data_table_is_atomic() -> None:
    html = b"""<html><body>
    <table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>
    </body></html>"""
    parsed = parse_html_document(html)
    tables = [b for b in parsed.blocks if b.kind == "table"]
    assert len(tables) == 1
    assert tables[0].text is not None
    assert "A" in tables[0].text and "B" in tables[0].text


def test_visible_ixbrl_retained_hidden_excluded() -> None:
    parsed = parse_html_document(RICH_10K_HTML)
    joined = " ".join(b.text for b in parsed.blocks if b.text)
    assert "1000" in joined
    assert "Hidden decoy" not in joined
    assert "Hidden risk" not in joined


def test_xpath_element_backed_round_trip() -> None:
    html = b"<html><body><p>Hello world</p></body></html>"
    parsed = parse_html_document(html)
    para = next(b for b in parsed.blocks if b.kind == "paragraph")
    resolved = resolve_xpath(html, para.source_locator_value)
    assert len(resolved) == 1
    assert normalize_whitespace("".join(resolved[0].itertext())) == "Hello world"


def test_mixed_fragment_deterministic_reextract() -> None:
    first = parse_html_document(MIXED_CONTENT_HTML)
    second = parse_html_document(MIXED_CONTENT_HTML)
    assert [b.to_dict() for b in first.blocks] == [b.to_dict() for b in second.blocks]


def test_empty_html_raises() -> None:
    try:
        parse_html_document(b"")
        raise AssertionError("expected DocumentParseError")
    except DocumentParseError as exc:
        assert exc.issues[0].code == "HTML_PARSE_FAILED"


def test_signatures_heading_remains_heading() -> None:
    html = b"<html><body><h2>SIGNATURES</h2><p>Pursuant to...</p></body></html>"
    parsed = parse_html_document(html)
    heading = next(b for b in parsed.blocks if b.text and b.text.upper().startswith("SIGNATURES"))
    assert heading.kind == "heading"
    assert heading.heading_level == 2
