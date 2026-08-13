"""Unit tests for corpus manifest and acceptance helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from edgar.corpus_acceptance import (
    is_standard_taxonomy_namespace,
    parse_us_gaap_taxonomy_year,
    resolve_published_bundle,
)
from edgar.corpus_manifest import load_corpus_manifest
from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.ingestion.payload import compute_payload_hash
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORPUS_TOML = _REPO_ROOT / "fixtures" / "corpus.toml"


def test_load_default_corpus_toml() -> None:
    manifest = load_corpus_manifest(_CORPUS_TOML)
    assert len(manifest.filings) == 5
    roles = {f.role for f in manifest.filings}
    assert roles == {"base_10k", "amendment_10ka", "second_10k", "first_10q", "second_10q"}


def test_corpus_manifest_rejects_empty_filings(tmp_path: Path) -> None:
    path = tmp_path / "empty.toml"
    path.write_text("[filings]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty filings"):
        load_corpus_manifest(path)


def test_corpus_manifest_rejects_duplicate_accession(tmp_path: Path) -> None:
    path = tmp_path / "dup.toml"
    path.write_text(
        """
[[filings]]
role = "a"
company = "A Co"
cik = "0000000001"
accession = "0000000001-00-000001"
form = "10-K"
industry_group = "tech"

[[filings]]
role = "b"
company = "B Co"
cik = "0000000002"
accession = "0000000001-00-000001"
form = "10-Q"
industry_group = "tech"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate accession"):
        load_corpus_manifest(path)


def test_corpus_manifest_amends_must_be_in_corpus(tmp_path: Path) -> None:
    path = tmp_path / "amends.toml"
    path.write_text(
        """
[[filings]]
role = "amendment_10ka"
company = "A Co"
cik = "0000000001"
accession = "0000000001-00-000002"
form = "10-K/A"
industry_group = "tech"
amends = "0000000001-00-000099"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not present in this corpus"):
        load_corpus_manifest(path)


def test_is_standard_taxonomy_namespace_uses_hostname() -> None:
    assert is_standard_taxonomy_namespace("http://fasb.org/us-gaap/2024")
    assert is_standard_taxonomy_namespace("https://www.xbrl.org/2003/instance")
    assert not is_standard_taxonomy_namespace("http://example.com/issuer/2024")
    assert not is_standard_taxonomy_namespace("http://evil-fasb.org/us-gaap/2024")


def test_parse_us_gaap_taxonomy_year_strict() -> None:
    assert parse_us_gaap_taxonomy_year("http://fasb.org/us-gaap/2024") == 2024
    assert parse_us_gaap_taxonomy_year("http://fasb.org/us-gaap/2023-01-31") == 2023
    assert parse_us_gaap_taxonomy_year("http://fasb.org/srt/2024") is None
    assert parse_us_gaap_taxonomy_year("http://example.com/us-gaap/2024") is None


def _minimal_bundle(store: ObjectStore, *, content: bytes = b"x") -> FilingBundle:
    obj = store.put_bytes(content)
    art = BundleArtifact(
        logical_path="accession/a.xml",
        content=ContentObject(sha256=obj.sha256, byte_size=len(content)),
        artifact_kind="attachment",
        required=True,
    )
    filing = FilingIdentity(
        cik="0000000001",
        accession="0000000001-00-000001",
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        accepted_at=datetime(2024, 1, 2, tzinfo=UTC),
        report_period_end=date(2023, 12, 31),
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


def test_resolve_published_bundle_zero_one_many(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    repo = BundleRepository(tmp_path, store)

    missing = resolve_published_bundle(repo, "0000000001", "0000000001-00-000001")
    assert missing.error is not None
    assert missing.bundle_dir is None

    repo.publish(_minimal_bundle(store, content=b"one"))
    one = resolve_published_bundle(repo, "0000000001", "0000000001-00-000001")
    assert one.error is None
    assert one.bundle_dir is not None

    repo.publish(_minimal_bundle(store, content=b"two"))
    many = resolve_published_bundle(repo, "0000000001", "0000000001-00-000001")
    assert many.error is not None
    assert "ambiguous" in many.error
    assert len(many.candidates) == 2
