"""Deterministic XBRL report identity within a filing (Phase 2B).

``report_key`` is SHA-256 of the canonical JSON encoding of a FilingBundle
``XbrlReportInput``. Extractor version, Arelle version, config, and timestamps
never participate. The identity function is the Python serializer below — never
re-hash a PostgreSQL JSONB round-trip.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from edgar.domain.bundle import InstanceReportInput, IxdsReportInput, XbrlReportInput


def report_input_payload(report_input: XbrlReportInput | Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a report input to the canonical identity payload dict."""
    if isinstance(report_input, (InstanceReportInput, IxdsReportInput)):
        payload = report_input.to_dict()
    else:
        payload = dict(report_input)
    kind = payload.get("kind")
    if kind == "instance":
        uris = payload.get("document_uris")
        if not isinstance(uris, list) or len(uris) != 1:
            raise ValueError("instance report_input requires exactly one document_uri")
        return {"kind": "instance", "document_uris": [str(uris[0])]}
    if kind == "ixds":
        uris = payload.get("document_uris")
        if not isinstance(uris, list) or not uris:
            raise ValueError("ixds report_input requires at least one document_uri")
        target = payload.get("target", "default")
        if target != "default":
            raise ValueError(f"unsupported IXDS target: {target!r}")
        return {
            "kind": "ixds",
            "document_uris": [str(u) for u in uris],
            "target": "default",
        }
    raise ValueError(f"unknown report_input kind: {kind!r}")


def canonical_report_input_json(report_input: XbrlReportInput | Mapping[str, Any]) -> str:
    """Canonical JSON string for report identity (UTF-8 identity bytes via encode)."""
    payload = report_input_payload(report_input)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_report_input_bytes(report_input: XbrlReportInput | Mapping[str, Any]) -> bytes:
    return canonical_report_input_json(report_input).encode("utf-8")


def report_key(report_input: XbrlReportInput | Mapping[str, Any]) -> str:
    """SHA-256 hex digest of the canonical report-input bytes."""
    return hashlib.sha256(canonical_report_input_bytes(report_input)).hexdigest()
