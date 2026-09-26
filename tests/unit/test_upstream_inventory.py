"""Upstream raw inventory scanner (M1A-3)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    IxdsReportInput,
    UriBinding,
)
from edgar.domain.payload import compute_payload_hash
from edgar.storage.objects import ObjectStore
from edgar.xbrl.upstream_inventory import (
    InventoryFailure,
    InventorySuccess,
    build_inventory_outcomes,
    ixds_membership_key,
)


def _instance_bundle(store: ObjectStore, xml: bytes) -> FilingBundle:
    obj = store.put_bytes(xml)
    path = "accession/a.xml"
    uri = "https://example.com/a.xml"
    filing = FilingIdentity(
        cik="0000000001",
        accession="0000000001-24-000001",
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        accepted_at=None,
        report_period_end=date(2023, 12, 31),
        primary_document="a.xml",
    )
    artifacts = (
        BundleArtifact(
            logical_path=path,
            content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
            artifact_kind="instance",
            required=True,
        ),
    )
    return FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(InstanceReportInput(document_uris=(uri,)),),
        uri_bindings=(
            UriBinding(
                document_uri=uri,
                artifact_path=path,
                content_sha256=obj.sha256,
                replay_aliases=(),
            ),
        ),
    )


_INSTANCE_TWO_FACTS = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:t="http://example.com/test">
  <xbrli:context id="c1">
    <xbrli:entity>
      <xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <t:Assets contextRef="c1" id="f1">1</t:Assets>
  <t:Assets contextRef="c1" id="f2">2</t:Assets>
</xbrli:xbrl>
"""


def test_instance_inventory_item_count(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "data")
    bundle = _instance_bundle(store, _INSTANCE_TWO_FACTS)
    outcomes = build_inventory_outcomes(bundle, store)
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert isinstance(outcome, InventorySuccess)
    assert outcome.inventory.selected_target_item_count == 2


def test_ixds_membership_key_normalizes_uri_order() -> None:
    a = IxdsReportInput(document_uris=("https://example.com/b.htm", "https://example.com/a.htm"))
    b = IxdsReportInput(document_uris=("https://example.com/a.htm", "https://example.com/b.htm"))
    assert ixds_membership_key(a) == ixds_membership_key(b)


def test_context_collision_fan_out(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "data2")
    dup_ctx = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="dup"/>
  <xbrli:context id="dup"/>
  <ix:nonNumeric name="t:Foo" contextRef="dup">x</ix:nonNumeric>
</html>
"""
    obj = store.put_bytes(dup_ctx)
    path = "accession/inline.htm"
    uri = "https://example.com/inline.htm"
    filing = FilingIdentity(
        cik="0000000001",
        accession="0000000001-24-000002",
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        accepted_at=None,
        report_period_end=date(2023, 12, 31),
        primary_document="inline.htm",
    )
    artifacts = (
        BundleArtifact(
            logical_path=path,
            content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
    )
    bundle = FilingBundle(
        filing=filing,
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(IxdsReportInput(document_uris=(uri,), target="default"),),
        uri_bindings=(
            UriBinding(
                document_uri=uri,
                artifact_path=path,
                content_sha256=obj.sha256,
                replay_aliases=(),
            ),
        ),
    )
    outcomes = build_inventory_outcomes(bundle, store)
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], InventoryFailure)
    assert outcomes[0].code == "CONTEXT_ID_COLLISION"
    assert "first=" in outcomes[0].message
    assert "second=" in outcomes[0].message
    # Same document: distinct element paths, not coarse (path, "context") placeholders.
    import re

    paths = re.findall(r"\('([^']+)', '([^']+)'\)", outcomes[0].message)
    assert len(paths) >= 2
    assert paths[0] != paths[1]


def test_comment_and_pi_do_not_crash_scan(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "c")
    xml = b"""<?xml version="1.0"?>
<!-- comment -->
<?pi data?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:nonNumeric name="t:Foo" contextRef="c1">x</ix:nonNumeric>
</html>
"""
    obj = store.put_bytes(xml)
    uri = "https://example.com/inline.htm"
    bundle = FilingBundle(
        filing=FilingIdentity(
            cik="0000000001",
            accession="0000000001-24-000003",
            form_type="10-K",
            filing_date=date(2024, 1, 1),
            accepted_at=None,
            report_period_end=date(2023, 12, 31),
            primary_document="inline.htm",
        ),
        payload_hash=compute_payload_hash(
            (
                BundleArtifact(
                    logical_path="a.htm",
                    content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
                    artifact_kind="primary_document",
                    required=True,
                ),
            )
        ),
        artifacts=(
            BundleArtifact(
                logical_path="a.htm",
                content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
                artifact_kind="primary_document",
                required=True,
            ),
        ),
        report_inputs=(IxdsReportInput(document_uris=(uri,), target="default"),),
        uri_bindings=(
            UriBinding(
                document_uri=uri,
                artifact_path="a.htm",
                content_sha256=obj.sha256,
                replay_aliases=(),
            ),
        ),
    )
    outcomes = build_inventory_outcomes(bundle, store)
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], InventorySuccess)


def test_foreign_namespace_non_numeric_not_counted(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "f")
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:foo="http://example.com/not-inline">
  <foo:nonNumeric contextRef="c1">x</foo:nonNumeric>
</html>
"""
    obj = store.put_bytes(xml)
    uri = "https://example.com/inline.htm"
    bundle = FilingBundle(
        filing=FilingIdentity(
            cik="0000000001",
            accession="0000000001-24-000004",
            form_type="10-K",
            filing_date=date(2024, 1, 1),
            accepted_at=None,
            report_period_end=date(2023, 12, 31),
            primary_document="inline.htm",
        ),
        payload_hash=compute_payload_hash(
            (
                BundleArtifact(
                    logical_path="a.htm",
                    content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
                    artifact_kind="primary_document",
                    required=True,
                ),
            )
        ),
        artifacts=(
            BundleArtifact(
                logical_path="a.htm",
                content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
                artifact_kind="primary_document",
                required=True,
            ),
        ),
        report_inputs=(IxdsReportInput(document_uris=(uri,), target="default"),),
        uri_bindings=(
            UriBinding(
                document_uri=uri,
                artifact_path="a.htm",
                content_sha256=obj.sha256,
                replay_aliases=(),
            ),
        ),
    )
    outcomes = build_inventory_outcomes(bundle, store)
    assert isinstance(outcomes[0], InventorySuccess)
    assert outcomes[0].inventory.selected_target_item_count == 0


def test_instance_wrong_root_is_fatal(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "w")
    html = b"<html><body/></html>"
    bundle = _instance_bundle(store, html)
    outcomes = build_inventory_outcomes(bundle, store)
    assert isinstance(outcomes[0], InventoryFailure)
    assert outcomes[0].code == "INSTANCE_ROOT_INVALID"
