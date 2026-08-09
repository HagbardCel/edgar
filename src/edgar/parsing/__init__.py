"""Document parsing package: deterministic HTML blocks and regulatory sections."""

from edgar.parsing.config import (
    DOCUMENT_PROJECTION_VERSION,
    DocumentConfig,
    build_document_config,
    document_config_fingerprint,
)
from edgar.parsing.html import parse_html_document
from edgar.parsing.records import (
    DocumentBlockRecord,
    DocumentIssueRecord,
    DocumentParseError,
    DocumentProjectionData,
    FilingSectionRecord,
    ParsedDocument,
    SectionSignal,
    document_projection_equality_state,
)
from edgar.parsing.sections import extract_filing_sections

__all__ = [
    "DOCUMENT_PROJECTION_VERSION",
    "DocumentBlockRecord",
    "DocumentConfig",
    "DocumentIssueRecord",
    "DocumentParseError",
    "DocumentProjectionData",
    "FilingSectionRecord",
    "ParsedDocument",
    "SectionSignal",
    "build_document_config",
    "document_config_fingerprint",
    "document_projection_equality_state",
    "extract_filing_sections",
    "parse_html_document",
]
