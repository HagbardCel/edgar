"""US-GAAP concept availability from captured filing taxonomy schema artifacts.

``source.concept_declaration`` is a bounded retained grain (facts, networks,
dimensions, issuer extensions). Decision applicability for P2 must ask whether
a standard concept exists in the filing's captured DTS schema, not whether it
was persisted as a declaration row.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import lxml.etree as etree

from edgar.domain.identifiers import validate_accession, validate_cik
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from edgar.xbrl.taxonomy_family import classify

_XSD_NS = "http://www.w3.org/2001/XMLSchema"


def _secure_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=True,
    )


def concepts_from_taxonomy_schema_bytes(data: bytes) -> frozenset[tuple[str, str]]:
    """``(targetNamespace, element@name)`` pairs declared in one schema document."""
    try:
        root = etree.fromstring(data, parser=_secure_parser())
    except etree.XMLSyntaxError:
        return frozenset()
    target = root.get("targetNamespace")
    if not target:
        return frozenset()
    concepts: set[tuple[str, str]] = set()
    for elem in root.iter(f"{{{_XSD_NS}}}element"):
        name = elem.get("name")
        if name:
            concepts.add((target, name))
    return frozenset(concepts)


@lru_cache(maxsize=128)
def _taxonomy_concepts_for_bundle(
    data_root: str,
    cik: str,
    accession: str,
) -> frozenset[tuple[str, str]]:
    root = Path(data_root)
    store = ObjectStore(root)
    repo = BundleRepository(root, store)
    published = repo.list_published(validate_cik(cik), validate_accession(accession))
    if len(published) != 1:
        return frozenset()
    _bundle_dir, bundle = published[0]
    concepts: set[tuple[str, str]] = set()
    for artifact in bundle.artifacts:
        if artifact.artifact_kind != "taxonomy_schema":
            continue
        try:
            payload = store.open_bytes(artifact.content.sha256)
        except (OSError, ValueError):
            continue
        for namespace, local_name in concepts_from_taxonomy_schema_bytes(payload):
            if classify(namespace).semantic_family == "us-gaap":
                concepts.add((namespace, local_name))
    return frozenset(concepts)


def load_taxonomy_concepts_for_filing(
    data_root: Path,
    cik: str,
    accession: str,
) -> frozenset[tuple[str, str]]:
    """US-GAAP concepts from ``taxonomy_schema`` artifacts in the published bundle."""
    return _taxonomy_concepts_for_bundle(str(data_root.resolve()), cik, accession)
