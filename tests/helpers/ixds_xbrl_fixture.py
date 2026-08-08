"""IXDS dual-member Inline XBRL fixture bytes for semantic acceptance tests."""

from __future__ import annotations

from edgar.xbrl.uri import normalize_uri

SCHEMA_URI = normalize_uri("https://example.com/test.xsd")
INLINE_A_URI = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000003/a.htm")
INLINE_B_URI = normalize_uri("https://www.sec.gov/Archives/edgar/data/1/0000000001000003/b.htm")

IXDS_SCHEMA = b"""<?xml version="1.0"?>
<schema xmlns="http://www.w3.org/2001/XMLSchema"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        targetNamespace="http://example.com/test"
        elementFormDefault="qualified">
  <import namespace="http://www.xbrl.org/2003/instance"
          schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>
  <element name="Assets" id="test_Assets" type="xbrli:stringItemType"
           substitutionGroup="xbrli:item" nillable="true"
           xbrli:periodType="instant"/>
</schema>
"""

INLINE_A = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:link="http://www.xbrl.org/2003/linkbase"
      xmlns:xlink="http://www.w3.org/1999/xlink"
      xmlns:t="http://example.com/test">
  <head><title>a</title></head>
  <body>
    <div>
      <ix:header>
        <ix:references>
          <link:schemaRef xlink:type="simple" xlink:href="https://example.com/test.xsd"/>
        </ix:references>
        <ix:resources>
          <xbrli:context id="c1">
            <xbrli:entity>
              <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
          </xbrli:context>
        </ix:resources>
      </ix:header>
      <p><ix:nonNumeric name="t:Assets" contextRef="c1" id="fa">1</ix:nonNumeric></p>
    </div>
  </body>
</html>
"""

INLINE_B = b"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:t="http://example.com/test">
  <head><title>b</title></head>
  <body>
    <div>
      <p><ix:nonNumeric name="t:Assets" contextRef="c1" id="fb">2</ix:nonNumeric></p>
    </div>
  </body>
</html>
"""
