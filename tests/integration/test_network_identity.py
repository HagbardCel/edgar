"""M1A-2: genuine pre-M1A-2 network collisions and rich-fixture resource QNames."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select

from edgar.db import source_schema as src
from edgar.db.source import catalog_source_filing, persist_extraction
from edgar.storage.objects import ObjectStore
from edgar.xbrl.source_extract import extract_filing
from edgar.xbrl.source_records import RelationshipRecord
from edgar.xbrl.source_wire import report_extraction_from_dict, report_extraction_to_dict
from tests.helpers.database import reset_test_database, test_database_url, truncate_all_tables
from tests.helpers.extraction_receipt import wrap_filing_extraction
from tests.helpers.linkbase_qnames import (
    LABEL_ARC,
    LABEL_LINK,
    PRESENTATION_ARC,
    PRESENTATION_LINK,
    REFERENCE_ARC,
    REFERENCE_LINK,
)
from tests.helpers.network_identity_fixture import (
    ALT_PRESENTATION_ARC,
    ALT_PRESENTATION_LINK,
    PARENT_CHILD,
    ROLE_URI,
    make_arc_qname_collision_bundle,
    make_link_qname_collision_bundle,
    pre_m1a2_semantic_key,
)
from tests.helpers.xbrl_bundles import make_rich_semantic_bundle

pytestmark = pytest.mark.database


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = test_database_url()
    eng = create_engine(url, future=True)
    reset_test_database(eng, database_url=url)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def truncate_tables(engine: Engine) -> Iterator[None]:
    with engine.begin() as conn:
        truncate_all_tables(conn)
    yield


def _presentation_pairs(relationships: tuple[RelationshipRecord, ...]) -> list[RelationshipRecord]:
    return [
        rel
        for rel in relationships
        if rel.network_type == "presentation"
        and rel.arcrole_uri == PARENT_CHILD
        and rel.link_role_uri == ROLE_URI
        and rel.source_concept.local_name == "Abstract"
        and rel.target_concept.local_name == "Assets"
    ]


def _extract_wire_persist(
    engine: Engine,
    tmp_path: Path,
    bundle_factory,  # noqa: ANN001
) -> tuple[tuple[RelationshipRecord, ...], list[tuple[str, str, str, str]]]:
    store = ObjectStore(tmp_path)
    bundle = bundle_factory(store)
    extraction = extract_filing(bundle, store)
    report = extraction.reports[0]
    restored = report_extraction_from_dict(report_extraction_to_dict(report))
    assert restored.relationships == report.relationships
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(
            conn,
            filing_id=catalog.filing_id,
            extraction=wrap_filing_extraction(extraction, bundle=bundle),
        )
        rows = conn.execute(
            select(
                src.source_relationship.c.arcrole_uri,
                src.source_relationship.c.link_role_uri,
                src.source_relationship.c.link_qname,
                src.source_relationship.c.arc_qname,
            ).order_by(src.source_relationship.c.source_order)
        ).all()
    return report.relationships, [(row[0], row[1], row[2], row[3]) for row in rows]


def test_link_qname_repairs_pre_m1a2_network_collision(engine: Engine, tmp_path: Path) -> None:
    relationships, sql_rows = _extract_wire_persist(
        engine, tmp_path, make_link_qname_collision_bundle
    )
    pair = _presentation_pairs(relationships)
    assert len(pair) == 2
    assert pre_m1a2_semantic_key(pair[0]) == pre_m1a2_semantic_key(pair[1])
    assert pair[0].arc_qname == pair[1].arc_qname == PRESENTATION_ARC
    link_qnames = {rel.link_qname for rel in pair}
    assert link_qnames == {PRESENTATION_LINK, ALT_PRESENTATION_LINK}
    network_keys = {
        (rel.arcrole_uri, rel.link_role_uri, rel.link_qname.clark, rel.arc_qname.clark)
        for rel in pair
    }
    assert len(network_keys) == 2
    sql_keys = {
        (arcrole, role, link, arc)
        for arcrole, role, link, arc in sql_rows
        if arcrole == PARENT_CHILD and role == ROLE_URI
    }
    assert sql_keys == network_keys
    for _arcrole, _role, link, arc in sql_keys:
        assert link.startswith("{")
        assert arc.startswith("{")
        assert "presentationArc" in arc


def test_arc_qname_repairs_pre_m1a2_network_collision(engine: Engine, tmp_path: Path) -> None:
    relationships, sql_rows = _extract_wire_persist(
        engine, tmp_path, make_arc_qname_collision_bundle
    )
    pair = _presentation_pairs(relationships)
    assert len(pair) == 2
    assert pre_m1a2_semantic_key(pair[0]) == pre_m1a2_semantic_key(pair[1])
    assert pair[0].link_qname == pair[1].link_qname == PRESENTATION_LINK
    arc_qnames = {rel.arc_qname for rel in pair}
    assert arc_qnames == {PRESENTATION_ARC, ALT_PRESENTATION_ARC}
    network_keys = {
        (rel.arcrole_uri, rel.link_role_uri, rel.link_qname.clark, rel.arc_qname.clark)
        for rel in pair
    }
    assert len(network_keys) == 2
    sql_keys = {
        (arcrole, role, link, arc)
        for arcrole, role, link, arc in sql_rows
        if arcrole == PARENT_CHILD and role == ROLE_URI
    }
    assert sql_keys == network_keys
    for _arcrole, _role, link, arc in sql_keys:
        assert link == PRESENTATION_LINK.clark
        assert arc.startswith("{")


def test_rich_label_and_reference_qnames_persist_as_clark(engine: Engine, tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    bundle = make_rich_semantic_bundle(store)
    extraction = extract_filing(bundle, store)
    report = extraction.reports[0]
    labels = [lab for lab in report.labels if lab.concept.local_name == "Assets"]
    references = [ref for ref in report.references if ref.concept.local_name == "Assets"]
    assert labels
    assert references
    assert all(lab.link_qname == LABEL_LINK and lab.arc_qname == LABEL_ARC for lab in labels)
    assert all(
        ref.link_qname == REFERENCE_LINK and ref.arc_qname == REFERENCE_ARC for ref in references
    )
    restored = report_extraction_from_dict(report_extraction_to_dict(report))
    assert restored.labels == report.labels
    assert restored.references == report.references
    with engine.begin() as conn:
        catalog = catalog_source_filing(conn, bundle)
        persist_extraction(
            conn,
            filing_id=catalog.filing_id,
            extraction=wrap_filing_extraction(extraction, bundle=bundle),
        )
        label_rows = conn.execute(
            select(
                src.source_concept_label.c.link_qname,
                src.source_concept_label.c.arc_qname,
            )
        ).all()
        ref_rows = conn.execute(
            select(
                src.source_concept_reference.c.link_qname,
                src.source_concept_reference.c.arc_qname,
            )
        ).all()
    assert label_rows
    assert ref_rows
    assert all(row[0] == LABEL_LINK.clark and row[1] == LABEL_ARC.clark for row in label_rows)
    assert all(row[0] == REFERENCE_LINK.clark and row[1] == REFERENCE_ARC.clark for row in ref_rows)
