"""Label/reference resource content fingerprints and occurrence records.

``resource_content_hash`` is a deterministic content fingerprint for
comparability: identical canonical content hashes indicate byte-identical
canonical content, not full semantic equivalence. ``resource_occurrence_hash``
identifies one occurrence in one source document.

Serialization contract: xbrl-resource-v1. Any change to canonicalization
rules requires a serialization-version bump.
"""

from __future__ import annotations

from typing import Any

import lxml.etree as etree

from spike_lib import RESOURCE_SERIALIZATION_VERSION
from spike_lib.hashing import sha256_hex, versioned_record_hash
from spike_lib.locators import element_locator, occurrence_provenance

XLINK_ROLE = "{http://www.w3.org/1999/xlink}role"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _ancestor_or_self_lang(element: Any) -> str | None:
    current = element
    while current is not None and isinstance(current.tag, str):
        lang = current.get(XML_LANG)
        if lang is not None:
            return lang or None
        current = current.getparent()
    return None


def canonical_label_text(element: Any) -> str:
    """Exact Unicode text content (NFC as parsed); whitespace preserved."""
    return "".join(element.itertext())


def reference_part_records(resource_element: Any) -> list[dict[str, Any]]:
    """Ordered reference parts with subtree C14N hashes.

    ``part_subtree_c14n_sha256`` is always computed for comparability, not only
    when structured markup is present. C14N here is XML C14N 1.0 inclusive,
    without comments, UTF-8 (lxml ``method="c14n"``).
    """
    parts: list[dict[str, Any]] = []
    for ordinal, child in enumerate(resource_element, start=1):
        if not isinstance(child.tag, str):
            continue
        c14n = etree.tostring(child, method="c14n")
        has_markup = any(isinstance(grand.tag, str) for grand in child.iterdescendants())
        parts.append(
            {
                "part_ordinal": ordinal,
                "part_qname": etree.QName(child.tag).text,
                "text": "".join(child.itertext()),
                "part_subtree_c14n_sha256": sha256_hex(c14n),
                "has_structured_markup": has_markup,
            }
        )
    return parts


def resource_content_record(element: Any, *, resource_type: str) -> dict[str, Any]:
    """Canonical content record for a label or reference resource element."""
    record: dict[str, Any] = {
        "resource_type": resource_type,
        "role_uri": element.get(XLINK_ROLE),
        "lang": _ancestor_or_self_lang(element),
    }
    if resource_type == "label":
        record["text"] = canonical_label_text(element)
    elif resource_type == "reference":
        record["parts"] = reference_part_records(element)
    else:
        raise ValueError(f"unsupported resource_type: {resource_type}")
    return record


def resource_content_hash(content_record: dict[str, Any]) -> str:
    return versioned_record_hash(RESOURCE_SERIALIZATION_VERSION, content_record)


def resource_occurrence_record(element: Any, *, canonical_document_uri: str) -> dict[str, Any]:
    """Occurrence identity for a resource element in one source document."""
    return {
        "document_uri": canonical_document_uri,
        "locator": element_locator(element),
        "provenance": occurrence_provenance(element),
    }


def resource_occurrence_hash(occurrence_record: dict[str, Any]) -> str:
    return versioned_record_hash(RESOURCE_SERIALIZATION_VERSION, occurrence_record)


def serialize_resource(
    element: Any, *, resource_type: str, canonical_document_uri: str
) -> dict[str, Any]:
    """Full resource record: occurrence identity plus canonical content."""
    occurrence = resource_occurrence_record(element, canonical_document_uri=canonical_document_uri)
    content = resource_content_record(element, resource_type=resource_type)
    return {
        "resource_occurrence": occurrence,
        "resource_occurrence_hash": resource_occurrence_hash(occurrence),
        "resource_content": content,
        "resource_content_hash": resource_content_hash(content),
    }
