"""Unit tests for corpus manifest and acceptance helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from edgar.corpus_acceptance import (
    CorpusProjection,
    evaluate_class_a_requirements,
    is_standard_taxonomy_namespace,
    parse_us_gaap_taxonomy_year,
    resolve_published_bundle,
    validate_corpus_bundle_identity,
)
from edgar.corpus_manifest import CorpusManifest, load_corpus_manifest
from edgar.domain.bundle import (
    ACQUISITION_POLICY_VERSION,
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

_MINIMAL_CORPUS = """
acquisition_policy_version = "acq-v1"

[[filings]]
role = "base_10k"
company = "A Co"
cik = "0000000001"
accession = "0000000001-00-000001"
form = "10-K"
industry_group = "tech"
"""


def test_load_default_corpus_toml() -> None:
    manifest = load_corpus_manifest(_CORPUS_TOML)
    assert manifest.acquisition_policy_version == ACQUISITION_POLICY_VERSION
    assert len(manifest.filings) == 6
    roles = {f.role for f in manifest.filings}
    assert roles == {
        "prior_ebay_10k",
        "base_10k",
        "amendment_10ka",
        "second_10k",
        "first_10q",
        "second_10q",
    }
    assert manifest.coverage_notes is not None
    base = next(f for f in manifest.filings if f.role == "base_10k")
    assert base.filed == date(2024, 2, 28)
    assert base.reason is not None


def test_corpus_manifest_rejects_empty_filings(tmp_path: Path) -> None:
    path = tmp_path / "empty.toml"
    path.write_text('acquisition_policy_version = "acq-v1"\nfilings = []\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_corpus_manifest(path)


def test_corpus_manifest_rejects_missing_required_field(tmp_path: Path) -> None:
    path = tmp_path / "missing-role.toml"
    path.write_text(
        """
acquisition_policy_version = "acq-v1"

[[filings]]
company = "A Co"
cik = "0000000001"
accession = "0000000001-00-000001"
form = "10-K"
industry_group = "tech"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_corpus_manifest(path)


def test_corpus_manifest_rejects_invalid_cik(tmp_path: Path) -> None:
    path = tmp_path / "bad-cik.toml"
    path.write_text(
        _MINIMAL_CORPUS.replace('cik = "0000000001"', 'cik = "bad"'),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_corpus_manifest(path)


def test_corpus_manifest_rejects_invalid_accession(tmp_path: Path) -> None:
    path = tmp_path / "bad-accession.toml"
    path.write_text(
        _MINIMAL_CORPUS.replace(
            'accession = "0000000001-00-000001"',
            'accession = "0000000001-00-000001-extra"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_corpus_manifest(path)


def test_corpus_manifest_rejects_cik_accession_inconsistency(tmp_path: Path) -> None:
    path = tmp_path / "cik-mismatch.toml"
    path.write_text(
        _MINIMAL_CORPUS.replace('cik = "0000000001"', 'cik = "0000000002"'),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_corpus_manifest(path)


def test_corpus_manifest_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    path = tmp_path / "unknown-key.toml"
    path.write_text(
        _MINIMAL_CORPUS + '\nunexpected = "value"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_corpus_manifest(path)


def test_corpus_manifest_rejects_wrong_acquisition_policy_version(tmp_path: Path) -> None:
    path = tmp_path / "bad-policy.toml"
    path.write_text(
        _MINIMAL_CORPUS.replace(
            'acquisition_policy_version = "acq-v1"',
            'acquisition_policy_version = "acq-v0"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="acquisition_policy_version"):
        load_corpus_manifest(path)


def test_corpus_manifest_rejects_duplicate_accession(tmp_path: Path) -> None:
    path = tmp_path / "dup.toml"
    path.write_text(
        """
acquisition_policy_version = "acq-v1"

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
cik = "0000000001"
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
acquisition_policy_version = "acq-v1"

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


def test_corpus_manifest_amendment_requires_amends(tmp_path: Path) -> None:
    path = tmp_path / "amendment-no-amends.toml"
    path.write_text(
        """
acquisition_policy_version = "acq-v1"

[[filings]]
role = "amendment_10ka"
company = "A Co"
cik = "0000000001"
accession = "0000000001-00-000002"
form = "10-K/A"
industry_group = "tech"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requires amends"):
        load_corpus_manifest(path)


def test_corpus_manifest_amends_requires_amendment_form(tmp_path: Path) -> None:
    path = tmp_path / "amends-non-amendment.toml"
    path.write_text(
        """
acquisition_policy_version = "acq-v1"

[[filings]]
role = "base_10k"
company = "A Co"
cik = "0000000001"
accession = "0000000001-00-000001"
form = "10-K"
industry_group = "tech"
amends = "0000000001-00-000099"

[[filings]]
role = "other"
company = "B Co"
cik = "0000000002"
accession = "0000000001-00-000099"
form = "10-Q"
industry_group = "tech"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="requires an amendment form"):
        load_corpus_manifest(path)


def test_evaluate_class_a_counts_actual_forms_not_roles() -> None:
    projections = (
        CorpusProjection(
            role="base_10k",
            company="Wrong Co",
            cik="0000000001",
            accession="0000000001-00-000001",
            form="10-Q",
            industry_group="tech",
            bundle_id=1,
            semantic_projection_id=1,
            document_projection_id=1,
        ),
        CorpusProjection(
            role="second_10k",
            company="Real 10-K",
            cik="0000000002",
            accession="0000000002-00-000001",
            form="10-K",
            industry_group="retail",
            bundle_id=2,
            semantic_projection_id=2,
            document_projection_id=2,
        ),
    )
    empty = {
        "used_extension_concept_count": 1,
        "dimension_count": 1,
        "distinct_presentation_role_count": 2,
        "has_taxonomy_transition": True,
    }
    result = evaluate_class_a_requirements(
        projections,
        extension=empty,
        dimensions=empty,
        presentation_roles=empty,
        taxonomy=empty,
    )
    assert result["checks"]["two_10k"] is False


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


def _minimal_bundle(
    store: ObjectStore,
    *,
    content: bytes = b"x",
    form_type: str = "10-K",
    filing_date: date = date(2024, 1, 1),
) -> FilingBundle:
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
        form_type=form_type,
        filing_date=filing_date,
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


def test_validate_corpus_bundle_identity_detects_form_mismatch(tmp_path: Path) -> None:
    manifest = CorpusManifest.model_validate(
        {
            "acquisition_policy_version": ACQUISITION_POLICY_VERSION,
            "filings": [
                {
                    "role": "base_10k",
                    "company": "A Co",
                    "cik": "0000000001",
                    "accession": "0000000001-00-000001",
                    "form": "10-K",
                    "industry_group": "tech",
                    "filed": "2024-01-01",
                }
            ],
        }
    )
    filing = manifest.filings[0]
    store = ObjectStore(tmp_path)
    bundle = _minimal_bundle(store, form_type="10-Q")
    issues = validate_corpus_bundle_identity(
        filing,
        bundle,
        manifest,
        source="/tmp/bundle",
    )
    assert any(issue.code == "FORM_MISMATCH" for issue in issues)


def test_resolve_published_bundle_zero_one_many(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    repo = BundleRepository(tmp_path, store)

    missing = resolve_published_bundle(repo, "0000000001", "0000000001-00-000001")
    assert missing.error is not None
    assert missing.error_code == "BUNDLE_NOT_FOUND"
    assert missing.bundle_dir is None

    repo.publish(_minimal_bundle(store, content=b"one"))
    one = resolve_published_bundle(repo, "0000000001", "0000000001-00-000001")
    assert one.error is None
    assert one.bundle_dir is not None

    repo.publish(_minimal_bundle(store, content=b"two"))
    many = resolve_published_bundle(repo, "0000000001", "0000000001-00-000001")
    assert many.error is not None
    assert many.error_code == "AMBIGUOUS_BUNDLE"
    assert "ambiguous" in many.error
    assert len(many.candidates) == 2
