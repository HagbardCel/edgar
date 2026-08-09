"""Versioned document-projection configuration and identity fingerprint."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import lxml.etree as etree

DOCUMENT_CONFIG_SCHEMA = "document-config-v1"

DOCUMENT_PROJECTION_VERSION = "document-html-v1"
BLOCK_EXTRACTOR_VERSION = "block-extractor-v1"
NORMALIZATION_VERSION = "whitespace-v1"
SECTION_EXTRACTOR_VERSION = "sec-item-sequence-v1"
SOURCE_LOCATOR_VERSION = "html-xpath-v1"
TABLE_TEXT_VERSION = "row-cell-v1"
TABLE_LAYOUT_VERSION = "table-layout-v1"


@dataclass(frozen=True)
class DocumentConfig:
    """Every interpretation-affecting knob of one document projection run."""

    parser_version: str
    block_extractor: str
    normalization: str
    section_extractor: str
    source_locator: str
    table_text: str
    table_layout: str
    lxml_version: str
    libxml2_version: str

    def __post_init__(self) -> None:
        for name in (
            "parser_version",
            "block_extractor",
            "normalization",
            "section_extractor",
            "source_locator",
            "table_text",
            "table_layout",
            "lxml_version",
            "libxml2_version",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "parser_version": self.parser_version,
            "block_extractor": self.block_extractor,
            "normalization": self.normalization,
            "section_extractor": self.section_extractor,
            "source_locator": self.source_locator,
            "table_text": self.table_text,
            "table_layout": self.table_layout,
            "lxml_version": self.lxml_version,
            "libxml2_version": self.libxml2_version,
        }


def _runtime_versions() -> tuple[str, str]:
    lxml_version = getattr(etree, "__version__", "") or "unknown"
    libxml2_version = ""
    try:
        libxml2_version = str(etree.LIBXML_VERSION)
        if isinstance(etree.LIBXML_VERSION, tuple):
            libxml2_version = ".".join(str(part) for part in etree.LIBXML_VERSION)
    except Exception:  # noqa: BLE001 — defensive around C extension metadata
        libxml2_version = "unknown"
    return lxml_version, libxml2_version or "unknown"


def build_document_config(
    *,
    parser_version: str = DOCUMENT_PROJECTION_VERSION,
    block_extractor: str = BLOCK_EXTRACTOR_VERSION,
    normalization: str = NORMALIZATION_VERSION,
    section_extractor: str = SECTION_EXTRACTOR_VERSION,
    source_locator: str = SOURCE_LOCATOR_VERSION,
    table_text: str = TABLE_TEXT_VERSION,
    table_layout: str = TABLE_LAYOUT_VERSION,
    lxml_version: str | None = None,
    libxml2_version: str | None = None,
) -> DocumentConfig:
    """Build active document configuration; runtime versions captured at call time."""
    runtime_lxml, runtime_libxml2 = _runtime_versions()
    return DocumentConfig(
        parser_version=parser_version,
        block_extractor=block_extractor,
        normalization=normalization,
        section_extractor=section_extractor,
        source_locator=source_locator,
        table_text=table_text,
        table_layout=table_layout,
        lxml_version=lxml_version if lxml_version is not None else runtime_lxml,
        libxml2_version=libxml2_version if libxml2_version is not None else runtime_libxml2,
    )


def document_config_fingerprint_bytes(config: DocumentConfig) -> bytes:
    envelope = {"config": config.to_dict(), "schema": DOCUMENT_CONFIG_SCHEMA}
    return json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def document_config_fingerprint(config: DocumentConfig) -> str:
    return hashlib.sha256(document_config_fingerprint_bytes(config)).hexdigest()
