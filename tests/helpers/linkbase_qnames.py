"""Standard 2003 linkbase QNames for synthetic M1A-2 constructors."""

from __future__ import annotations

from edgar.xbrl.records import ExpandedQName

XBRL_LINKBASE_NS = "http://www.xbrl.org/2003/linkbase"


def linkbase_qname(local_name: str) -> ExpandedQName:
    return ExpandedQName(namespace_uri=XBRL_LINKBASE_NS, local_name=local_name)


PRESENTATION_LINK = linkbase_qname("presentationLink")
PRESENTATION_ARC = linkbase_qname("presentationArc")
CALCULATION_LINK = linkbase_qname("calculationLink")
CALCULATION_ARC = linkbase_qname("calculationArc")
DEFINITION_LINK = linkbase_qname("definitionLink")
DEFINITION_ARC = linkbase_qname("definitionArc")
LABEL_LINK = linkbase_qname("labelLink")
LABEL_ARC = linkbase_qname("labelArc")
REFERENCE_LINK = linkbase_qname("referenceLink")
REFERENCE_ARC = linkbase_qname("referenceArc")
