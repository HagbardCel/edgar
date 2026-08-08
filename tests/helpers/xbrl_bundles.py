"""Shared synthetic XBRL FilingBundle builders for contract/integration tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import arelle

from edgar.domain.bundle import (
    BundleArtifact,
    ContentObject,
    FilingBundle,
    FilingIdentity,
    InstanceReportInput,
    UriBinding,
)
from edgar.domain.identifiers import sanitize_basename, validate_cik
from edgar.domain.payload import compute_payload_hash
from edgar.storage.objects import ObjectStore
from edgar.xbrl.uri import normalize_uri, sha256_of_uri

_ARELLE_CACHE = (
    Path(arelle.__file__).resolve().parent
    / "resources"
    / "cache"
    / "http"
    / "www.xbrl.org"
    / "2003"
)
_ARELLE_CACHE_2005 = (
    Path(arelle.__file__).resolve().parent
    / "resources"
    / "cache"
    / "http"
    / "www.xbrl.org"
    / "2005"
)

SCHEMA = b"""<?xml version="1.0"?>
<schema xmlns="http://www.w3.org/2001/XMLSchema"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        targetNamespace="http://example.com/test"
        elementFormDefault="qualified">
  <import namespace="http://www.xbrl.org/2003/instance"
          schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
  <element name="Assets" id="test_Assets" type="xbrli:monetaryItemType"
           substitutionGroup="xbrli:item" nillable="true"
           xbrli:periodType="instant" xbrli:balance="debit"/>
</schema>
"""

INSTANCE = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
            xmlns:t="http://example.com/test">
  <link:schemaRef xlink:type="simple" xlink:href="https://example.com/test.xsd"/>
  <xbrli:context id="c1">
    <xbrli:entity>
      <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="u1"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <t:Assets contextRef="c1" unitRef="u1" decimals="INF" id="f1">100</t:Assets>
  <t:Assets contextRef="c1" unitRef="u1" decimals="INF" id="f2">100</t:Assets>
</xbrli:xbrl>
"""

# Two measures filed in reverse lexical order; extractor must sort by expanded QName.
INSTANCE_UNIT_ORDER = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:a="http://example.com/a"
            xmlns:b="http://example.com/b"
            xmlns:t="http://example.com/test">
  <link:schemaRef xlink:type="simple" xlink:href="https://example.com/test.xsd"/>
  <xbrli:context id="c1">
    <xbrli:entity>
      <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="uShare">
    <xbrli:divide>
      <xbrli:unitNumerator>
        <xbrli:measure>b:Zebra</xbrli:measure>
        <xbrli:measure>a:Alpha</xbrli:measure>
      </xbrli:unitNumerator>
      <xbrli:unitDenominator>
        <xbrli:measure>b:Shares</xbrli:measure>
      </xbrli:unitDenominator>
    </xbrli:divide>
  </xbrli:unit>
  <t:Assets contextRef="c1" unitRef="uShare" decimals="0" id="f1">1</t:Assets>
</xbrli:xbrl>
"""

# Dimension taxonomy with a default member; instance context has no Axis occurrence.
DIM_SCHEMA = b"""<?xml version="1.0"?>
<schema xmlns="http://www.w3.org/2001/XMLSchema"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:xbrldt="http://xbrl.org/2005/xbrldt"
        xmlns:link="http://www.xbrl.org/2003/linkbase"
        xmlns:xlink="http://www.w3.org/1999/xlink"
        targetNamespace="http://example.com/dim"
        elementFormDefault="qualified"
        xmlns:t="http://example.com/dim">
  <import namespace="http://www.xbrl.org/2003/instance"
          schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
  <import namespace="http://xbrl.org/2005/xbrldt"
          schemaLocation="http://www.xbrl.org/2005/xbrldt-2005.xsd"/>
  <annotation>
    <appinfo>
      <link:roleType roleURI="http://example.com/role/Statement" id="Statement">
        <link:definition>Statement</link:definition>
        <link:usedOn>link:definitionLink</link:usedOn>
      </link:roleType>
      <link:linkbaseRef xlink:type="simple"
        xlink:href="https://example.com/dim-definition.xml"
        xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/>
    </appinfo>
  </annotation>
  <element name="Assets" id="t_Assets" type="xbrli:monetaryItemType"
           substitutionGroup="xbrli:item" nillable="true"
           xbrli:periodType="instant" xbrli:balance="debit"/>
  <element name="Table" id="t_Table" type="xbrli:stringItemType"
           substitutionGroup="xbrldt:hypercubeItem" abstract="true"
           nillable="true" xbrli:periodType="duration"/>
  <element name="Axis" id="t_Axis" type="xbrli:stringItemType"
           substitutionGroup="xbrldt:dimensionItem" abstract="true"
           nillable="true" xbrli:periodType="duration"/>
  <element name="Domain" id="t_Domain" type="xbrli:stringItemType"
           substitutionGroup="xbrli:item" abstract="true"
           nillable="true" xbrli:periodType="duration"/>
  <element name="DefaultMember" id="t_DefaultMember" type="xbrli:stringItemType"
           substitutionGroup="xbrli:item" abstract="true"
           nillable="true" xbrli:periodType="duration"/>
  <element name="LineItems" id="t_LineItems" type="xbrli:stringItemType"
           substitutionGroup="xbrli:item" abstract="true"
           nillable="true" xbrli:periodType="duration"/>
</schema>
"""

DIM_DEFINITION = b"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink"
               xmlns:xbrldt="http://xbrl.org/2005/xbrldt"
               xmlns:t="http://example.com/dim">
  <link:roleRef roleURI="http://example.com/role/Statement"
                xlink:type="simple"
                xlink:href="https://example.com/dim.xsd#Statement"/>
  <link:definitionLink xlink:type="extended"
                       xlink:role="http://example.com/role/Statement">
    <link:loc xlink:type="locator" xlink:href="https://example.com/dim.xsd#t_LineItems"
              xlink:label="LineItems"/>
    <link:loc xlink:type="locator" xlink:href="https://example.com/dim.xsd#t_Table"
              xlink:label="Table"/>
    <link:loc xlink:type="locator" xlink:href="https://example.com/dim.xsd#t_Axis"
              xlink:label="Axis"/>
    <link:loc xlink:type="locator" xlink:href="https://example.com/dim.xsd#t_Domain"
              xlink:label="Domain"/>
    <link:loc xlink:type="locator" xlink:href="https://example.com/dim.xsd#t_DefaultMember"
              xlink:label="DefaultMember"/>
    <link:definitionArc xlink:type="arc"
      xlink:arcrole="http://xbrl.org/int/dim/arcrole/all"
      xlink:from="LineItems" xlink:to="Table" order="1.0"
      xbrldt:contextElement="segment" xbrldt:closed="true"/>
    <link:definitionArc xlink:type="arc"
      xlink:arcrole="http://xbrl.org/int/dim/arcrole/hypercube-dimension"
      xlink:from="Table" xlink:to="Axis" order="1.0"/>
    <link:definitionArc xlink:type="arc"
      xlink:arcrole="http://xbrl.org/int/dim/arcrole/dimension-domain"
      xlink:from="Axis" xlink:to="Domain" order="1.0"/>
    <link:definitionArc xlink:type="arc"
      xlink:arcrole="http://xbrl.org/int/dim/arcrole/domain-member"
      xlink:from="Domain" xlink:to="DefaultMember" order="1.0"/>
    <link:definitionArc xlink:type="arc"
      xlink:arcrole="http://xbrl.org/int/dim/arcrole/dimension-default"
      xlink:from="Axis" xlink:to="DefaultMember" order="1.0"/>
  </link:definitionLink>
</link:linkbase>
"""

DIM_INSTANCE = b"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
            xmlns:t="http://example.com/dim">
  <link:schemaRef xlink:type="simple" xlink:href="https://example.com/dim.xsd"/>
  <xbrli:context id="c1">
    <xbrli:entity>
      <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="u1"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <t:Assets contextRef="c1" unitRef="u1" decimals="INF" id="f1">100</t:Assets>
</xbrli:xbrl>
"""

SCHEMA_URI = normalize_uri("https://example.com/test.xsd")
INSTANCE_URI = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000001/a.xml")
SCHEMA_ALIAS = normalize_uri("https://alias.example.com/test.xsd")
DIM_SCHEMA_URI = normalize_uri("https://example.com/dim.xsd")
DIM_DEFINITION_URI = normalize_uri("https://example.com/dim-definition.xml")
DIM_INSTANCE_URI = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000002/a.xml")

STANDARD_SCHEMAS = (
    (
        normalize_uri("http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"),
        "xbrl-instance-2003-12-31.xsd",
        _ARELLE_CACHE,
    ),
    (
        normalize_uri("http://www.xbrl.org/2003/xbrl-linkbase-2003-12-31.xsd"),
        "xbrl-linkbase-2003-12-31.xsd",
        _ARELLE_CACHE,
    ),
    (
        normalize_uri("http://www.xbrl.org/2003/xl-2003-12-31.xsd"),
        "xl-2003-12-31.xsd",
        _ARELLE_CACHE,
    ),
    (
        normalize_uri("http://www.xbrl.org/2003/xlink-2003-12-31.xsd"),
        "xlink-2003-12-31.xsd",
        _ARELLE_CACHE,
    ),
    (
        normalize_uri("http://www.xbrl.org/2005/xbrldt-2005.xsd"),
        "xbrldt-2005.xsd",
        _ARELLE_CACHE_2005,
    ),
)


def _external_path(uri: str, basename: str) -> str:
    return f"external/{sha256_of_uri(uri)}/{sanitize_basename(basename)}"


def _standard_artifacts(
    store: ObjectStore, *, include_xbrldt: bool = False
) -> tuple[list[BundleArtifact], list[UriBinding]]:
    artifacts: list[BundleArtifact] = []
    bindings: list[UriBinding] = []
    for uri, filename, cache_dir in STANDARD_SCHEMAS:
        if filename == "xbrldt-2005.xsd" and not include_xbrldt:
            continue
        data = (cache_dir / filename).read_bytes()
        obj = store.put_bytes(data)
        path = _external_path(uri, filename)
        artifacts.append(
            BundleArtifact(
                logical_path=path,
                content=ContentObject(sha256=obj.sha256, byte_size=obj.byte_size),
                artifact_kind="external",
                required=True,
            )
        )
        bindings.append(UriBinding(uri, path, obj.sha256))
    return artifacts, bindings


def _filing(*, accession: str = "0000000001-00-000001") -> FilingIdentity:
    return FilingIdentity(
        cik=validate_cik("1"),
        accession=accession,
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        accepted_at=None,
        report_period_end=None,
        primary_document="a.xml",
    )


def _bundle_from_parts(
    *,
    store: ObjectStore,
    instance_bytes: bytes,
    schema_bytes: bytes,
    schema_uri: str = SCHEMA_URI,
    instance_uri: str = INSTANCE_URI,
    schema_aliases: tuple[str, ...] = (),
    extra_artifacts: list[BundleArtifact] | None = None,
    extra_bindings: list[UriBinding] | None = None,
    include_xbrldt: bool = False,
    accession: str = "0000000001-00-000001",
) -> FilingBundle:
    schema_obj = store.put_bytes(schema_bytes)
    instance_obj = store.put_bytes(instance_bytes)
    schema_path = _external_path(schema_uri, Path(schema_uri).name or "test.xsd")
    artifacts: list[BundleArtifact] = [
        BundleArtifact(
            logical_path="accession/a.xml",
            content=ContentObject(sha256=instance_obj.sha256, byte_size=instance_obj.byte_size),
            artifact_kind="primary_document",
            required=True,
        ),
        BundleArtifact(
            logical_path=schema_path,
            content=ContentObject(sha256=schema_obj.sha256, byte_size=schema_obj.byte_size),
            artifact_kind="external",
            required=True,
        ),
    ]
    bindings: list[UriBinding] = [
        UriBinding(instance_uri, "accession/a.xml", instance_obj.sha256),
        UriBinding(
            schema_uri,
            schema_path,
            schema_obj.sha256,
            replay_aliases=schema_aliases,
        ),
    ]
    std_a, std_b = _standard_artifacts(store, include_xbrldt=include_xbrldt)
    artifacts.extend(std_a)
    bindings.extend(std_b)
    if extra_artifacts:
        artifacts.extend(extra_artifacts)
    if extra_bindings:
        bindings.extend(extra_bindings)
    artifact_tuple = tuple(artifacts)
    binding_tuple = tuple(bindings)
    return FilingBundle(
        filing=_filing(accession=accession),
        payload_hash=compute_payload_hash(artifact_tuple),
        artifacts=artifact_tuple,
        report_inputs=(InstanceReportInput(document_uris=(instance_uri,)),),
        uri_bindings=binding_tuple,
    )


def make_minimal_semantic_bundle(store: ObjectStore) -> FilingBundle:
    """Ordinary XBRL instance with duplicate facts and a 2024-12-31 instant context."""
    return _bundle_from_parts(store=store, instance_bytes=INSTANCE, schema_bytes=SCHEMA)


def make_unit_order_bundle(store: ObjectStore) -> FilingBundle:
    """Unit numerator measures filed out of expanded-QName order."""
    return _bundle_from_parts(store=store, instance_bytes=INSTANCE_UNIT_ORDER, schema_bytes=SCHEMA)


def make_alias_schema_bundle(store: ObjectStore) -> FilingBundle:
    """Schema primary URI with a replay alias (locators must use primary)."""
    # Instance schemaRef points at the alias; binding maps alias → primary.
    instance = INSTANCE.replace(b"https://example.com/test.xsd", SCHEMA_ALIAS.encode("utf-8"))
    return _bundle_from_parts(
        store=store,
        instance_bytes=instance,
        schema_bytes=SCHEMA,
        schema_aliases=(SCHEMA_ALIAS,),
    )


def make_dimensional_default_bundle(store: ObjectStore) -> FilingBundle:
    """DTS has Axis→DefaultMember; instance context has no Axis occurrence."""
    defn_obj = store.put_bytes(DIM_DEFINITION)
    defn_path = _external_path(DIM_DEFINITION_URI, "dim-definition.xml")
    return _bundle_from_parts(
        store=store,
        instance_bytes=DIM_INSTANCE,
        schema_bytes=DIM_SCHEMA,
        schema_uri=DIM_SCHEMA_URI,
        instance_uri=DIM_INSTANCE_URI,
        include_xbrldt=True,
        accession="0000000001-00-000002",
        extra_artifacts=[
            BundleArtifact(
                logical_path=defn_path,
                content=ContentObject(sha256=defn_obj.sha256, byte_size=defn_obj.byte_size),
                artifact_kind="external",
                required=True,
            )
        ],
        extra_bindings=[UriBinding(DIM_DEFINITION_URI, defn_path, defn_obj.sha256)],
    )
