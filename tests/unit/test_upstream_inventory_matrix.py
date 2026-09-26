"""Extended upstream inventory scanner matrix (M1A-3 remediation)."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from unittest.mock import patch

from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    IxdsReportInput,
    UriBinding,
)
from edgar.domain.payload import compute_payload_hash
from edgar.domain.report_key import report_key as compute_report_key
from edgar.storage.objects import ObjectStore
from edgar.xbrl.upstream_inventory import (
    InventoryFailure,
    InventorySuccess,
    _ixds_membership_for_input,
    _scan_inline_member,
    build_inventory_outcomes,
)


def _inline_bundle(
    store: ObjectStore,
    tmp: Path,
    xml: bytes,
    *,
    accession: str = "0000000001-24-000010",
    target: str | None = "default",
) -> FilingBundle:
    obj = store.put_bytes(xml)
    path = "accession/inline.htm"
    uri = "https://example.com/inline.htm"
    artifacts = (
        BundleArtifact(
            logical_path=path,
            content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
    )
    report_input = IxdsReportInput(document_uris=(uri,), target=target)
    return FilingBundle(
        filing=FilingIdentity(
            cik="0000000001",
            accession=accession,
            form_type="10-K",
            filing_date=date(2024, 1, 1),
            accepted_at=None,
            report_period_end=date(2023, 12, 31),
            primary_document="inline.htm",
        ),
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(report_input,),
        uri_bindings=(
            UriBinding(
                document_uri=uri,
                artifact_path=path,
                content_sha256=obj.sha256,
                replay_aliases=(),
            ),
        ),
    )


def test_ix_hidden_descendant_counted(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.wbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:hidden>
    <ix:nonNumeric name="t:Foo" contextRef="c1">hidden</ix:nonNumeric>
  </ix:hidden>
</html>
""".replace(b"wbrl", b"xbrl")
    outcomes = build_inventory_outcomes(_inline_bundle(store, tmp_path, xml), store)
    assert isinstance(outcomes[0], InventorySuccess)
    assert outcomes[0].inventory.selected_target_item_count == 1


def test_continuation_unresolved(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:nonNumeric name="t:Foo" contextRef="c1" continuedAt="missing">x</ix:nonNumeric>
</html>
"""
    outcomes = build_inventory_outcomes(_inline_bundle(store, tmp_path, xml), store)
    assert isinstance(outcomes[0], InventoryFailure)
    assert outcomes[0].code == "CONTINUATION_UNRESOLVED"


def test_continuation_cycle(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:continuation id="a" continuedAt="b"/>
  <ix:continuation id="b" continuedAt="a"/>
  <ix:nonNumeric name="t:Foo" contextRef="c1" continuedAt="a">x</ix:nonNumeric>
</html>
"""
    outcomes = build_inventory_outcomes(_inline_bundle(store, tmp_path, xml), store)
    assert isinstance(outcomes[0], InventoryFailure)
    assert outcomes[0].code == "CONTINUATION_CYCLE"


def test_continuation_ambiguous(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:continuation id="dup"/>
  <ix:continuation id="dup"/>
  <ix:nonNumeric name="t:Foo" contextRef="c1" continuedAt="dup">x</ix:nonNumeric>
</html>
"""
    outcomes = build_inventory_outcomes(_inline_bundle(store, tmp_path, xml), store)
    assert isinstance(outcomes[0], InventoryFailure)
    assert outcomes[0].code == "CONTINUATION_AMBIGUOUS"


def test_unit_id_collision(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:unit id="dup"/>
  <xbrli:unit id="dup"/>
  <xbrli:context id="c1"/>
  <ix:nonNumeric name="t:Foo" contextRef="c1">x</ix:nonNumeric>
</html>
"""
    outcomes = build_inventory_outcomes(_inline_bundle(store, tmp_path, xml), store)
    assert isinstance(outcomes[0], InventoryFailure)
    assert outcomes[0].code == "UNIT_ID_COLLISION"
    paths = re.findall(r"\('([^']+)', '([^']+)'\)", outcomes[0].message)
    assert len(paths) >= 2 and paths[0] != paths[1]


def test_inline_target_omitted_vs_literal_default_distinct(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:nonNumeric name="t:A" contextRef="c1">1</ix:nonNumeric>
  <ix:nonNumeric name="t:B" contextRef="c1" target="default">2</ix:nonNumeric>
</html>
"""
    outcomes = build_inventory_outcomes(_inline_bundle(store, tmp_path, xml), store)
    inv = outcomes[0]
    assert isinstance(inv, InventorySuccess)
    assert inv.inventory.selected_target_item_count == 1
    alt = {tuple(sorted(d.items())): c for d, c in inv.inventory.alternate_target_item_counts}
    assert alt.get((("kind", "named"), ("name", "default")), 0) == 1


def test_inline_fraction_is_fatal(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:fraction name="t:Amt" contextRef="c1">1</ix:fraction>
</html>
"""
    outcomes = build_inventory_outcomes(_inline_bundle(store, tmp_path, xml), store)
    assert isinstance(outcomes[0], InventoryFailure)
    assert outcomes[0].code == "UNSUPPORTED_INLINE_FRACTION_OR_TUPLE"


def test_ixds_duplicate_canonical_member(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:nonNumeric name="t:Foo" contextRef="c1">x</ix:nonNumeric>
</html>
"""
    obj = store.put_bytes(xml)
    uri_a = "https://example.com/a.htm"
    uri_b = "https://example.com/b.htm"
    artifacts = (
        BundleArtifact(
            logical_path="accession/a.htm",
            content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
    )
    bundle = FilingBundle(
        filing=FilingIdentity(
            cik="0000000001",
            accession="0000000001-24-000011",
            form_type="10-K",
            filing_date=date(2024, 1, 1),
            accepted_at=None,
            report_period_end=date(2023, 12, 31),
            primary_document="a.htm",
        ),
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(IxdsReportInput(document_uris=(uri_a, uri_b), target="default"),),
        uri_bindings=(UriBinding(uri_a, "accession/a.htm", obj.sha256, replay_aliases=(uri_b,)),),
    )
    outcomes = build_inventory_outcomes(bundle, store)
    assert isinstance(outcomes[0], InventoryFailure)
    assert outcomes[0].code == "IXDS_DUPLICATE_CANONICAL_MEMBER"


def test_continuation_reuse_footnote_and_item(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:continuation id="shared"/>
  <ix:footnote continuedAt="shared">fn</ix:footnote>
  <ix:nonNumeric name="t:Foo" contextRef="c1" continuedAt="shared">x</ix:nonNumeric>
</html>
"""
    outcomes = build_inventory_outcomes(_inline_bundle(store, tmp_path, xml), store)
    assert isinstance(outcomes[0], InventoryFailure)
    assert outcomes[0].code == "CONTINUATION_REUSE"


def test_continuation_reuse_across_alternate_and_selected_target(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:continuation id="tail"/>
  <ix:continuation id="mid" continuedAt="tail"/>
  <ix:nonNumeric name="t:Alt" contextRef="c1" target="alt" continuedAt="mid">a</ix:nonNumeric>
  <ix:nonNumeric name="t:Def" contextRef="c1" continuedAt="mid">b</ix:nonNumeric>
</html>
"""
    outcomes = build_inventory_outcomes(_inline_bundle(store, tmp_path, xml), store)
    assert isinstance(outcomes[0], InventoryFailure)
    assert outcomes[0].code == "CONTINUATION_REUSE"


def test_inline_tuple_on_selected_target_is_fatal(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:tuple contextRef="c1"/>
</html>
"""
    outcomes = build_inventory_outcomes(_inline_bundle(store, tmp_path, xml), store)
    assert isinstance(outcomes[0], InventoryFailure)
    assert outcomes[0].code == "UNSUPPORTED_INLINE_FRACTION_OR_TUPLE"


def test_inline_tuple_on_alternate_target_only(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:nonNumeric name="t:Foo" contextRef="c1">1</ix:nonNumeric>
  <ix:tuple target="alt" contextRef="c1"/>
</html>
"""
    outcomes = build_inventory_outcomes(_inline_bundle(store, tmp_path, xml), store)
    assert isinstance(outcomes[0], InventorySuccess)
    assert outcomes[0].inventory.selected_target_item_count == 1
    assert outcomes[0].inventory.tuple_container_count == 0


def test_ixds_membership_replay_alias_resolves_to_canonical(tmp_path: Path) -> None:
    canonical = "https://example.com/canonical.htm"
    alias = "https://example.com/alias.htm"
    bindings = (
        UriBinding(
            document_uri=canonical,
            artifact_path="accession/a.htm",
            content_sha256="a" * 64,
            replay_aliases=(alias,),
        ),
    )
    resolved = _ixds_membership_for_input(
        IxdsReportInput(document_uris=(alias,), target="default"),
        bindings,
    )
    assert resolved == frozenset({canonical})


def test_ixds_membership_ambiguous_alias(tmp_path: Path) -> None:
    shared = "https://example.com/shared.htm"
    bindings = (
        UriBinding("https://example.com/a.htm", "a.htm", "a" * 64, replay_aliases=(shared,)),
        UriBinding("https://example.com/b.htm", "b.htm", "b" * 64, replay_aliases=(shared,)),
    )
    resolved = _ixds_membership_for_input(
        IxdsReportInput(document_uris=(shared,), target="default"),
        bindings,
    )
    assert isinstance(resolved, InventoryFailure)
    assert resolved.code == "IXDS_MEMBER_URI_AMBIGUOUS"


def test_ixds_membership_primary_and_alias_duplicate(tmp_path: Path) -> None:
    uri_a = "https://example.com/a.htm"
    uri_b = "https://example.com/b.htm"
    bindings = (UriBinding(uri_a, "accession/a.htm", "a" * 64, replay_aliases=(uri_b,)),)
    resolved = _ixds_membership_for_input(
        IxdsReportInput(document_uris=(uri_a, uri_b), target="default"),
        bindings,
    )
    assert isinstance(resolved, InventoryFailure)
    assert resolved.code == "IXDS_DUPLICATE_CANONICAL_MEMBER"


def test_ixds_shared_membership_two_outcomes_one_scan(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    xml_a = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c1"/>
  <ix:nonNumeric name="t:Foo" contextRef="c1">x</ix:nonNumeric>
</html>
"""
    xml_b = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <xbrli:context id="c2"/>
</html>
"""
    obj_a = store.put_bytes(xml_a)
    obj_b = store.put_bytes(xml_b)
    uri_a = "https://example.com/a.htm"
    uri_b = "https://example.com/b.htm"
    path_a = "accession/a.htm"
    path_b = "accession/b.htm"
    artifacts = (
        BundleArtifact(
            logical_path=path_a,
            content=ContentObject(sha256=obj_a.sha256, byte_size=obj_a.byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
        BundleArtifact(
            logical_path=path_b,
            content=ContentObject(sha256=obj_b.sha256, byte_size=obj_b.byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
    )
    bundle = FilingBundle(
        filing=FilingIdentity(
            cik="0000000001",
            accession="0000000001-24-000012",
            form_type="10-K",
            filing_date=date(2024, 1, 1),
            accepted_at=None,
            report_period_end=date(2023, 12, 31),
            primary_document="a.htm",
        ),
        payload_hash=compute_payload_hash(artifacts),
        artifacts=artifacts,
        report_inputs=(
            IxdsReportInput(document_uris=(uri_a, uri_b), target="default"),
            IxdsReportInput(document_uris=(uri_b, uri_a), target="default"),
        ),
        uri_bindings=(
            UriBinding(uri_a, path_a, obj_a.sha256),
            UriBinding(uri_b, path_b, obj_b.sha256),
        ),
    )
    key_ab = compute_report_key(bundle.report_inputs[0])
    key_ba = compute_report_key(bundle.report_inputs[1])
    scan_calls: list[str] = []
    original_scan = _scan_inline_member

    def counting_scan(path: str, root: object, scan: object) -> None:
        scan_calls.append(path)
        original_scan(path, root, scan)  # type: ignore[arg-type]

    with patch(
        "edgar.xbrl.upstream_inventory._scan_inline_member",
        side_effect=counting_scan,
    ):
        outcomes = build_inventory_outcomes(bundle, store)
    assert len(outcomes) == 2
    assert all(isinstance(o, InventorySuccess) for o in outcomes)
    assert {o.report_key for o in outcomes} == {key_ab, key_ba}
    assert len(scan_calls) == 2
