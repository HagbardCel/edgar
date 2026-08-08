"""Unit tests for bundle structure/integrity and publication directory policy."""

from __future__ import annotations

import json
import uuid
from datetime import date
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
from edgar.domain.payload import compute_payload_hash
from edgar.domain.uri import UriIdentityError, normalize_uri
from edgar.domain.validation import BundleStructureError, validate_bundle_structure
from edgar.storage.bundles import BundleRepository, BundleStorageError, validate_bundle_integrity
from edgar.storage.objects import ObjectStore


def _bundle_for(store: ObjectStore, data: bytes = b"x") -> FilingBundle:
    obj = store.put_bytes(data)
    art = BundleArtifact(
        logical_path="accession/a.xml",
        content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
        artifact_kind="attachment",
        required=True,
    )
    filing = FilingIdentity(
        cik="0001065088",
        accession="0001065088-24-000036",
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        accepted_at=None,
        report_period_end=None,
        primary_document="a.htm",
    )
    return FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash([art]),
        artifacts=(art,),
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/a.xml",)),),
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/a.xml",
                artifact_path="accession/a.xml",
                content_sha256=obj.sha256,
            ),
        ),
    )


def test_ipv6_literal_rejected_by_uri_identity() -> None:
    with pytest.raises(UriIdentityError, match="IPv6"):
        normalize_uri("https://[2001:db8::1]/")


def test_noncanonical_cik_rejected_on_load() -> None:
    with pytest.raises(Exception, match="noncanonical"):
        FilingIdentity.from_dict(
            {
                "cik": "1065088",
                "accession": "0001065088-24-000036",
                "form_type": "10-K",
                "filing_date": "2024-01-01",
                "accepted_at": None,
                "report_period_end": None,
                "primary_document": "a.htm",
            }
        )


def test_uri_binding_rejects_uppercase_digest() -> None:
    with pytest.raises(ValueError, match="lowercase"):
        UriBinding(
            document_uri="https://example.com/a.xml",
            artifact_path="accession/a.xml",
            content_sha256=("AB" * 32),
        )


def test_uri_binding_rejects_duplicate_aliases() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        UriBinding(
            document_uri="https://example.com/a.xml",
            artifact_path="accession/a.xml",
            content_sha256="ab" * 32,
            replay_aliases=("https://example.com/b", "https://example.com/b"),
        )


def test_structure_rejects_bad_payload_hash(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    bundle = _bundle_for(store)
    bad = FilingBundle(
        filing=bundle.filing,
        payload_hash="00" * 32,
        artifacts=bundle.artifacts,
        report_inputs=bundle.report_inputs,
        uri_bindings=bundle.uri_bindings,
    )
    with pytest.raises(BundleStructureError, match="payload_hash"):
        validate_bundle_structure(bad)


def test_structure_rejects_missing_report_input_binding(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    bundle = _bundle_for(store)
    bad = FilingBundle(
        filing=bundle.filing,
        payload_hash=bundle.payload_hash,
        artifacts=bundle.artifacts,
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/missing.xml",)),),
        uri_bindings=bundle.uri_bindings,
    )
    with pytest.raises(BundleStructureError, match="report-input"):
        validate_bundle_structure(bad)


def test_integrity_missing_cas(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    art = BundleArtifact(
        logical_path="accession/a.xml",
        content=ContentObject(sha256="ab" * 32, byte_size=1),
        artifact_kind="attachment",
        required=True,
    )
    bundle = FilingBundle(
        filing=FilingIdentity(
            cik="0001065088",
            accession="0001065088-24-000036",
            form_type="10-K",
            filing_date=date(2024, 1, 1),
            accepted_at=None,
            report_period_end=None,
            primary_document="a.htm",
        ),
        payload_hash=compute_payload_hash([art]),
        artifacts=(art,),
        report_inputs=(InstanceReportInput(document_uris=("https://example.com/a.xml",)),),
        uri_bindings=(
            UriBinding(
                document_uri="https://example.com/a.xml",
                artifact_path="accession/a.xml",
                content_sha256="ab" * 32,
            ),
        ),
    )
    with pytest.raises(BundleStorageError, match="missing CAS"):
        validate_bundle_integrity(bundle, store)


def test_staging_not_listed_as_published(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    repo = BundleRepository(tmp_path, store)
    bundle = _bundle_for(store)
    root = tmp_path / "bundles" / bundle.filing.cik / bundle.filing.accession
    staging = root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    (staging / "bundle.json").write_text(json.dumps(bundle.to_dict()), encoding="utf-8")
    assert repo.list_published(bundle.filing.cik, bundle.filing.accession) == []


def test_unexpected_directory_fails_closed(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    repo = BundleRepository(tmp_path, store)
    bundle = _bundle_for(store)
    root = tmp_path / "bundles" / bundle.filing.cik / bundle.filing.accession
    weird = root / "not-a-uuid"
    weird.mkdir(parents=True)
    (weird / "bundle.json").write_text(json.dumps(bundle.to_dict()), encoding="utf-8")
    with pytest.raises(BundleStorageError, match="unexpected directory"):
        repo.list_published(bundle.filing.cik, bundle.filing.accession)


def test_path_cik_accession_mismatch(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    repo = BundleRepository(tmp_path, store)
    published = repo.publish(_bundle_for(store))
    # Move descriptor content under wrong accession path by rewriting filing in place.
    data = json.loads((published.bundle_dir / "bundle.json").read_text(encoding="utf-8"))
    data["filing"]["accession"] = "0001065088-24-000099"
    (published.bundle_dir / "bundle.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BundleStorageError, match="does not match"):
        repo.list_published("0001065088", "0001065088-24-000036")


def test_strict_decode_rejects_string_byte_size(tmp_path: Path) -> None:
    from edgar.domain.decode import BundleDecodeError

    store = ObjectStore(tmp_path)
    data = _bundle_for(store).to_dict()
    data["artifacts"][0]["byte_size"] = "1"
    with pytest.raises(BundleDecodeError, match="byte_size"):
        FilingBundle.from_dict(data)


def test_strict_decode_rejects_string_schema_version(tmp_path: Path) -> None:
    from edgar.domain.decode import BundleDecodeError

    store = ObjectStore(tmp_path)
    data = _bundle_for(store).to_dict()
    data["schema_version"] = "1"
    with pytest.raises(BundleDecodeError, match="schema_version"):
        FilingBundle.from_dict(data)


def test_strict_decode_rejects_bool_as_schema_version(tmp_path: Path) -> None:
    from edgar.domain.decode import BundleDecodeError

    store = ObjectStore(tmp_path)
    data = _bundle_for(store).to_dict()
    data["schema_version"] = True
    with pytest.raises(BundleDecodeError, match="schema_version"):
        FilingBundle.from_dict(data)


def test_strict_decode_rejects_string_required(tmp_path: Path) -> None:
    from edgar.domain.decode import BundleDecodeError

    store = ObjectStore(tmp_path)
    data = _bundle_for(store).to_dict()
    data["artifacts"][0]["required"] = "false"
    with pytest.raises(BundleDecodeError, match="required"):
        FilingBundle.from_dict(data)


def test_strict_decode_rejects_empty_accepted_at(tmp_path: Path) -> None:
    from edgar.domain.decode import BundleDecodeError

    store = ObjectStore(tmp_path)
    data = _bundle_for(store).to_dict()
    data["filing"]["accepted_at"] = ""
    with pytest.raises(BundleDecodeError, match="accepted_at"):
        FilingBundle.from_dict(data)


def test_strict_decode_rejects_missing_ixds_target(tmp_path: Path) -> None:
    from edgar.domain.bundle import report_input_from_dict
    from edgar.domain.decode import BundleDecodeError

    with pytest.raises(BundleDecodeError, match="target|missing"):
        report_input_from_dict({"kind": "ixds", "document_uris": ["https://example.com/a.htm"]})


def test_strict_decode_rejects_wrong_ixds_target() -> None:
    from edgar.domain.bundle import report_input_from_dict
    from edgar.domain.decode import BundleDecodeError

    with pytest.raises(BundleDecodeError, match="target"):
        report_input_from_dict(
            {
                "kind": "ixds",
                "document_uris": ["https://example.com/a.htm"],
                "target": "other",
            }
        )


def test_strict_decode_rejects_unknown_nested_field(tmp_path: Path) -> None:
    from edgar.domain.decode import BundleDecodeError

    store = ObjectStore(tmp_path)
    data = _bundle_for(store).to_dict()
    data["filing"]["extra"] = "nope"
    with pytest.raises(BundleDecodeError, match="unknown"):
        FilingBundle.from_dict(data)


def test_strict_decode_rejects_invalid_artifact_kind(tmp_path: Path) -> None:
    from edgar.domain.decode import BundleDecodeError

    store = ObjectStore(tmp_path)
    data = _bundle_for(store).to_dict()
    data["artifacts"][0]["artifact_kind"] = "not-a-kind"
    with pytest.raises(BundleDecodeError, match="artifact_kind"):
        FilingBundle.from_dict(data)
