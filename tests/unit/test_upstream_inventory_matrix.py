"""Extended upstream inventory scanner matrix (M1A-3 remediation)."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    IxdsReportInput,
    UriBinding,
)
from edgar.domain.payload import compute_payload_hash
from edgar.storage.objects import ObjectStore
from edgar.xbrl.upstream_inventory import (
    InventoryFailure,
    InventorySuccess,
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
