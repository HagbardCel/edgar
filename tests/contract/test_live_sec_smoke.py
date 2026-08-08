"""Opt-in live SEC acquisition smoke test."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from edgar.config import Settings
from edgar.ingestion.acquisition import AcquisitionService

EBAY_ACCESSION = "0001065088-24-000036"


@pytest.mark.network
def test_live_ebay_retrieve_and_reuse(tmp_path: Path) -> None:
    if not os.environ.get("SEC_USER_AGENT"):
        pytest.skip("SEC_USER_AGENT required for live SEC test")
    settings = Settings().model_copy(update={"edgar_data_root": tmp_path})
    with AcquisitionService(settings) as service:
        first = service.acquire(EBAY_ACCESSION)
        second = service.acquire(EBAY_ACCESSION)
    assert first.replay_faithful
    assert first.publish.reused is False
    assert second.publish.reused is True
    assert first.publish.opaque_id == second.publish.opaque_id
    assert len(first.bundle.report_inputs) == 1
    assert first.bundle.report_inputs[0].document_uris
