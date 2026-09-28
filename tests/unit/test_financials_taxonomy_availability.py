"""Captured DTS closure taxonomy availability for quality reporting."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.financials.taxonomy_availability import (
    TaxonomyAvailabilityError,
    _availability_from_bundle,
    load_filing_taxonomy_availability,
    parse_taxonomy_schema_bytes,
)
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore

_NS_GAAP = "http://fasb.org/us-gaap/2024"
_NS_ISSUER = "http://example.com/issuer/2024"
_REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"
_ACCESSION = "0001065088-24-000036"
_CIK = "0001065088"


def _schema(target: str, local_names: tuple[str, ...]) -> bytes:
    elements = "\n".join(f'  <xs:element name="{name}" type="xs:string"/>' for name in local_names)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="{target}"
           elementFormDefault="qualified">
{elements}
</xs:schema>
""".encode()


def _publish_closure_bundle(
    tmp_path: Path,
    *,
    issuer_sha: str,
    external_sha: str,
    issuer_bytes: int,
    external_bytes: int,
    issuer_path: str = "taxonomy/issuer-extension.xsd",
) -> None:
    store = ObjectStore(tmp_path)
    instance = store.put_bytes(b"<html/>")
    filing = FilingIdentity(
        cik=_CIK,
        accession=_ACCESSION,
        form_type="10-K",
        filing_date=date(2024, 2, 1),
        accepted_at=datetime(2024, 2, 1, tzinfo=UTC),
        report_period_end=date(2023, 12, 31),
        primary_document="a.htm",
    )
    instance_art = BundleArtifact(
        logical_path="accession/a.htm",
        content=ContentObject(sha256=instance.sha256, byte_size=instance.byte_size),
        artifact_kind="primary_document",
        required=True,
    )
    issuer_art = BundleArtifact(
        logical_path=issuer_path,
        content=ContentObject(sha256=issuer_sha, byte_size=issuer_bytes),
        artifact_kind="taxonomy_schema",
        required=True,
    )
    external_art = BundleArtifact(
        logical_path="taxonomy/us-gaap-2024.xsd",
        content=ContentObject(sha256=external_sha, byte_size=external_bytes),
        artifact_kind="external",
        required=True,
    )
    bundle = FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash((instance_art, issuer_art, external_art)),
        artifacts=(instance_art, issuer_art, external_art),
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/a.htm",)),),
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/a.htm",
                artifact_path="accession/a.htm",
                content_sha256=instance.sha256,
            ),
            UriBinding(
                document_uri="https://example.com/issuer-extension.xsd",
                artifact_path=issuer_path,
                content_sha256=issuer_sha,
            ),
            UriBinding(
                document_uri="https://fasb.org/us-gaap/2024/elts.xsd",
                artifact_path="taxonomy/us-gaap-2024.xsd",
                content_sha256=external_sha,
            ),
        ),
    )
    BundleRepository(tmp_path, store).publish(bundle)


def test_schema_parser_collects_target_namespace_elements() -> None:
    target, concepts = parse_taxonomy_schema_bytes(_schema(_NS_GAAP, ("Foo", "Bar")))
    assert target == _NS_GAAP
    assert concepts == frozenset({(_NS_GAAP, "Foo"), (_NS_GAAP, "Bar")})


def test_external_closure_schema_makes_us_gaap_concepts_available(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    issuer = store.put_bytes(_schema(_NS_ISSUER, ("IssuerRevenue",)))
    external = store.put_bytes(_schema(_NS_GAAP, (_REVENUE,)))
    _publish_closure_bundle(
        tmp_path,
        issuer_sha=issuer.sha256,
        external_sha=external.sha256,
        issuer_bytes=issuer.byte_size,
        external_bytes=external.byte_size,
    )
    availability = load_filing_taxonomy_availability(tmp_path, _CIK, _ACCESSION)
    assert availability.filing_taxonomy_release == "2024"
    assert (_NS_GAAP, _REVENUE) in availability.concepts
    assert external.sha256 in availability.schema_sha256s


def test_missing_cas_object_is_not_treated_as_concept_absence(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    issuer = store.put_bytes(_schema(_NS_ISSUER, ("IssuerRevenue",)))
    external = store.put_bytes(_schema(_NS_GAAP, (_REVENUE,)))
    missing = "f" * 64
    with pytest.raises(TaxonomyAvailabilityError, match="missing CAS object"):
        _availability_from_bundle(
            store,
            "10-K",
            (issuer.sha256, missing, external.sha256),
        )


def test_malformed_schema_bytes_fail_closed() -> None:
    with pytest.raises(TaxonomyAvailabilityError, match="not well-formed"):
        parse_taxonomy_schema_bytes(b"<not-xml")


def test_no_published_bundle_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(TaxonomyAvailabilityError, match="no published FilingBundle"):
        load_filing_taxonomy_availability(tmp_path, _CIK, _ACCESSION)


def test_annual_without_us_gaap_schema_fails_closed(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    issuer = store.put_bytes(_schema(_NS_ISSUER, ("IssuerRevenue",)))
    with pytest.raises(TaxonomyAvailabilityError, match="no captured US-GAAP"):
        _availability_from_bundle(store, "10-K", (issuer.sha256,))


def test_multiple_published_bundles_fail_closed(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    issuer = store.put_bytes(_schema(_NS_ISSUER, ("IssuerRevenue",)))
    external = store.put_bytes(_schema(_NS_GAAP, (_REVENUE,)))
    _publish_closure_bundle(
        tmp_path,
        issuer_sha=issuer.sha256,
        external_sha=external.sha256,
        issuer_bytes=issuer.byte_size,
        external_bytes=external.byte_size,
    )
    alt_issuer = store.put_bytes(_schema(_NS_ISSUER, ("IssuerRevenue", "Alt")))
    _publish_closure_bundle(
        tmp_path,
        issuer_sha=alt_issuer.sha256,
        external_sha=external.sha256,
        issuer_bytes=alt_issuer.byte_size,
        external_bytes=external.byte_size,
        issuer_path="taxonomy/issuer-extension-alt.xsd",
    )
    with pytest.raises(TaxonomyAvailabilityError, match="exactly one"):
        load_filing_taxonomy_availability(tmp_path, _CIK, _ACCESSION)
