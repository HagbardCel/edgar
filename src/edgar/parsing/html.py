"""Deterministic offline HTML → document blocks + ephemeral section signals."""

from __future__ import annotations

import re
from typing import Any

import lxml.etree as etree
from lxml import html

from edgar.parsing.records import (
    SOURCE_LOCATOR_SCHEME,
    DocumentBlockKind,
    DocumentBlockRecord,
    DocumentIssueRecord,
    DocumentParseError,
    ParsedDocument,
    SectionSignal,
)

_SKIP_TAGS = frozenset({"script", "style", "noscript"})
_IX_HIDDEN_LOCAL = frozenset({"hidden", "header"})
_IX_NAMESPACE_MARKERS = ("inlinexbrl",)
_BLOCK_TAGS = frozenset({"p", "pre", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_NBSP_RE = re.compile(r"[\u00a0\u2007\u202f]")
_WS_RE = re.compile(r"[\t\r\n\f ]+")
_SIGNATURE_MARKUP_RE = re.compile(r"(?i)^\s*/\s*s\s*/")


def normalize_whitespace(text: str) -> str:
    """Whitespace-v1: NBSP→space, collapse runs, strip; preserve case/punctuation."""
    cleaned = _NBSP_RE.sub(" ", text)
    cleaned = _WS_RE.sub(" ", cleaned)
    return cleaned.strip()


def _local_name(tag: Any) -> str:
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1].lower()
    if ":" in tag:
        return tag.rsplit(":", 1)[-1].lower()
    return tag.lower()


def _expanded_namespace_uri(tag: Any) -> str | None:
    """Return the element's own Clark-notation namespace URI, if present."""
    if not isinstance(tag, str):
        return None
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return None


def _is_inline_xbrl_namespace(uri: str | None) -> bool:
    if not uri:
        return False
    lowered = uri.lower()
    return any(marker in lowered for marker in _IX_NAMESPACE_MARKERS)


def _is_ix_qualified_hidden(el: etree._Element) -> bool:
    """True only when *this* element is IX-qualified hidden/header.

    Qualification uses the element's own lexical tag or expanded QName namespace.
    In-scope nsmap declarations alone do not qualify ordinary HTML elements.
    """
    local = _local_name(el.tag)
    if local not in _IX_HIDDEN_LOCAL:
        return False
    tag = el.tag if isinstance(el.tag, str) else ""
    # Lexical ix:header / ix:hidden (HTML parser may keep the prefix).
    if tag.lower().startswith("ix:") and local in _IX_HIDDEN_LOCAL:
        return True
    if el.prefix == "ix" and local in _IX_HIDDEN_LOCAL:
        return True
    # Own expanded QName namespace is Inline XBRL.
    if _is_inline_xbrl_namespace(_expanded_namespace_uri(tag)):
        return True
    # Bare <hidden> is not HTML5; treat as ix:hidden equivalent.
    # Bare <header> is ordinary HTML5 and must remain visible.
    return local == "hidden" and "{" not in tag and ":" not in tag


def _style_hides(style: str | None) -> bool:
    if not style:
        return False
    for decl in style.split(";"):
        if ":" not in decl:
            continue
        prop, _, value = decl.partition(":")
        prop = prop.strip().lower()
        value = value.strip().lower()
        if prop == "display" and value == "none":
            return True
        if prop == "visibility" and value == "hidden":
            return True
    return False


def _is_hidden(el: etree._Element) -> bool:
    if _local_name(el.tag) in _SKIP_TAGS:
        return True
    if el.get("hidden") is not None:
        return True
    if _style_hides(el.get("style")):
        return True
    return _is_ix_qualified_hidden(el)


def _xpath_for(el: etree._Element) -> str:
    parts: list[str] = []
    node: etree._Element | None = el
    while node is not None and isinstance(node.tag, str):
        parent = node.getparent()
        name = _local_name(node.tag)
        if parent is None:
            parts.append(name)
            break
        siblings = [
            sib for sib in parent if isinstance(sib.tag, str) and _local_name(sib.tag) == name
        ]
        if len(siblings) == 1:
            parts.append(name)
        else:
            index = siblings.index(node) + 1
            parts.append(f"{name}[{index}]")
        node = parent
    parts.reverse()
    return "/" + "/".join(parts) if parts else "/"


def _append_text_chunk(chunks: list[str], raw: str | None) -> None:
    if raw:
        chunks.append(raw)


def _append_break_boundary(chunks: list[str]) -> None:
    chunks.append(" ")


def _element_text_content(el: etree._Element) -> str:
    chunks: list[str] = []

    def walk(node: etree._Element) -> None:
        if _is_hidden(node):
            return
        if node.text:
            chunks.append(node.text)
        for child in node:
            if isinstance(child.tag, str):
                local = _local_name(child.tag)
                if local == "br":
                    _append_break_boundary(chunks)
                    # lxml may attach following text as child text of void-ish tags.
                    if child.text:
                        chunks.append(child.text)
                elif local == "wbr":
                    # Word-break opportunity: no whitespace; keep any attached text.
                    if child.text:
                        chunks.append(child.text)
                else:
                    walk(child)
            if child.tail:
                chunks.append(child.tail)

    walk(el)
    return normalize_whitespace("".join(chunks))


def _is_block_element(el: etree._Element) -> bool:
    return _local_name(el.tag) in _BLOCK_TAGS


def _has_plausible_boundary_markup(el: etree._Element) -> bool:
    text = _element_text_content(el)
    if re.search(r"(?i)\bitem\s+\d+[a-z]?\b", text):
        return True
    if re.search(r"(?i)\bpart\s+[ivx]+\b", text):
        return True
    return bool(
        re.search(r"(?i)^\s*signatures?\b", text) or re.search(r"(?i)\bsignatures?\b", text[:40])
    )


def _table_is_layout(table: etree._Element) -> bool:
    """table-layout-v1: preserve addressability of Item/Part/SIGNATURE candidates."""
    if _has_plausible_boundary_markup(table):
        return True
    rows = table.xpath(".//tr")
    if not rows:
        return True
    max_cols = 0
    for row in rows:
        cols = row.xpath("./td|./th")
        max_cols = max(max_cols, len(cols))
    if max_cols <= 1:
        return True
    # Nested block-ish content.
    return bool(table.xpath(".//p|.//ul|.//ol|.//h1|.//h2|.//h3|.//h4|.//h5|.//h6"))


def _table_text(table: etree._Element) -> str:
    rows_out: list[str] = []
    for row in table.xpath(".//tr"):
        cells = []
        for cell in row.xpath("./td|./th"):
            cells.append(normalize_whitespace(_element_text_content(cell)))
        if any(cells):
            rows_out.append(" | ".join(cells))
    return "\n".join(rows_out)


def _is_bold_like(el: etree._Element) -> bool:
    if _local_name(el.tag) in {"b", "strong"}:
        return True
    style = (el.get("style") or "").lower()
    if "font-weight" in style and any(token in style for token in ("bold", "700", "800", "900")):
        return True
    return bool(el.xpath(".//b|.//strong"))


def _anchor_id(el: etree._Element) -> str | None:
    for attr in ("id", "name"):
        value = el.get(attr)
        if value:
            return value
    return None


def _link_stats(el: etree._Element) -> tuple[int, int, int]:
    total_text = _element_text_content(el)
    total_chars = len(total_text)
    links = el.xpath(".//a[@href]")
    internal = 0
    link_chars = 0
    for link in links:
        href = (link.get("href") or "").strip()
        if href.startswith("#"):
            internal += 1
        link_chars += len(_element_text_content(link))
    return internal, link_chars, total_chars


def _footnote_like(el: etree._Element) -> bool:
    identity = " ".join(
        filter(
            None,
            [
                (el.get("id") or ""),
                (el.get("class") or ""),
                (el.get("name") or ""),
            ],
        )
    ).lower()
    if "footnote" in identity or "foot-note" in identity:
        return True
    if _local_name(el.tag) == "small" and len(_element_text_content(el)) < 400:
        parent = el.getparent()
        if parent is not None and _local_name(parent.tag) in {"div", "p", "td", "body"}:
            return True
    return False


def _signature_structural(el: etree._Element, text: str) -> bool:
    """Parser-local structural signature cue (not regulatory terminal selection)."""
    if _SIGNATURE_MARKUP_RE.match(text):
        return True
    identity = " ".join(filter(None, [(el.get("id") or ""), (el.get("class") or "")])).lower()
    return "signature" in identity and "item" not in text.lower()


class _BlockBuilder:
    def __init__(self) -> None:
        self.blocks: list[DocumentBlockRecord] = []
        self.signals: list[SectionSignal] = []
        self.issues: list[DocumentIssueRecord] = []

    def _emit(
        self,
        *,
        kind: DocumentBlockKind,
        text: str | None,
        el: etree._Element,
        parent_ordinal: int | None,
        heading_level: int | None = None,
        signal_text: str | None = None,
    ) -> int:
        ordinal = len(self.blocks)
        xpath = _xpath_for(el)
        block = DocumentBlockRecord(
            ordinal=ordinal,
            parent_ordinal=parent_ordinal,
            kind=kind,
            text=text,
            heading_level=heading_level,
            source_locator_scheme=SOURCE_LOCATOR_SCHEME,
            source_locator_value=xpath,
        )
        self.blocks.append(block)
        candidate = signal_text if signal_text is not None else (text or "")
        internal, link_chars, total_chars = _link_stats(el)
        self.signals.append(
            SectionSignal(
                block_ordinal=ordinal,
                source_xpath=xpath,
                tag=_local_name(el.tag),
                heading_level=heading_level,
                is_bold_like=_is_bold_like(el),
                anchor_id=_anchor_id(el),
                internal_link_count=internal,
                link_text_chars=link_chars,
                total_text_chars=total_chars,
                normalized_candidate_text=normalize_whitespace(candidate).casefold(),
            )
        )
        return ordinal

    def walk(self, el: etree._Element, parent_ordinal: int | None) -> None:
        if not isinstance(el.tag, str):
            return
        if _is_hidden(el):
            return

        tag = _local_name(el.tag)

        if tag in _HEADING_TAGS:
            text = _element_text_content(el)
            if text:
                level = int(tag[1])
                self._emit(
                    kind="heading",
                    text=text,
                    el=el,
                    parent_ordinal=parent_ordinal,
                    heading_level=level,
                )
            return

        if tag in {"p", "pre"}:
            text = _element_text_content(el)
            if not text:
                return
            kind: DocumentBlockKind = "paragraph"
            if _footnote_like(el):
                kind = "footnote"
            elif _signature_structural(el, text):
                kind = "signature"
            self._emit(kind=kind, text=text, el=el, parent_ordinal=parent_ordinal)
            return

        if tag in {"ul", "ol"}:
            list_ordinal = self._emit(
                kind="list",
                text=None,
                el=el,
                parent_ordinal=parent_ordinal,
                signal_text=_element_text_content(el),
            )
            for child in el:
                if isinstance(child.tag, str) and _local_name(child.tag) == "li":
                    self.walk(child, list_ordinal)
            return

        if tag == "li":
            # Emit list_item with direct uncovered text; nested lists as children.
            nested_lists = [
                child
                for child in el
                if isinstance(child.tag, str) and _local_name(child.tag) in {"ul", "ol"}
            ]
            # Build item text excluding nested lists; treat <br> as whitespace.
            clone_parts: list[str] = []
            if el.text:
                clone_parts.append(el.text)
            for child in el:
                if isinstance(child.tag, str) and _local_name(child.tag) in {"ul", "ol"}:
                    if child.tail:
                        clone_parts.append(child.tail)
                    continue
                if isinstance(child.tag, str) and not _is_hidden(child):
                    local = _local_name(child.tag)
                    if local == "br":
                        _append_break_boundary(clone_parts)
                    elif local == "wbr":
                        pass
                    else:
                        clone_parts.append(_element_text_content(child))
                if child.tail:
                    clone_parts.append(child.tail)
            item_text = normalize_whitespace("".join(clone_parts))
            item_ordinal = self._emit(
                kind="list_item",
                text=item_text or None,
                el=el,
                parent_ordinal=parent_ordinal,
                signal_text=item_text,
            )
            for nested in nested_lists:
                self.walk(nested, item_ordinal)
            return

        if tag == "table":
            if _table_is_layout(el):
                for child in el:
                    if isinstance(child.tag, str):
                        self.walk(child, parent_ordinal)
                return
            text = _table_text(el)
            if text:
                self._emit(kind="table", text=text, el=el, parent_ordinal=parent_ordinal)
            return

        self._walk_container(el, parent_ordinal)

    def _walk_container(self, el: etree._Element, parent_ordinal: int | None) -> None:
        # Process in document order: uncovered prefix, child subtree, uncovered tail.
        buffer: list[str] = []

        def flush_buffer() -> None:
            if not buffer:
                return
            text = normalize_whitespace("".join(buffer))
            buffer.clear()
            if not text:
                return
            kind: DocumentBlockKind = "other"
            if _footnote_like(el):
                kind = "footnote"
            elif _signature_structural(el, text):
                kind = "signature"
            else:
                kind = "paragraph"
            self._emit(kind=kind, text=text, el=el, parent_ordinal=parent_ordinal)

        def collect_inline_into_buffer(node: etree._Element) -> None:
            """Collect inline text; flush+walk nested blocks; continue after them."""
            if _is_hidden(node):
                return
            if node.text:
                buffer.append(node.text)
            for child in node:
                if not isinstance(child.tag, str):
                    if child.tail:
                        buffer.append(child.tail)
                    continue
                local = _local_name(child.tag)
                if local == "br":
                    _append_break_boundary(buffer)
                    if child.text:
                        buffer.append(child.text)
                    if child.tail:
                        buffer.append(child.tail)
                    continue
                if local == "wbr":
                    if child.text:
                        buffer.append(child.text)
                    if child.tail:
                        buffer.append(child.tail)
                    continue
                if _should_descend_as_block(child):
                    flush_buffer()
                    self.walk(child, parent_ordinal)
                    if child.tail:
                        buffer.append(child.tail)
                    continue
                collect_inline_into_buffer(child)
                if child.tail:
                    buffer.append(child.tail)

        if el.text:
            buffer.append(el.text)
        for child in el:
            if not isinstance(child.tag, str):
                if child.tail:
                    buffer.append(child.tail)
                continue
            if _is_hidden(child):
                if child.tail:
                    buffer.append(child.tail)
                continue
            local = _local_name(child.tag)
            if local == "br":
                _append_break_boundary(buffer)
                if child.text:
                    buffer.append(child.text)
                if child.tail:
                    buffer.append(child.tail)
                continue
            if local == "wbr":
                if child.text:
                    buffer.append(child.text)
                if child.tail:
                    buffer.append(child.tail)
                continue
            if _should_descend_as_block(child):
                flush_buffer()
                self.walk(child, parent_ordinal)
                if child.tail:
                    buffer.append(child.tail)
                continue
            # Treat as inline content; may contain nested blocks.
            collect_inline_into_buffer(child)
            if child.tail:
                buffer.append(child.tail)
        flush_buffer()


def _should_descend_as_block(el: etree._Element) -> bool:
    tag = _local_name(el.tag)
    if tag in _BLOCK_TAGS:
        return True
    if tag == "table":
        return True
    structural = {
        "div",
        "section",
        "article",
        "main",
        "header",
        "footer",
        "td",
        "th",
        "tr",
        "tbody",
        "thead",
        "tfoot",
    }
    return tag in structural


def parse_html_document(html_bytes: bytes) -> ParsedDocument:
    """Parse HTML bytes into final blocks + ephemeral signals.

    Raises DocumentParseError for fatal outcomes (no coherent projection).
    """
    if not html_bytes or not html_bytes.strip():
        raise DocumentParseError(
            "HTML document is empty",
            issues=(
                DocumentIssueRecord(
                    severity="fatal",
                    code="HTML_PARSE_FAILED",
                    message="empty HTML document",
                ),
            ),
        )
    try:
        # recover=True for malformed SEC HTML; no network; no huge_tree.
        parser = html.HTMLParser(recover=True, no_network=True, huge_tree=False)
        root = html.document_fromstring(html_bytes, parser=parser)
    except Exception as exc:  # noqa: BLE001 — convert parser failures
        raise DocumentParseError(
            f"HTML parse failed: {exc}",
            issues=(
                DocumentIssueRecord(
                    severity="fatal",
                    code="HTML_PARSE_FAILED",
                    message=str(exc),
                ),
            ),
        ) from exc

    builder = _BlockBuilder()
    body = root.find(".//body")
    start = body if body is not None else root
    builder.walk(start, None)

    meaningful = [b for b in builder.blocks if b.text is not None or b.kind in {"list"}]
    if not meaningful:
        raise DocumentParseError(
            "document produced no meaningful blocks",
            issues=(
                DocumentIssueRecord(
                    severity="fatal",
                    code="DOCUMENT_NO_MEANINGFUL_BLOCKS",
                    message="no meaningful blocks after HTML extraction",
                ),
            ),
        )

    return ParsedDocument(
        blocks=tuple(builder.blocks),
        section_signals=tuple(builder.signals),
        issues=tuple(builder.issues),
    )


def resolve_xpath(html_bytes: bytes, xpath: str) -> list[Any]:
    """Reparse bytes and evaluate an absolute XPath (test helper)."""
    parser = html.HTMLParser(recover=True, no_network=True, huge_tree=False)
    root = html.document_fromstring(html_bytes, parser=parser)
    return root.xpath(xpath)


__all__ = [
    "normalize_whitespace",
    "parse_html_document",
    "resolve_xpath",
]
