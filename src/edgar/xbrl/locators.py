"""Deterministic element locators for source occurrences (``element-locator-v1``).

A locator addresses one element inside one immutable source document. It is
derived only from the document's own bytes, so it is reproducible offline and is
never an Arelle in-memory object identifier or a filesystem path.

Preference order, first match wins:

1. an ``xml:id`` that is unique within the owning document
2. an unqualified ``id`` that is unique within the owning document
3. the expanded element path from the document root

A syntactically non-unique id is not trusted: the locator falls back to the
expanded path. The expanded path is a sequence of Clark-notation names with a
1-based ordinal among same-named siblings, serialized as
``/{ns}local[1]/{ns}child[2]`` (an unqualified name has no braces).

``xlink:label`` and source line are provenance only. They never participate in
locator identity because they are neither unique nor stable across serializers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import lxml.etree as etree

from edgar.xbrl.config import ELEMENT_LOCATOR_VERSION
from edgar.xbrl.records import SourceLocator

# lxml ships no type information; elements are used structurally here.
XmlElement = Any

XML_NS = "http://www.w3.org/XML/1998/namespace"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_ID_ATTRIBUTE = f"{{{XML_NS}}}id"
XLINK_LABEL_ATTRIBUTE = f"{{{XLINK_NS}}}label"

LOCATOR_VERSION = ELEMENT_LOCATOR_VERSION


class LocatorError(ValueError):
    """Raised when a locator cannot be derived or parsed deterministically."""


def _clark(element: XmlElement) -> str:
    tag = element.tag
    if not isinstance(tag, str):
        raise LocatorError(f"only element nodes can be located, got {type(tag).__name__}")
    return etree.QName(tag).text


def _is_element(node: XmlElement) -> bool:
    return isinstance(getattr(node, "tag", None), str)


def _attribute_is_unique(root: XmlElement, xpath: str, value: str, namespaces: Any) -> bool:
    found = root.xpath(xpath, namespaces=namespaces or {}, value=value)
    return isinstance(found, list) and len(found) == 1


def expanded_element_path(element: XmlElement) -> tuple[tuple[str, int], ...]:
    """Path from the document root as ``((clark_name, ordinal), ...)``."""
    segments: list[tuple[str, int]] = []
    current = element
    while current is not None and _is_element(current):
        name = _clark(current)
        parent = current.getparent()
        if parent is None:
            ordinal = 1
        else:
            ordinal = 0
            for sibling in parent:
                if not _is_element(sibling) or _clark(sibling) != name:
                    continue
                ordinal += 1
                if sibling is current:
                    break
            else:  # pragma: no cover - a child is always found under its parent
                raise LocatorError(f"element {name} not found among its parent's children")
        segments.append((name, ordinal))
        current = parent
    segments.reverse()
    return tuple(segments)


def _split_clark(name: str) -> tuple[str | None, str]:
    """Split a Clark name into (namespace, local), rejecting unserializable names."""
    if name.startswith("{"):
        namespace, closing, local = name[1:].partition("}")
        if not closing or not namespace or "{" in namespace or "}" in namespace:
            raise LocatorError(f"malformed Clark element name: {name!r}")
    else:
        namespace, local = None, name
    if not local or any(ch in local for ch in "/[]{}"):
        raise LocatorError(f"element name is not serializable in a locator: {name!r}")
    return namespace, local


def format_expanded_path(segments: tuple[tuple[str, int], ...]) -> str:
    """Serialize an expanded path to its canonical locator value."""
    if not segments:
        raise LocatorError("expanded path must have at least one segment")
    parts: list[str] = []
    for name, ordinal in segments:
        if ordinal < 1:
            raise LocatorError(f"invalid path segment: {(name, ordinal)!r}")
        _split_clark(name)
        parts.append(f"{name}[{ordinal}]")
    return "/" + "/".join(parts)


def parse_expanded_path(value: str) -> tuple[tuple[str, int], ...]:
    """Inverse of :func:`format_expanded_path`; validates the locator syntax.

    Namespace URIs contain ``/``, so segments are scanned rather than split: a
    segment is ``/`` then an optional ``{namespace}``, then the local name, then
    a bracketed 1-based ordinal.
    """
    if not value.startswith("/"):
        raise LocatorError(f"expanded path must start with '/': {value!r}")
    segments: list[tuple[str, int]] = []
    position = 0
    length = len(value)
    while position < length:
        if value[position] != "/":
            raise LocatorError(f"malformed expanded path at offset {position}: {value!r}")
        position += 1
        start = position
        if position < length and value[position] == "{":
            closing = value.find("}", position)
            if closing < 0:
                raise LocatorError(f"unterminated namespace in expanded path: {value!r}")
            position = closing + 1
        bracket = value.find("[", position)
        if bracket < 0:
            raise LocatorError(f"missing ordinal in expanded path: {value!r}")
        close = value.find("]", bracket)
        if close < 0:
            raise LocatorError(f"unterminated ordinal in expanded path: {value!r}")
        name = value[start:bracket]
        _split_clark(name)
        try:
            ordinal = int(value[bracket + 1 : close])
        except ValueError as exc:
            raise LocatorError(f"non-integer ordinal in expanded path: {value!r}") from exc
        if ordinal < 1:
            raise LocatorError(f"ordinal must be 1-based: {value!r}")
        segments.append((name, ordinal))
        position = close + 1
    if not segments:
        raise LocatorError(f"expanded path has no segments: {value!r}")
    return tuple(segments)


def element_locator(element: XmlElement, *, document_uri: str) -> SourceLocator:
    """Build the stable locator for ``element`` within its own document.

    ``document_uri`` must be the canonical replay URI of the bundle URI binding
    that owns the bytes; :class:`~edgar.xbrl.records.SourceLocator` rejects any
    other form.
    """
    tree = element.getroottree()
    root = tree.getroot() if tree is not None else None
    if root is None:
        raise LocatorError("element is not attached to a document tree")

    xml_id = element.get(XML_ID_ATTRIBUTE)
    if xml_id and _attribute_is_unique(root, "//*[@xml:id=$value]", xml_id, {"xml": XML_NS}):
        return SourceLocator(document_uri=document_uri, scheme="xml_id", value=xml_id)

    plain_id = element.get("id")
    if plain_id and _attribute_is_unique(root, "//*[@id=$value]", plain_id, None):
        return SourceLocator(document_uri=document_uri, scheme="unqualified_id", value=plain_id)

    path = format_expanded_path(expanded_element_path(element))
    return SourceLocator(document_uri=document_uri, scheme="expanded_element_path", value=path)


@dataclass(frozen=True)
class LocatorProvenance:
    """Non-identity provenance retained beside a locator for diagnostics only."""

    xlink_label: str | None = None
    source_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"xlink_label": self.xlink_label, "source_line": self.source_line}


def occurrence_provenance(element: XmlElement) -> LocatorProvenance:
    """Collect ``xlink:label`` and source line; neither is locator identity."""
    label = element.get(XLINK_LABEL_ATTRIBUTE)
    raw_line = getattr(element, "sourceline", None)
    return LocatorProvenance(
        xlink_label=label or None,
        source_line=int(raw_line) if raw_line is not None else None,
    )
