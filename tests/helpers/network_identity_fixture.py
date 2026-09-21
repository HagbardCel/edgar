"""FilingBundles that collide under pre-M1A-2 network identity (role/arcrole only).

Case A differs only in link QName (custom ``altPresentationLink``).
Case B differs only in arc QName (custom ``altPresentationArc``).
"""

from __future__ import annotations

from edgar.domain.bundle import BundleArtifact, ContentObject, FilingBundle, InstanceReportInput
from edgar.storage.objects import ObjectStore
from edgar.xbrl.closure import run_online_closure
from edgar.xbrl.records import ExpandedQName
from edgar.xbrl.source_records import RelationshipRecord
from edgar.xbrl.uri import normalize_uri
from tests.helpers.arelle_cache_fetcher import ArelleCacheFetcher
from tests.helpers.xbrl_bundles import _bundle_from_discovery

NS = "http://example.com/netid"
SCHEMA_URI = normalize_uri("https://example.com/netid.xsd")
INSTANCE_URI = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000021/a.xml")
PRES_URI = normalize_uri("https://example.com/netid-presentation.xml")
ROLE_URI = "http://example.com/role/Statement"
PARENT_CHILD = "http://www.xbrl.org/2003/arcrole/parent-child"

ALT_PRESENTATION_LINK = ExpandedQName(namespace_uri=NS, local_name="altPresentationLink")
ALT_PRESENTATION_ARC = ExpandedQName(namespace_uri=NS, local_name="altPresentationArc")

_SCHEMA = f"""<?xml version="1.0"?>
<schema xmlns="http://www.w3.org/2001/XMLSchema"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:link="http://www.xbrl.org/2003/linkbase"
        xmlns:xlink="http://www.w3.org/1999/xlink"
        targetNamespace="{NS}"
        elementFormDefault="qualified"
        xmlns:t="{NS}">
  <import namespace="http://www.xbrl.org/2003/instance"
          schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
  <import namespace="http://www.xbrl.org/2003/linkbase"
          schemaLocation="http://www.xbrl.org/2003/xbrl-linkbase-2003-12-31.xsd"/>
  <annotation>
    <appinfo>
      <link:roleType roleURI="{ROLE_URI}" id="Statement">
        <link:definition>Statement</link:definition>
        <link:usedOn>link:presentationLink</link:usedOn>
        <link:usedOn>t:altPresentationLink</link:usedOn>
      </link:roleType>
      <link:linkbaseRef xlink:type="simple" xlink:href="{PRES_URI}"
        xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/>
    </appinfo>
  </annotation>
  <element name="altPresentationLink" substitutionGroup="link:presentationLink"/>
  <element name="altPresentationArc" substitutionGroup="link:presentationArc"/>
  <element name="Abstract" id="t_Abstract" type="xbrli:stringItemType"
           substitutionGroup="xbrli:item" abstract="true" nillable="true"
           xbrli:periodType="instant"/>
  <element name="Assets" id="t_Assets" type="xbrli:monetaryItemType"
           substitutionGroup="xbrli:item" nillable="true"
           xbrli:periodType="instant" xbrli:balance="debit"/>
</schema>
""".encode()

_INSTANCE = f"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
            xmlns:t="{NS}">
  <link:schemaRef xlink:type="simple" xlink:href="{SCHEMA_URI}"/>
  <xbrli:context id="c1">
    <xbrli:entity>
      <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="u1"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <t:Assets contextRef="c1" unitRef="u1" decimals="INF" id="f1">100</t:Assets>
</xbrli:xbrl>
""".encode()

_LINK_COLLISION_PRESENTATION = f"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink"
               xmlns:t="{NS}">
  <link:roleRef roleURI="{ROLE_URI}" xlink:type="simple"
                xlink:href="{SCHEMA_URI}#Statement"/>
  <link:presentationLink xlink:type="extended" xlink:role="{ROLE_URI}">
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Abstract" xlink:label="Abstract"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Assets" xlink:label="Assets"/>
    <link:presentationArc xlink:type="arc" xlink:arcrole="{PARENT_CHILD}"
      xlink:from="Abstract" xlink:to="Assets" order="1.0"/>
  </link:presentationLink>
  <t:altPresentationLink xlink:type="extended" xlink:role="{ROLE_URI}">
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Abstract" xlink:label="Abstract"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Assets" xlink:label="Assets"/>
    <link:presentationArc xlink:type="arc" xlink:arcrole="{PARENT_CHILD}"
      xlink:from="Abstract" xlink:to="Assets" order="1.0"/>
  </t:altPresentationLink>
</link:linkbase>
""".encode()

_ARC_COLLISION_PRESENTATION = f"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink"
               xmlns:t="{NS}">
  <link:roleRef roleURI="{ROLE_URI}" xlink:type="simple"
                xlink:href="{SCHEMA_URI}#Statement"/>
  <link:presentationLink xlink:type="extended" xlink:role="{ROLE_URI}">
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Abstract" xlink:label="Abstract"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Assets" xlink:label="Assets"/>
    <link:presentationArc xlink:type="arc" xlink:arcrole="{PARENT_CHILD}"
      xlink:from="Abstract" xlink:to="Assets" order="1.0"/>
  </link:presentationLink>
  <link:presentationLink xlink:type="extended" xlink:role="{ROLE_URI}">
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Abstract" xlink:label="Abstract"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Assets" xlink:label="Assets"/>
    <t:altPresentationArc xlink:type="arc" xlink:arcrole="{PARENT_CHILD}"
      xlink:from="Abstract" xlink:to="Assets" order="1.0"/>
  </link:presentationLink>
</link:linkbase>
""".encode()


def pre_m1a2_semantic_key(rel: RelationshipRecord) -> tuple[object, ...]:
    """Pre-M1A-2 network identity: excludes source_order and link/arc QNames."""
    attrs = rel.attributes or {}
    return (
        rel.network_type,
        rel.arcrole_uri,
        rel.link_role_uri,
        rel.source_concept,
        rel.target_concept,
        rel.order_value,
        rel.weight,
        rel.preferred_label,
        rel.target_role,
        attrs.get("closed"),
        attrs.get("usable"),
        attrs.get("context_element"),
    )


def _make_bundle(
    store: ObjectStore,
    *,
    presentation: bytes,
    accession: str,
) -> FilingBundle:
    instance_obj = store.put_bytes(_INSTANCE)
    report = InstanceReportInput(document_uris=(INSTANCE_URI,))
    mapping = {SCHEMA_URI: _SCHEMA, PRES_URI: presentation}
    discovery = run_online_closure(
        report,
        accession_uri_map={INSTANCE_URI: (instance_obj.sha256, "accession/a.xml")},
        store=store,
        fetcher=ArelleCacheFetcher(mapping),  # type: ignore[arg-type]
        max_file_bytes=5_000_000,
        max_new_payload_bytes=50_000_000,
    )
    if (
        not discovery.load_completed
        or discovery.errors
        or discovery.unresolved_documents
        or discovery.network_attempts
    ):
        raise RuntimeError(
            "network-identity fixture discovery failed: "
            f"errors={discovery.errors!r} unresolved={discovery.unresolved_documents!r}"
        )
    return _bundle_from_discovery(
        store=store,
        report=report,
        discovery=discovery,
        accession_artifacts=[
            BundleArtifact(
                "accession/a.xml",
                ContentObject(instance_obj.sha256, instance_obj.byte_size),
                "primary_document",
                True,
            ),
        ],
        accession=accession,
        primary="a.xml",
    )


def make_link_qname_collision_bundle(store: ObjectStore) -> FilingBundle:
    return _make_bundle(
        store, presentation=_LINK_COLLISION_PRESENTATION, accession="0000000001-00-000021"
    )


def make_arc_qname_collision_bundle(store: ObjectStore) -> FilingBundle:
    return _make_bundle(
        store, presentation=_ARC_COLLISION_PRESENTATION, accession="0000000001-00-000022"
    )
