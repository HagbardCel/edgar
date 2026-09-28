"""Taxonomy concept availability from captured schema artifacts."""

from __future__ import annotations

from edgar.financials.taxonomy_availability import concepts_from_taxonomy_schema_bytes

_NS = "http://fasb.org/us-gaap/2024"


def test_schema_parser_collects_target_namespace_elements() -> None:
    schema = f"""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="{_NS}"
           elementFormDefault="qualified">
  <xs:element name="Foo" type="xs:string"/>
  <xs:element name="Bar" type="xs:string"/>
</xs:schema>
""".encode()
    concepts = concepts_from_taxonomy_schema_bytes(schema)
    assert concepts == frozenset({(_NS, "Foo"), (_NS, "Bar")})
