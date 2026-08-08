"""edgar.ingestion package."""

from edgar.ingestion.acquisition import AcquisitionResult, AcquisitionService
from edgar.ingestion.catalog import CatalogService
from edgar.ingestion.payload import PAYLOAD_HASH_SCHEMA, compute_payload_hash, payload_hash_bytes
from edgar.ingestion.report_input import (
    UnsupportedReportInput,
    identify_report_input,
    is_inline_xbrl,
    is_xbrl_instance,
)

__all__ = [
    "AcquisitionResult",
    "AcquisitionService",
    "CatalogService",
    "PAYLOAD_HASH_SCHEMA",
    "UnsupportedReportInput",
    "compute_payload_hash",
    "identify_report_input",
    "is_inline_xbrl",
    "is_xbrl_instance",
    "payload_hash_bytes",
]
