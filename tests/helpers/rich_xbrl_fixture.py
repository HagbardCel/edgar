"""Rich ordinary XBRL fixture bytes for semantic acceptance tests."""

from __future__ import annotations

from edgar.xbrl.uri import normalize_uri

NS = "http://example.com/rich"
SCHEMA_URI = normalize_uri("https://example.com/rich.xsd")
INSTANCE_URI = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000009/a.xml")
PRES_URI = normalize_uri("https://example.com/rich-presentation.xml")
CALC_URI = normalize_uri("https://example.com/rich-calculation.xml")
DEFN_URI = normalize_uri("https://example.com/rich-definition.xml")
LAB_URI = normalize_uri("https://example.com/rich-label.xml")
REF_URI = normalize_uri("https://example.com/rich-reference.xml")

SCHEMA = f"""<?xml version="1.0"?>
<schema xmlns="http://www.w3.org/2001/XMLSchema"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:xbrldt="http://xbrl.org/2005/xbrldt"
        xmlns:link="http://www.xbrl.org/2003/linkbase"
        xmlns:xlink="http://www.w3.org/1999/xlink"
        targetNamespace="{NS}"
        elementFormDefault="qualified"
        xmlns:t="{NS}">
  <import namespace="http://www.xbrl.org/2003/instance"
          schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
  <import namespace="http://xbrl.org/2005/xbrldt"
          schemaLocation="http://www.xbrl.org/2005/xbrldt-2005.xsd"/>
  <annotation>
    <appinfo>
      <link:roleType roleURI="http://example.com/role/Statement" id="Statement">
        <link:definition>Statement</link:definition>
        <link:usedOn>link:presentationLink</link:usedOn>
        <link:usedOn>link:calculationLink</link:usedOn>
        <link:usedOn>link:definitionLink</link:usedOn>
      </link:roleType>
      <link:arcroleType arcroleURI="http://example.com/arcrole/custom" id="customArc"
                       cyclesAllowed="undirected">
        <link:definition>Custom arcrole</link:definition>
        <link:usedOn>link:definitionArc</link:usedOn>
      </link:arcroleType>
      <link:linkbaseRef xlink:type="simple" xlink:href="{PRES_URI}"
        xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/>
      <link:linkbaseRef xlink:type="simple" xlink:href="{CALC_URI}"
        xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/>
      <link:linkbaseRef xlink:type="simple" xlink:href="{DEFN_URI}"
        xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/>
      <link:linkbaseRef xlink:type="simple" xlink:href="{LAB_URI}"
        xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/>
      <link:linkbaseRef xlink:type="simple" xlink:href="{REF_URI}"
        xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/>
    </appinfo>
  </annotation>
  <element name="Abstract" id="t_Abstract" type="xbrli:stringItemType"
           substitutionGroup="xbrli:item" abstract="true" nillable="true"
           xbrli:periodType="duration"/>
  <element name="Assets" id="t_Assets" type="xbrli:monetaryItemType"
           substitutionGroup="xbrli:item" nillable="true"
           xbrli:periodType="duration" xbrli:balance="debit"/>
  <element name="Liabilities" id="t_Liabilities" type="xbrli:monetaryItemType"
           substitutionGroup="xbrli:item" nillable="true"
           xbrli:periodType="duration" xbrli:balance="credit"/>
  <element name="Equity" id="t_Equity" type="xbrli:monetaryItemType"
           substitutionGroup="xbrli:item" nillable="true"
           xbrli:periodType="duration" xbrli:balance="credit"/>
  <element name="TextNote" id="t_TextNote" type="xbrli:stringItemType"
           substitutionGroup="xbrli:item" nillable="true" xbrli:periodType="duration"/>
  <element name="Flag" id="t_Flag" type="xbrli:booleanItemType"
           substitutionGroup="xbrli:item" nillable="true" xbrli:periodType="duration"/>
  <element name="AsOfDate" id="t_AsOfDate" type="xbrli:dateItemType"
           substitutionGroup="xbrli:item" nillable="true" xbrli:periodType="duration"/>
  <element name="AsOfDateTime" id="t_AsOfDateTime" type="xbrli:dateTimeItemType"
           substitutionGroup="xbrli:item" nillable="true" xbrli:periodType="duration"/>
  <element name="AsOfTime" id="t_AsOfTime" type="xbrli:timeItemType"
           substitutionGroup="xbrli:item" nillable="true" xbrli:periodType="duration"/>
  <element name="RelatedConcept" id="t_RelatedConcept" type="xbrli:QNameItemType"
           substitutionGroup="xbrli:item" nillable="true" xbrli:periodType="duration"/>
  <element name="NilNote" id="t_NilNote" type="xbrli:stringItemType"
           substitutionGroup="xbrli:item" nillable="true" xbrli:periodType="duration"/>
  <element name="Table" id="t_Table" type="xbrli:stringItemType"
           substitutionGroup="xbrldt:hypercubeItem" abstract="true"
           nillable="true" xbrli:periodType="duration"/>
  <element name="ExplicitAxis" id="t_ExplicitAxis" type="xbrli:stringItemType"
           substitutionGroup="xbrldt:dimensionItem" abstract="true"
           nillable="true" xbrli:periodType="duration"/>
  <element name="Domain" id="t_Domain" type="xbrli:stringItemType"
           substitutionGroup="xbrli:item" abstract="true"
           nillable="true" xbrli:periodType="duration"/>
  <element name="MemberA" id="t_MemberA" type="xbrli:stringItemType"
           substitutionGroup="xbrli:item" abstract="true"
           nillable="true" xbrli:periodType="duration"/>
  <element name="TypedAxis" id="t_TypedAxis" type="xbrli:stringItemType"
           substitutionGroup="xbrldt:dimensionItem" abstract="true"
           nillable="true" xbrli:periodType="duration"
           xbrldt:typedDomainRef="#t_TypedDomain"/>
  <element name="TypedDomain" id="t_TypedDomain" type="xs:string"
           xmlns:xs="http://www.w3.org/2001/XMLSchema"/>
</schema>
""".encode()

PRESENTATION = f"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:roleRef roleURI="http://example.com/role/Statement" xlink:type="simple"
                xlink:href="{SCHEMA_URI}#Statement"/>
  <link:presentationLink xlink:type="extended" xlink:role="http://example.com/role/Statement">
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Abstract" xlink:label="Abstract"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Assets" xlink:label="Assets"/>
    <link:presentationArc xlink:type="arc"
      xlink:arcrole="http://www.xbrl.org/2003/arcrole/parent-child"
      xlink:from="Abstract" xlink:to="Assets" order="1.0"/>
  </link:presentationLink>
</link:linkbase>
""".encode()

CALCULATION = f"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:roleRef roleURI="http://example.com/role/Statement" xlink:type="simple"
                xlink:href="{SCHEMA_URI}#Statement"/>
  <link:calculationLink xlink:type="extended" xlink:role="http://example.com/role/Statement">
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Equity" xlink:label="Equity"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Assets" xlink:label="Assets"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Liabilities"
              xlink:label="Liabilities"/>
    <link:calculationArc xlink:type="arc"
      xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item"
      xlink:from="Equity" xlink:to="Assets" order="1.0" weight="1"/>
    <link:calculationArc xlink:type="arc"
      xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item"
      xlink:from="Equity" xlink:to="Liabilities" order="2.0" weight="-1"/>
  </link:calculationLink>
</link:linkbase>
""".encode()

DEFINITION = f"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink"
               xmlns:xbrldt="http://xbrl.org/2005/xbrldt">
  <link:roleRef roleURI="http://example.com/role/Statement" xlink:type="simple"
                xlink:href="{SCHEMA_URI}#Statement"/>
  <link:arcroleRef arcroleURI="http://xbrl.org/int/dim/arcrole/all" xlink:type="simple"
                   xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#all"/>
  <link:arcroleRef arcroleURI="http://xbrl.org/int/dim/arcrole/hypercube-dimension"
                   xlink:type="simple"
                   xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#hypercube-dimension"/>
  <link:arcroleRef arcroleURI="http://xbrl.org/int/dim/arcrole/dimension-domain"
                   xlink:type="simple"
                   xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#dimension-domain"/>
  <link:arcroleRef arcroleURI="http://xbrl.org/int/dim/arcrole/domain-member"
                   xlink:type="simple"
                   xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#domain-member"/>
  <link:definitionLink xlink:type="extended" xlink:role="http://example.com/role/Statement">
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Assets" xlink:label="Assets"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Equity" xlink:label="Equity"/>
    <link:definitionArc xlink:type="arc"
      xlink:arcrole="http://www.xbrl.org/2003/arcrole/general-special"
      xlink:from="Equity" xlink:to="Assets" order="1.0"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Abstract" xlink:label="LineItems"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Table" xlink:label="Table"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_ExplicitAxis"
              xlink:label="ExplicitAxis"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Domain" xlink:label="Domain"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_MemberA" xlink:label="MemberA"/>
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_TypedAxis" xlink:label="TypedAxis"/>
    <link:definitionArc xlink:type="arc" xlink:arcrole="http://xbrl.org/int/dim/arcrole/all"
      xlink:from="LineItems" xlink:to="Table" order="1.0"
      xbrldt:contextElement="segment" xbrldt:closed="true"/>
    <link:definitionArc xlink:type="arc"
      xlink:arcrole="http://xbrl.org/int/dim/arcrole/hypercube-dimension"
      xlink:from="Table" xlink:to="ExplicitAxis" order="1.0"/>
    <link:definitionArc xlink:type="arc"
      xlink:arcrole="http://xbrl.org/int/dim/arcrole/hypercube-dimension"
      xlink:from="Table" xlink:to="TypedAxis" order="2.0"/>
    <link:definitionArc xlink:type="arc"
      xlink:arcrole="http://xbrl.org/int/dim/arcrole/dimension-domain"
      xlink:from="ExplicitAxis" xlink:to="Domain" order="1.0"/>
    <link:definitionArc xlink:type="arc"
      xlink:arcrole="http://xbrl.org/int/dim/arcrole/domain-member"
      xlink:from="Domain" xlink:to="MemberA" order="1.0"/>
  </link:definitionLink>
</link:linkbase>
""".encode()

LABEL = f"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink"
               xmlns:xml="http://www.w3.org/XML/1998/namespace">
  <link:labelLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Assets" xlink:label="Assets"/>
    <link:labelArc xlink:type="arc"
      xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label"
      xlink:from="Assets" xlink:to="lab1" order="1.0"/>
    <link:label xlink:type="resource" xlink:label="lab1"
      xlink:role="http://www.xbrl.org/2003/role/label" xml:lang="en">Assets</link:label>
    <link:labelArc xlink:type="arc"
      xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label"
      xlink:from="Assets" xlink:to="lab2" order="2.0"/>
    <link:label xlink:type="resource" xlink:label="lab2"
      xlink:role="http://www.xbrl.org/2003/role/terseLabel" xml:lang="en">Assets terse</link:label>
    <link:labelArc xlink:type="arc"
      xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label"
      xlink:from="Assets" xlink:to="lab3" order="3.0"/>
    <link:label xlink:type="resource" xlink:label="lab3"
      xlink:role="http://www.xbrl.org/2003/role/documentation"
      xml:lang="en">Assets documentation</link:label>
  </link:labelLink>
</link:linkbase>
""".encode()

REFERENCE = f"""<?xml version="1.0"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink"
               xmlns:ref="http://www.xbrl.org/2006/ref">
  <link:referenceLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">
    <link:loc xlink:type="locator" xlink:href="{SCHEMA_URI}#t_Assets" xlink:label="Assets"/>
    <link:referenceArc xlink:type="arc"
      xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-reference"
      xlink:from="Assets" xlink:to="ref1" order="1.0"/>
    <link:reference xlink:type="resource" xlink:label="ref1"
      xlink:role="http://www.xbrl.org/2003/role/reference">
      <ref:Name>NamePart</ref:Name>
      <ref:Number>42</ref:Number>
      <ref:Paragraph xmlns:custom="http://example.com/custom">
        <custom:Note>structured</custom:Note>
      </ref:Paragraph>
    </link:reference>
    <link:referenceArc xlink:type="arc"
      xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-reference"
      xlink:from="Assets" xlink:to="ref2" order="2.0"/>
    <link:reference xlink:type="resource" xlink:label="ref2"
      xlink:role="http://www.xbrl.org/2003/role/definitionRef">
      <ref:Name>DefinitionRef</ref:Name>
    </link:reference>
    <link:referenceArc xlink:type="arc"
      xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-reference"
      xlink:from="Assets" xlink:to="ref3" order="3.0"/>
    <link:reference xlink:type="resource" xlink:label="ref3"
      xlink:role="http://www.xbrl.org/2003/role/disclosureRef">
      <ref:Name>DisclosureRef</ref:Name>
    </link:reference>
  </link:referenceLink>
</link:linkbase>
""".encode()

INSTANCE = f"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
            xmlns:t="{NS}">
  <link:schemaRef xlink:type="simple" xlink:href="{SCHEMA_URI}"/>
  <xbrli:context id="cDur">
    <xbrli:entity>
      <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
    </xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2024-01-01</xbrli:startDate>
      <xbrli:endDate>2024-12-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>
  <xbrli:context id="cExp">
    <xbrli:entity>
      <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="t:ExplicitAxis">t:MemberA</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2024-01-01</xbrli:startDate>
      <xbrli:endDate>2024-12-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>
  <xbrli:context id="cTyped">
    <xbrli:entity>
      <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:typedMember dimension="t:TypedAxis">
          <t:TypedDomain>typed-value</t:TypedDomain>
        </xbrldi:typedMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2024-01-01</xbrli:startDate>
      <xbrli:endDate>2024-12-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>
  <xbrli:unit id="u1"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <t:Assets contextRef="cDur" unitRef="u1" id="fAssets">100</t:Assets>
  <t:Liabilities contextRef="cDur" unitRef="u1" decimals="INF" id="fLiab">40</t:Liabilities>
  <t:Equity contextRef="cDur" unitRef="u1" decimals="INF" id="fEq">60</t:Equity>
  <t:Assets contextRef="cExp" unitRef="u1" decimals="INF" id="fExp">10</t:Assets>
  <t:Assets contextRef="cTyped" unitRef="u1" decimals="INF" id="fTyped">5</t:Assets>
  <t:TextNote contextRef="cDur" id="fText">{{foo}}bar</t:TextNote>
  <t:Flag contextRef="cDur" id="fFlag">true</t:Flag>
  <t:AsOfDate contextRef="cDur" id="fDate">2024-06-15</t:AsOfDate>
  <t:AsOfDateTime contextRef="cDur" id="fDateTime">2024-06-15T12:30:00</t:AsOfDateTime>
  <t:AsOfTime contextRef="cDur" id="fTime">12:30:00</t:AsOfTime>
  <t:RelatedConcept contextRef="cDur" id="fQName">t:Assets</t:RelatedConcept>
  <t:NilNote contextRef="cDur" xsi:nil="true" id="fNil"/>
</xbrli:xbrl>
""".encode()
