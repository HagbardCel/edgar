"""Effective relationship extraction with endpoint-aware occurrence identities.

Identity model (xbrl-relationship-v2):

- ``arc_occurrence_hash``: arc document URI + deterministic arc element locator.
- Endpoint occurrence: locator-backed endpoints carry document URI + locator
  only; resolved semantics live in the canonical compared record.
- ``relationship_occurrence_hash``: arc occurrence hash + source/target
  endpoint occurrence hashes.
- Direct (non-locator) concept endpoints are extraction-incomplete: Clark
  QName is never an occurrence identity.
- Diagnostic provenance (xlink:label, source line) never enters any hash.

Enumeration contract: one pass per exact base set. Exact base-set identities
are Arelle ``baseSets`` keys whose link QName and arc QName slots are both
non-None; the aggregate keys are never used for enumeration.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import lxml.etree as etree

from spike_lib import RELATIONSHIP_SERIALIZATION_VERSION
from spike_lib.hashing import canonical_json_bytes, versioned_record_hash
from spike_lib.locators import element_locator, occurrence_provenance
from spike_lib.resources import serialize_resource

PRESENTATION_ARCROLE = "http://www.xbrl.org/2003/arcrole/parent-child"
CALCULATION_ARCROLE = "http://www.xbrl.org/2003/arcrole/summation-item"
CONCEPT_LABEL_ARCROLE = "http://www.xbrl.org/2003/arcrole/concept-label"
CONCEPT_REFERENCE_ARCROLE = "http://www.xbrl.org/2003/arcrole/concept-reference"
FOOTNOTE_ARCROLE = "http://www.xbrl.org/2003/arcrole/fact-footnote"

# XBRL Generic Labels 1.0 / Generic References — deferred for Slice 0.
DEFERRED_GENERIC_RESOURCE_ARCROLES = frozenset(
    {
        "http://xbrl.org/arcrole/2008/element-label",
        "http://xbrl.org/arcrole/2008/element-reference",
    }
)

# Locked definition arcrole registry (XBRL Dimensions 1.0 + XBRL 2.1 definition links).
DEFINITION_ARCROLES = frozenset(
    {
        "http://www.xbrl.org/2003/arcrole/general-special",
        "http://www.xbrl.org/2003/arcrole/essence-alias",
        "http://www.xbrl.org/2003/arcrole/similar-tuples",
        "http://www.xbrl.org/2003/arcrole/requires-element",
        "http://xbrl.org/int/dim/arcrole/all",
        "http://xbrl.org/int/dim/arcrole/notAll",
        "http://xbrl.org/int/dim/arcrole/hypercube-dimension",
        "http://xbrl.org/int/dim/arcrole/dimension-domain",
        "http://xbrl.org/int/dim/arcrole/domain-member",
        "http://xbrl.org/int/dim/arcrole/dimension-default",
    }
)

LINK_NS = "http://www.xbrl.org/2003/linkbase"
DEFINITION_LINK_CLARK = f"{{{LINK_NS}}}definitionLink"

# Documented exclusions: counted but neither extracted nor failing.
EXCLUDED_ARCROLES = frozenset({FOOTNOTE_ARCROLE})

RELATIONSHIP_SET_LOAD_FAILED = "RELATIONSHIP_SET_LOAD_FAILED"
ENDPOINT_FAMILY_MISMATCH = "ENDPOINT_FAMILY_MISMATCH"
DIRECT_ENDPOINT_UNIDENTIFIABLE = "DIRECT_ENDPOINT_UNIDENTIFIABLE"

ConceptDocUriResolver = Callable[[Any], str | None]


def _clark_qname(qname: Any) -> str | None:
    if qname is None:
        return None
    clark = getattr(qname, "clarkNotation", None)
    if isinstance(clark, str):
        return clark
    try:
        return etree.QName(str(qname)).text
    except (TypeError, ValueError):
        return None


def _concept_clark(model_object: Any) -> str | None:
    return _clark_qname(getattr(model_object, "qname", None))


def _decimal_or_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return format(Decimal(str(value)), "f")
    except Exception:  # noqa: BLE001
        return str(value)


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def classify_network(arcrole: str, *, link_clark: str | None) -> str:
    """Relationship family under the Phase 1 registry.

    Returns one of: presentation, calculation, definition, resource,
    excluded, deferred, unsupported.
    """
    if arcrole == PRESENTATION_ARCROLE:
        return "presentation"
    if arcrole == CALCULATION_ARCROLE:
        return "calculation"
    if arcrole in DEFINITION_ARCROLES:
        return "definition"
    if arcrole in (CONCEPT_LABEL_ARCROLE, CONCEPT_REFERENCE_ARCROLE):
        return "resource"
    if arcrole in EXCLUDED_ARCROLES:
        return "excluded"
    if arcrole in DEFERRED_GENERIC_RESOURCE_ARCROLES:
        return "deferred"
    # Custom definition arcroles are supported when the link topology is a
    # definition link; the original arcrole URI is preserved in the record.
    if link_clark == DEFINITION_LINK_CLARK:
        return "definition"
    return "unsupported"


def arc_occurrence_record(arc_element: Any, *, canonical_document_uri: str) -> dict[str, Any]:
    """Occurrence identity only: document URI + locator. No provenance."""
    return {
        "arc_document_uri": canonical_document_uri,
        "arc_locator": element_locator(arc_element),
    }


def arc_occurrence_hash(record: dict[str, Any]) -> str:
    return versioned_record_hash(RELATIONSHIP_SERIALIZATION_VERSION, record)


def endpoint_occurrence_record(
    *, canonical_document_uri: str, locator_element: Any
) -> dict[str, Any]:
    """Locator-backed endpoint occurrence: document URI + locator only."""
    return {
        "document_uri": canonical_document_uri,
        "locator": element_locator(locator_element),
    }


def endpoint_occurrence_hash(record: dict[str, Any]) -> str:
    return versioned_record_hash(RELATIONSHIP_SERIALIZATION_VERSION, record)


def resolved_object_identity(
    model_object: Any, *, canonical_doc_uri: ConceptDocUriResolver
) -> dict[str, Any] | None:
    """Semantic identity of a dereferenced endpoint object (not an occurrence)."""
    from arelle.ModelDtsObject import ModelConcept, ModelResource

    if model_object is None:
        return None
    if isinstance(model_object, ModelConcept):
        clark = _concept_clark(model_object)
        if clark is None:
            return None
        return {"kind": "concept", "expanded_qname": clark}
    if isinstance(model_object, ModelResource):
        local_name = getattr(model_object, "localName", None)
        namespace = getattr(model_object, "namespaceURI", None)
        if namespace == LINK_NS and local_name in ("label", "reference"):
            doc = getattr(model_object, "modelDocument", None)
            doc_uri = canonical_doc_uri(doc) if doc is not None else None
            if doc_uri is None:
                return None
            serialized = serialize_resource(
                model_object, resource_type=local_name, canonical_document_uri=doc_uri
            )
            return {
                "kind": "resource",
                "resource_occurrence_hash": serialized["resource_occurrence_hash"],
                "resource_content_hash": serialized["resource_content_hash"],
            }
        return {"kind": "other_resource", "element": etree.QName(model_object.tag).text}
    return None


def endpoint_occurrence_identity(
    model_object: Any,
    locator: Any,
    *,
    canonical_doc_uri: ConceptDocUriResolver,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool, str | None]:
    """Return (occurrence_identity, resolved_semantics, stable, failure_code).

    Locator-backed endpoints are stable when the locator document URI and
    resolved object are available. Local filed resources are stable via their
    resource occurrence hash. Direct concept endpoints (no locator) are
    unstable — Clark QName is never an occurrence identity.
    """
    resolved = resolved_object_identity(model_object, canonical_doc_uri=canonical_doc_uri)
    if locator is not None:
        doc = getattr(locator, "modelDocument", None)
        doc_uri = canonical_doc_uri(doc) if doc is not None else None
        if doc_uri is None or resolved is None:
            return None, resolved, False, ENDPOINT_FAMILY_MISMATCH
        occurrence = endpoint_occurrence_record(
            canonical_document_uri=doc_uri, locator_element=locator
        )
        return (
            {
                "endpoint_kind": "locator",
                "endpoint_occurrence_hash": endpoint_occurrence_hash(occurrence),
                "endpoint_occurrence": occurrence,
            },
            resolved,
            True,
            None,
        )
    if resolved is not None and resolved.get("kind") == "resource":
        return (
            {
                "endpoint_kind": "local_resource",
                "endpoint_occurrence_hash": resolved["resource_occurrence_hash"],
            },
            resolved,
            True,
            None,
        )
    if resolved is not None and resolved.get("kind") == "concept":
        # Direct concept with no filed locator: extraction incomplete.
        return None, resolved, False, DIRECT_ENDPOINT_UNIDENTIFIABLE
    return None, resolved, False, ENDPOINT_FAMILY_MISMATCH


def relationship_occurrence_hash(
    arc_hash: str,
    source_endpoint_hash: str | None,
    target_endpoint_hash: str | None,
) -> str:
    return versioned_record_hash(
        RELATIONSHIP_SERIALIZATION_VERSION,
        {
            "arc_occurrence_hash": arc_hash,
            "source_endpoint_occurrence_hash": source_endpoint_hash,
            "target_endpoint_occurrence_hash": target_endpoint_hash,
        },
    )


def canonical_relationship_record(record_fields: dict[str, Any]) -> dict[str, Any]:
    """Explicit inclusion builder for collection-hash inputs.

    Only named fields enter semantic identity; diagnostic provenance cannot
    leak in by default.
    """
    network = record_fields["network_type"]
    base: dict[str, Any] = {
        "relationship_occurrence_hash": record_fields["relationship_occurrence_hash"],
        "network_type": network,
        "arcrole_uri": record_fields["arcrole_uri"],
        "link_role_uri": record_fields["link_role_uri"],
        "arc_occurrence_hash": record_fields["arc_occurrence_hash"],
        "source_endpoint_occurrence_identity": record_fields["source_endpoint_occurrence_identity"],
        "target_endpoint_occurrence_identity": record_fields["target_endpoint_occurrence_identity"],
        "source_semantic_identity": record_fields["source_semantic_identity"],
        "target_semantic_identity": record_fields["target_semantic_identity"],
        "order": record_fields["order"],
    }
    if network == "resource":
        base["resource_relationship_kind"] = record_fields["resource_relationship_kind"]
        base["source_concept"] = record_fields["source_concept"]
        base["resource_occurrence_hash"] = record_fields.get("resource_occurrence_hash")
        base["resource_content_hash"] = record_fields.get("resource_content_hash")
    else:
        base["source_concept"] = record_fields["source_concept"]
        base["target_concept"] = record_fields["target_concept"]
        base["weight"] = record_fields.get("weight")
        base["preferred_label_role"] = record_fields.get("preferred_label_role")
        base["target_role"] = record_fields.get("target_role")
        base["closed"] = record_fields.get("closed")
        base["usable"] = record_fields.get("usable")
        base["context_element"] = record_fields.get("context_element")
    return base


def _canonical_doc_uri_from_aliases(aliases: dict[str, str]) -> ConceptDocUriResolver:
    def resolve(model_document: Any) -> str | None:
        uri = str(getattr(model_document, "uri", "") or "")
        if not uri:
            return None
        return aliases.get(uri)

    return resolve


def _endpoint_hash(identity: dict[str, Any] | None) -> str | None:
    if identity is None:
        return None
    return identity.get("endpoint_occurrence_hash")


def collect_relationships(
    model_xbrl: Any, *, canonical_doc_uri: ConceptDocUriResolver
) -> dict[str, Any]:
    """Enumerate effective relationships across exact base sets.

    Returns concept records, resource records, counts, the unsupported
    inventory, and the extraction-completeness report.
    """
    base_sets = getattr(model_xbrl, "baseSets", None) or {}
    exact_keys = [
        key
        for key in base_sets
        if isinstance(key, tuple)
        and len(key) == 4
        and key[0]
        and key[2] is not None
        and key[3] is not None
    ]

    def key_sort(key: tuple[Any, ...]) -> tuple[str, str, str, str]:
        return (
            str(key[0]),
            str(key[1]) if key[1] else "",
            _clark_qname(key[2]) or "",
            _clark_qname(key[3]) or "",
        )

    concept_records: list[dict[str, Any]] = []
    resource_records: list[dict[str, Any]] = []
    seen: dict[str, bytes] = {}
    duplicate_inconsistencies = 0
    unstable_endpoints = 0
    endpoint_family_failures = 0
    base_set_load_failures: list[dict[str, Any]] = []
    endpoint_family_failure_records: list[dict[str, Any]] = []
    encountered: dict[str, int] = {}
    supported_counts: dict[str, int] = {}
    excluded_counts: dict[str, int] = {}
    deferred_counts: dict[str, int] = {}
    unsupported_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}

    for arcrole, linkrole, link_qname, arc_qname in sorted(exact_keys, key=key_sort):
        arcrole_uri = str(arcrole)
        link_clark = _clark_qname(link_qname)
        arc_clark = _clark_qname(arc_qname)
        network = classify_network(arcrole_uri, link_clark=link_clark)
        try:
            rel_set = model_xbrl.relationshipSet(arcrole, linkrole, link_qname, arc_qname)
        except Exception as exc:  # noqa: BLE001
            failure = {
                "failure_code": RELATIONSHIP_SET_LOAD_FAILED,
                "arcrole_uri": arcrole_uri,
                "link_role_uri": str(linkrole) if linkrole else None,
                "link_qname": link_clark,
                "arc_qname": arc_clark,
            }
            base_set_load_failures.append(failure)
            # Operational diagnostics (not semantic identity).
            failure_diagnostic = {
                **failure,
                "exception_class": type(exc).__name__,
                "exception_message": str(exc),
            }
            endpoint_family_failure_records.append(failure_diagnostic)
            continue

        model_rels = list(getattr(rel_set, "modelRelationships", None) or [])
        count = len(model_rels)
        encountered[arcrole_uri] = encountered.get(arcrole_uri, 0) + count
        if network == "excluded":
            excluded_counts[arcrole_uri] = excluded_counts.get(arcrole_uri, 0) + count
            continue
        if network == "deferred":
            deferred_counts[arcrole_uri] = deferred_counts.get(arcrole_uri, 0) + count
            # Deferred generic resource arcroles fail closed for Slice 0.
            unsupported_counts[arcrole_uri] = unsupported_counts.get(arcrole_uri, 0) + count
            continue
        if network == "unsupported":
            unsupported_counts[arcrole_uri] = unsupported_counts.get(arcrole_uri, 0) + count
            continue
        supported_counts[arcrole_uri] = supported_counts.get(arcrole_uri, 0) + count

        for rel in model_rels:
            arc_element = getattr(rel, "arcElement", None)
            if arc_element is None:
                unstable_endpoints += 1
                continue
            arc_doc = getattr(rel, "modelDocument", None)
            arc_doc_uri = canonical_doc_uri(arc_doc) if arc_doc is not None else None
            if arc_doc_uri is None:
                unstable_endpoints += 1
                continue
            arc_record = arc_occurrence_record(arc_element, canonical_document_uri=arc_doc_uri)
            arc_hash = arc_occurrence_hash(arc_record)
            arc_diag = occurrence_provenance(arc_element)

            from_model = getattr(rel, "fromModelObject", None)
            to_model = getattr(rel, "toModelObject", None)
            try:
                from_locator = rel.fromLocator
            except Exception:  # noqa: BLE001
                from_locator = None
            try:
                to_locator = rel.toLocator
            except Exception:  # noqa: BLE001
                to_locator = None

            source_identity, source_resolved, source_stable, source_fail = (
                endpoint_occurrence_identity(
                    from_model, from_locator, canonical_doc_uri=canonical_doc_uri
                )
            )
            target_identity, target_resolved, target_stable, target_fail = (
                endpoint_occurrence_identity(
                    to_model, to_locator, canonical_doc_uri=canonical_doc_uri
                )
            )
            if not source_stable or not target_stable:
                unstable_endpoints += 1
                code = source_fail or target_fail or ENDPOINT_FAMILY_MISMATCH
                endpoint_family_failures += 1
                endpoint_family_failure_records.append(
                    {
                        "failure_code": code,
                        "arcrole_uri": arcrole_uri,
                        "arc_occurrence_hash": arc_hash,
                        "source_stable": source_stable,
                        "target_stable": target_stable,
                    }
                )

            # Endpoint-family topology checks for supported networks.
            family_ok = True
            if network in ("presentation", "calculation", "definition"):
                src_concept = _concept_clark(from_model)
                tgt_concept = _concept_clark(to_model)
                if src_concept is None or tgt_concept is None:
                    family_ok = False
                    endpoint_family_failures += 1
                    endpoint_family_failure_records.append(
                        {
                            "failure_code": ENDPOINT_FAMILY_MISMATCH,
                            "arcrole_uri": arcrole_uri,
                            "arc_occurrence_hash": arc_hash,
                            "reason": "concept_network_requires_concept_endpoints",
                        }
                    )
            elif network == "resource":
                src_concept = _concept_clark(from_model)
                resource_ok = False
                if to_model is not None:
                    local_name = getattr(to_model, "localName", None)
                    namespace = getattr(to_model, "namespaceURI", None)
                    if namespace == LINK_NS and local_name in ("label", "reference"):
                        resource_ok = True
                if src_concept is None or not resource_ok:
                    family_ok = False
                    endpoint_family_failures += 1
                    endpoint_family_failure_records.append(
                        {
                            "failure_code": ENDPOINT_FAMILY_MISMATCH,
                            "arcrole_uri": arcrole_uri,
                            "arc_occurrence_hash": arc_hash,
                            "reason": "resource_network_requires_label_or_reference_target",
                        }
                    )

            if not family_ok:
                unstable_endpoints += 1

            rel_hash = relationship_occurrence_hash(
                arc_hash, _endpoint_hash(source_identity), _endpoint_hash(target_identity)
            )

            fields: dict[str, Any] = {
                "network_type": network,
                "arcrole_uri": arcrole_uri,
                "link_role_uri": str(linkrole) if linkrole else None,
                "order": _decimal_or_none(getattr(rel, "order", None)),
                "arc_occurrence_hash": arc_hash,
                "source_endpoint_occurrence_identity": source_identity,
                "target_endpoint_occurrence_identity": target_identity,
                "source_semantic_identity": source_resolved,
                "target_semantic_identity": target_resolved,
                "relationship_occurrence_hash": rel_hash,
            }

            diagnostic: dict[str, Any] = {
                "arc_provenance": arc_diag,
            }
            if from_locator is not None:
                diagnostic["source_locator_provenance"] = occurrence_provenance(from_locator)
            if to_locator is not None:
                diagnostic["target_locator_provenance"] = occurrence_provenance(to_locator)

            if network == "resource":
                resource = None
                if to_model is not None:
                    local_name = getattr(to_model, "localName", None)
                    namespace = getattr(to_model, "namespaceURI", None)
                    if namespace == LINK_NS and local_name in ("label", "reference"):
                        doc = getattr(to_model, "modelDocument", None)
                        doc_uri = canonical_doc_uri(doc) if doc is not None else None
                        if doc_uri is not None:
                            resource = serialize_resource(
                                to_model,
                                resource_type=local_name,
                                canonical_document_uri=doc_uri,
                            )
                if resource is None:
                    unstable_endpoints += 1
                    endpoint_family_failures += 1
                fields.update(
                    {
                        "source_concept": _concept_clark(from_model),
                        "resource_relationship_kind": (
                            "concept_label"
                            if arcrole_uri == CONCEPT_LABEL_ARCROLE
                            else "concept_reference"
                        ),
                        "resource_occurrence_hash": (
                            resource["resource_occurrence_hash"] if resource else None
                        ),
                        "resource_content_hash": (
                            resource["resource_content_hash"] if resource else None
                        ),
                    }
                )
                if resource is not None:
                    diagnostic["resource_diagnostic_provenance"] = resource.get(
                        "diagnostic_provenance"
                    )
                    diagnostic["resource_full"] = resource
                target_records = resource_records
                family_key = fields["resource_relationship_kind"]
            else:
                fields.update(
                    {
                        "source_concept": _concept_clark(from_model),
                        "target_concept": _concept_clark(to_model),
                        "weight": _decimal_or_none(getattr(rel, "weight", None)),
                        "preferred_label_role": _str_or_none(getattr(rel, "preferredLabel", None)),
                        "target_role": _str_or_none(getattr(rel, "targetRole", None)),
                        "closed": _bool_or_none(getattr(rel, "closed", None)),
                        "usable": _bool_or_none(getattr(rel, "usable", None)),
                        "context_element": _str_or_none(getattr(rel, "contextElement", None)),
                    }
                )
                target_records = concept_records
                family_key = network

            canonical = canonical_relationship_record(fields)
            inspection_record = {
                "canonical_record": canonical,
                "diagnostic_provenance": diagnostic,
            }
            # Convenience mirrors used by evidence projections / tests.
            inspection_record.update(fields)

            canonical_bytes = canonical_json_bytes(canonical)
            prior = seen.get(rel_hash)
            if prior is not None:
                if prior != canonical_bytes:
                    duplicate_inconsistencies += 1
                continue
            seen[rel_hash] = canonical_bytes
            target_records.append(inspection_record)
            family_counts[family_key] = family_counts.get(family_key, 0) + 1

    concept_records.sort(key=lambda r: canonical_json_bytes(r["canonical_record"]))
    resource_records.sort(key=lambda r: canonical_json_bytes(r["canonical_record"]))

    # Semantic failure inventory: stable codes only (no exception text).
    semantic_base_set_failures = [
        {
            "failure_code": f["failure_code"],
            "arcrole_uri": f["arcrole_uri"],
            "link_role_uri": f["link_role_uri"],
            "link_qname": f["link_qname"],
            "arc_qname": f["arc_qname"],
        }
        for f in base_set_load_failures
    ]

    unsupported_total = sum(unsupported_counts.values())
    deferred_total = sum(deferred_counts.values())
    extraction_complete = (
        unstable_endpoints == 0
        and unsupported_total == 0
        and deferred_total == 0
        and duplicate_inconsistencies == 0
        and len(base_set_load_failures) == 0
        and endpoint_family_failures == 0
    )

    return {
        "concept_records": concept_records,
        "resource_records": resource_records,
        "relationship_counts": {
            "presentation": family_counts.get("presentation", 0),
            "calculation": family_counts.get("calculation", 0),
            "definition": family_counts.get("definition", 0),
            "resource": sum(
                family_counts.get(k, 0) for k in ("concept_label", "concept_reference")
            ),
        },
        "resource_relationship_counts": {
            "concept_label": family_counts.get("concept_label", 0),
            "concept_reference": family_counts.get("concept_reference", 0),
        },
        "unsupported_inventory": {
            "encountered_arcrole_counts": dict(sorted(encountered.items())),
            "supported_arcrole_counts": dict(sorted(supported_counts.items())),
            "excluded_arcrole_counts": dict(sorted(excluded_counts.items())),
            "deferred_arcrole_counts": dict(sorted(deferred_counts.items())),
            "unsupported_arcrole_counts": dict(sorted(unsupported_counts.items())),
            "deferred_generic_resource_arcroles": sorted(DEFERRED_GENERIC_RESOURCE_ARCROLES),
        },
        "extraction": {
            "extraction_complete": extraction_complete,
            "unstable_endpoint_occurrence_count": unstable_endpoints,
            "unsupported_failing_relationship_count": unsupported_total + deferred_total,
            "duplicate_occurrence_inconsistency_count": duplicate_inconsistencies,
            "base_set_load_failure_count": len(base_set_load_failures),
            "endpoint_family_failure_count": endpoint_family_failures,
            "base_set_load_failures": semantic_base_set_failures,
            "endpoint_family_failure_records": [
                {k: v for k, v in rec.items() if k not in ("exception_class", "exception_message")}
                for rec in endpoint_family_failure_records
                if rec.get("failure_code") != RELATIONSHIP_SET_LOAD_FAILED
                or "exception_class" not in rec
            ],
        },
    }
