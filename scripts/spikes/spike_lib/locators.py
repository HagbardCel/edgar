"""Deterministic element locators for resource/arc/endpoint occurrences.

Locator preference:
1. unique ``xml:id`` within the owning document
2. unique unqualified ``id`` within the owning document
3. deterministic expanded element path (Clark-notation QName + 1-based
   ordinal among same-expanded-name siblings) from the document root

xlink:label and source line are retained as provenance only; they are not
stable identity inputs. A syntactically non-unique id falls back to the
expanded element path rather than trusting the id.
"""

from __future__ import annotations

from typing import Any

import lxml.etree as etree

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XLINK_LABEL = "{http://www.w3.org/1999/xlink}label"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _clark(tag: Any) -> str:
    return etree.QName(tag).text


def _id_is_unique(
    root: Any, attr_xpath: str, value: str, namespaces: dict[str, str] | None
) -> bool:
    found = root.xpath(attr_xpath, namespaces=namespaces or {}, value=value)
    return len(found) == 1


def expanded_element_path(element: Any) -> list[list[Any]]:
    """Path from the document root: [[clark_qname, ordinal], ...]."""
    segments: list[list[Any]] = []
    current = element
    while current is not None and isinstance(current.tag, str):
        qname = _clark(current.tag)
        parent = current.getparent()
        if parent is None:
            ordinal = 1
        else:
            same_name = [
                child
                for child in parent
                if isinstance(child.tag, str) and _clark(child.tag) == qname
            ]
            # lxml element equality is identity-based.
            ordinal = same_name.index(current) + 1
        segments.append([qname, ordinal])
        current = parent
    segments.reverse()
    return segments


def element_locator(element: Any) -> dict[str, Any]:
    """Stable deterministic locator for an element within its document."""
    root = element.getroottree().getroot()
    xml_id = element.get(XML_ID)
    if xml_id and _id_is_unique(root, "//*[@xml:id=$value]", xml_id, {"xml": XML_NS}):
        return {"kind": "xml_id", "value": xml_id}
    plain_id = element.get("id")
    if plain_id and _id_is_unique(root, "//*[@id=$value]", plain_id, None):
        return {"kind": "unqualified_id", "value": plain_id}
    return {"kind": "expanded_element_path", "path": expanded_element_path(element)}


def occurrence_provenance(element: Any) -> dict[str, Any]:
    """Non-identity provenance: xlink:label and source line when available."""
    provenance: dict[str, Any] = {}
    xlink_label = element.get(XLINK_LABEL)
    if xlink_label:
        provenance["xlink_label"] = xlink_label
    source_line = getattr(element, "sourceline", None)
    if source_line is not None:
        provenance["source_line"] = int(source_line)
    return provenance
