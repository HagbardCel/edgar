"""US-GAAP concept availability from captured filing DTS schema documents.

Closure-fetched standard FASB schemas are stored as ``artifact_kind=external``,
not only ``taxonomy_schema``. Availability walks ``uri_bindings`` (the replay
closure), treats each bound object whose root is an XSD ``schema`` as taxonomy
evidence, and fails closed when inspection cannot complete for annual filings.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import lxml.etree as etree

from edgar.domain.identifiers import validate_accession, validate_cik
from edgar.financials.select import ANNUAL_FORMS
from edgar.financials.taxonomy_release import filing_taxonomy_release, us_gaap_release_token
from edgar.storage.bundles import BundleRepository
from edgar.storage.objects import ObjectStore
from edgar.xbrl.taxonomy_family import classify

_XSD_NS = "http://www.w3.org/2001/XMLSchema"
_SCHEMA_ROOT = f"{{{_XSD_NS}}}schema"


class TaxonomyAvailabilityError(ValueError):
    """Captured DTS taxonomy could not be inspected for quality reporting."""


@dataclass(frozen=True)
class FilingTaxonomyAvailability:
    filing_taxonomy_release: str
    releases: frozenset[str]
    concepts: frozenset[tuple[str, str]]
    schema_sha256s: tuple[str, ...]


def _secure_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=True,
    )


def parse_taxonomy_schema_bytes(data: bytes) -> tuple[str, frozenset[tuple[str, str]]]:
    """Parse one XSD schema document. Raises on malformed XML or missing target namespace."""
    try:
        root = etree.fromstring(data, parser=_secure_parser())
    except etree.XMLSyntaxError as exc:
        raise TaxonomyAvailabilityError(f"taxonomy schema XML is not well-formed: {exc}") from exc
    if root.tag != _SCHEMA_ROOT:
        raise TaxonomyAvailabilityError(
            f"expected XSD schema root, got {root.tag!r}",
        )
    target = root.get("targetNamespace")
    if not target:
        raise TaxonomyAvailabilityError("taxonomy schema is missing targetNamespace")
    concepts: set[tuple[str, str]] = set()
    for elem in root.iter(f"{{{_XSD_NS}}}element"):
        name = elem.get("name")
        if name:
            concepts.add((target, name))
    return target, frozenset(concepts)


def _inspect_bound_object(
    store: ObjectStore,
    sha256: str,
) -> tuple[str, frozenset[tuple[str, str]]] | None:
    try:
        payload = store.open_bytes(sha256)
    except (OSError, ValueError) as exc:
        raise TaxonomyAvailabilityError(
            f"missing CAS object for captured DTS document: {sha256}",
        ) from exc
    try:
        root = etree.fromstring(payload, parser=_secure_parser())
    except etree.XMLSyntaxError:
        return None
    if root.tag != _SCHEMA_ROOT:
        return None
    return parse_taxonomy_schema_bytes(payload)


def _availability_from_bundle(
    store: ObjectStore,
    bundle_form: str,
    uri_binding_shas: tuple[str, ...],
) -> FilingTaxonomyAvailability:
    concepts: set[tuple[str, str]] = set()
    schema_shas: list[str] = []
    us_gaap_namespaces: set[str] = set()
    for sha256 in uri_binding_shas:
        parsed = _inspect_bound_object(store, sha256)
        if parsed is None:
            continue
        _target, declared = parsed
        schema_shas.append(sha256)
        for namespace, local_name in declared:
            if classify(namespace).semantic_family == "us-gaap":
                concepts.add((namespace, local_name))
                us_gaap_namespaces.add(namespace)
    if bundle_form in ANNUAL_FORMS and not us_gaap_namespaces:
        raise TaxonomyAvailabilityError(
            "annual filing has no captured US-GAAP taxonomy schema in the DTS closure",
        )
    release_tokens = {
        token
        for namespace in us_gaap_namespaces
        if (token := us_gaap_release_token(namespace)) is not None
    }
    return FilingTaxonomyAvailability(
        filing_taxonomy_release=filing_taxonomy_release(us_gaap_namespaces),
        releases=frozenset(release_tokens),
        concepts=frozenset(concepts),
        schema_sha256s=tuple(schema_shas),
    )


def _uri_binding_shas(bundle: object) -> tuple[str, ...]:
    bindings = getattr(bundle, "uri_bindings", ())
    seen: list[str] = []
    for binding in bindings:
        digest = binding.content_sha256
        if digest not in seen:
            seen.append(digest)
    return tuple(seen)


@lru_cache(maxsize=128)
def _cached_filing_taxonomy_availability(
    data_root: str,
    cik: str,
    accession: str,
) -> FilingTaxonomyAvailability:
    root = Path(data_root)
    store = ObjectStore(root)
    repo = BundleRepository(root, store)
    published = repo.list_published(validate_cik(cik), validate_accession(accession))
    if not published:
        raise TaxonomyAvailabilityError(
            f"no published FilingBundle for accession {accession}",
        )
    if len(published) > 1:
        raise TaxonomyAvailabilityError(
            f"accession {accession} has {len(published)} published bundles; "
            "quality reporting requires exactly one",
        )
    _bundle_dir, bundle = published[0]
    return _availability_from_bundle(
        store,
        bundle.filing.form_type,
        _uri_binding_shas(bundle),
    )


def load_filing_taxonomy_availability(
    data_root: Path,
    cik: str,
    accession: str,
) -> FilingTaxonomyAvailability:
    """US-GAAP concepts and release from captured DTS closure schema documents."""
    return _cached_filing_taxonomy_availability(str(data_root.resolve()), cik, accession)


def load_taxonomy_concepts_for_filing(
    data_root: Path,
    cik: str,
    accession: str,
) -> frozenset[tuple[str, str]]:
    """Compatibility wrapper returning only US-GAAP concepts."""
    return load_filing_taxonomy_availability(data_root, cik, accession).concepts
