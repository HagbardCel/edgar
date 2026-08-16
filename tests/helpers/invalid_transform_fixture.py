"""Inline XBRL fixture: one valid numeric fact + one invalidTransformation fact."""

from __future__ import annotations

from edgar.xbrl.uri import normalize_uri

SCHEMA_URI = normalize_uri("https://example.com/invalid-transform.xsd")
INLINE_URI = normalize_uri(
    "https://www.sec.gov/Archives/edgar/data/1/0000000001000012/invalid-transform.htm"
)

SCHEMA = b"""<?xml version="1.0"?>
<schema xmlns="http://www.w3.org/2001/XMLSchema"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        targetNamespace="http://example.com/invalid-transform"
        elementFormDefault="qualified">
  <import namespace="http://www.xbrl.org/2003/instance"
          schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
  <element name="Assets" id="it_Assets" type="xbrli:monetaryItemType"
           substitutionGroup="xbrli:item" nillable="true"
           xbrli:periodType="instant"/>
  <element name="Note" id="it_Note" type="xbrli:stringItemType"
           substitutionGroup="xbrli:item" nillable="true"
           xbrli:periodType="instant"/>
</schema>
"""

# SEC legacy transformation namespace is not registered in Arelle 2.43.1 →
# ix11.11.1.2:invalidTransformation on the Note fact; Assets remains valid.
INLINE = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2015-02-26"
      xmlns:ixt-sec="http://www.sec.gov/inlineXBRL/transformation/2015-08-31"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:link="http://www.xbrl.org/2003/linkbase"
      xmlns:xlink="http://www.w3.org/1999/xlink"
      xmlns:t="http://example.com/invalid-transform"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
  <head><title>invalid-transform</title></head>
  <body>
    <div>
      <ix:header>
        <ix:references>
          <link:schemaRef xlink:type="simple"
            xlink:href="https://example.com/invalid-transform.xsd"/>
        </ix:references>
        <ix:resources>
          <xbrli:context id="c1">
            <xbrli:entity>
              <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
          </xbrli:context>
          <xbrli:unit id="u1"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
        </ix:resources>
      </ix:header>
      <p>
        <ix:nonFraction name="t:Assets" contextRef="c1" unitRef="u1"
                        decimals="INF" scale="0" id="fvalid"
                        format="ixt:numdotdecimal">1234.56</ix:nonFraction>
      </p>
      <p>
        <ix:nonNumeric name="t:Note" contextRef="c1" id="finvalid"
                       format="ixt-sec:datemonthdayyear">January 1, 2024</ix:nonNumeric>
      </p>
    </div>
  </body>
</html>
"""
