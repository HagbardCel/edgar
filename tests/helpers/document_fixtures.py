"""In-memory HTML fixtures for document projection contract tests."""

from __future__ import annotations

_IX = b'xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"'

RICH_10K_HTML = (
    b"""<!DOCTYPE html>
<html><body>
<div>Table of Contents</div>
<div><a href="#item1">Item 1. Business</a> 3</div>
<div><a href="#item1a">Item 1A. Risk Factors</a> 8</div>
<div><a href="#item1b">Item 1B. Unresolved Staff Comments</a> 12</div>
<div><a href="#item1c">Item 1C. Cybersecurity</a> 14</div>
<div><a href="#item7">Item 7. MD&amp;A</a> 40</div>
<div><a href="#item7a">Item 7A. Market Risk</a> 55</div>
<div><a href="#item8">Item 8. Financial Statements</a> 60</div>
<div><a href="#signatures">SIGNATURES</a> 82</div>

<div style="display:none">Item 1. Hidden decoy Business</div>
<div hidden>Item 7. Hidden MD&amp;A</div>
<div><ix:hidden """
    + _IX
    + b""">Item 1A. Hidden risk</ix:hidden></div>

<h2 id="item1">Item 1. Business</h2>
<p>We sell widgets. Revenue&nbsp;increased <b>12%</b> year over year.</p>
<div>
  Intro before list.
  <ul>
    <li>Apple</li>
    <li>Banana</li>
    <li>Cherry</li>
  </ul>
  Trailing after list.
</div>

<h2 id="item1a">Item 1A. Risk Factors</h2>
<p>Risks include competition.</p>

<h2 id="item1b">Item 1B. Unresolved Staff Comments</h2>
<p>None.</p>

<h2 id="item1c">Item 1C. Cybersecurity</h2>
<p>We maintain cybersecurity programs.</p>

<h2>Item 2. Properties</h2>
<p>Headquarters in California.</p>

<h2>Item 3. Legal Proceedings</h2>
<p>No material proceedings.</p>

<h2>Item 4. Mine Safety Disclosures</h2>
<p>Not applicable.</p>

<h2>Item 5. Market for Registrant</h2>
<p>NASDAQ.</p>

<h2>Item 6. Reserved</h2>
<p>Reserved.</p>

<h2 id="item7">Item 7. Management's Discussion and Analysis</h2>
<p>MD&amp;A content here.</p>
<table>
  <tr><td>Revenue</td><td>100</td></tr>
  <tr><td>Expense</td><td>40</td></tr>
</table>
<p class="footnote">See note regarding revenue recognition.</p>

<h2 id="item7a">Item 7A. Quantitative and Qualitative Disclosures About Market Risk</h2>
<p>Market risk content.</p>

<h2 id="item8">Item 8. Financial Statements and Supplementary Data</h2>
<p>Financial statement content with <ix:nonfraction """
    + _IX
    + b""">1000</ix:nonfraction> dollars.</p>

<h2>Item 9. Changes in and Disagreements</h2>
<p>None.</p>

<h2 id="signatures">SIGNATURES</h2>
<p>Pursuant to the requirements of the Securities Exchange Act.</p>
<p>/s/ Jane CEO</p>
</body></html>
"""
)

RICH_10Q_HTML = b"""<!DOCTYPE html>
<html><body>
<div>Table of Contents</div>
<div><a href="#p1i1">Item 1. Financial Statements</a></div>
<div><a href="#p2i1">Item 1. Legal Proceedings</a></div>

<h1>Part I. Financial Information</h1>
<h2 id="p1i1">Item 1. Financial Statements</h2>
<p>Condensed financial statements.</p>
<h2>Item 2. Management's Discussion and Analysis</h2>
<p>Quarterly MD&amp;A.</p>
<h2>Item 3. Quantitative and Qualitative Disclosures About Market Risk</h2>
<p>Market risk.</p>
<h2>Item 4. Controls and Procedures</h2>
<p>Controls.</p>

<h1>Part II. Other Information</h1>
<h2 id="p2i1">Item 1. Legal Proceedings</h2>
<p>Legal matters.</p>
<h2>Item 1A. Risk Factors</h2>
<p>Updated risks.</p>
<h2>Item 2. Unregistered Sales</h2>
<p>None.</p>
<h2>SIGNATURES</h2>
<p>Pursuant to the requirements.</p>
</body></html>
"""

LAYOUT_TABLE_ITEMS_HTML = b"""<!DOCTYPE html>
<html><body>
<table>
  <tr><td><b>ITEM 7.</b> Management's Discussion</td></tr>
  <tr><td>MD&amp;A body text.</td></tr>
  <tr><td><b>ITEM 7A.</b> Market Risk</td></tr>
  <tr><td>Market risk body.</td></tr>
</table>
<h2>SIGNATURES</h2>
<p>Sign here.</p>
</body></html>
"""

MIXED_CONTENT_HTML = b"""<!DOCTYPE html>
<html><body>
<div>
  Introductory text.
  <p>Paragraph text.</p>
  Trailing text.
</div>
</body></html>
"""

SAME_ORDINAL_COLLAPSE_HTML = b"""<!DOCTYPE html>
<html><body>
<div>ITEM 1. Business ... ITEM 1A. Risk Factors ...</div>
<h2>SIGNATURES</h2>
</body></html>
"""

PARTIAL_10KA_HTML = b"""<!DOCTYPE html>
<html><body>
<h2>Item 1A. Risk Factors</h2>
<p>Amended risk factors only.</p>
<h2>SIGNATURES</h2>
<p>Pursuant to the requirements.</p>
</body></html>
"""

AMBIGUOUS_END_HTML = b"""<!DOCTYPE html>
<html><body>
<h2>Item 1C. Cybersecurity</h2>
<p>Cyber content.</p>
<h2>Item 2. Properties</h2>
<p>First properties.</p>
<div><b>Item 2. Properties</b></div>
<p>Second properties heading region.</p>
<h2>Item 7. MD&amp;A</h2>
<p>MD&amp;A.</p>
<h2>SIGNATURES</h2>
</body></html>
"""

HEADER_IX_SAME_DOC_HTML = b"""<!DOCTYPE html>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>
<header>VISIBLE</header>
<ix:header>HIDDEN</ix:header>
<p>Body text.</p>
</body></html>
"""

BR_WBR_HTML = b"""<!DOCTYPE html>
<html><body>
<p>Revenue<br>increased</p>
<p>long<wbr>identifier</p>
</body></html>
"""

NESTED_BLOCK_IN_INLINE_HTML = b"""<!DOCTYPE html>
<html><body>
<div>
  A
  <span>X <p>B</p> Y</span>
  C
</div>
</body></html>
"""

NESTED_LIST_HTML = b"""<!DOCTYPE html>
<html><body>
<ul>
  <li>Parent item
    <ul><li>Nested item</li></ul>
  </li>
</ul>
</body></html>
"""

PROSE_CROSSREF_10Q_HTML = b"""<!DOCTYPE html>
<html><body>
<h1>PART I</h1>
<h2>Item 1. Financial Statements</h2>
<p>See Part II, Item 1A for additional risk factors.</p>
<h2>Item 2. Management's Discussion and Analysis</h2>
<p>MD&amp;A body.</p>
<h2>Item 3. Market Risk</h2>
<p>Risk.</p>
<h2>Item 4. Controls and Procedures</h2>
<p>Controls.</p>
<h1>PART II</h1>
<h2>Item 1. Legal Proceedings</h2>
<p>Legal.</p>
<h2>Item 1A. Risk Factors</h2>
<p>Risks.</p>
<h2>SIGNATURES</h2>
</body></html>
"""

COMPACT_TOC_BODY_HTML = b"""<!DOCTYPE html>
<html><body>
<div>Table of Contents</div>
<div><a href="#item1">Item 1. Business</a> 3</div>
<div><a href="#item1a">Item 1A. Risk Factors</a> 8</div>
<h2 id="item1">Item 1. Business</h2>
<p>Business body immediately after TOC.</p>
<h2 id="item1a">Item 1A. Risk Factors</h2>
<p>Risk body.</p>
<h2>SIGNATURES</h2>
</body></html>
"""

INTERVENING_COLLAPSE_HTML = b"""<!DOCTYPE html>
<html><body>
<h2>Item 1C. Cybersecurity</h2>
<p>Cyber content.</p>
<div>ITEM 2. Properties ... ITEM 3. Legal Proceedings ...</div>
<h2>Item 7. Management's Discussion</h2>
<p>MD&amp;A.</p>
<h2>SIGNATURES</h2>
</body></html>
"""

MISSING_INTERMEDIATE_HTML = b"""<!DOCTYPE html>
<html><body>
<h2>Item 1. Business</h2>
<p>Business.</p>
<h2>Item 1A. Risk Factors</h2>
<p>Risks.</p>
<h2>Item 1C. Cybersecurity</h2>
<p>Cyber. No Item 1B.</p>
<h2>Item 7. MD&amp;A</h2>
<p>MD&amp;A.</p>
<h2>Item 8. Financial Statements</h2>
<p>Statements.</p>
<h2>SIGNATURES</h2>
</body></html>
"""

NO_TERMINAL_END_HTML = b"""<!DOCTYPE html>
<html><body>
<h2>Item 8. Financial Statements</h2>
<p>Statements without later boundary or signatures.</p>
</body></html>
"""

ORDINARY_MISSING_START_HTML = b"""<!DOCTYPE html>
<html><body>
<h2>Item 7. Management's Discussion</h2>
<p>MD&amp;A only.</p>
<h2>Item 8. Financial Statements</h2>
<p>Statements.</p>
<h2>SIGNATURES</h2>
</body></html>
"""

LAYOUT_TABLE_SIGNATURES_HTML = b"""<!DOCTYPE html>
<html><body>
<table>
  <tr><td><b>ITEM 7.</b> Management's Discussion</td></tr>
  <tr><td>MD&amp;A body text.</td></tr>
  <tr><td><b>ITEM 8.</b> Financial Statements</td></tr>
  <tr><td>Statements body.</td></tr>
  <tr><td><b>SIGNATURES</b></td></tr>
</table>
</body></html>
"""

PART_I_ONLY_RESET_10Q_HTML = b"""<!DOCTYPE html>
<html><body>
<h1>PART I</h1>
<h2>Item 1. Financial Statements</h2>
<p>FS.</p>
<h2>Item 2. Management's Discussion</h2>
<p>MD&amp;A.</p>
<h2>Item 3. Market Risk</h2>
<p>Risk.</p>
<h2>Item 4. Controls and Procedures</h2>
<p>Controls.</p>
<h2>Item 1. Legal Proceedings</h2>
<p>Should not be Part I.</p>
<h2>SIGNATURES</h2>
</body></html>
"""

PLAIN_SHORT_ITEM_HTML = b"""<!DOCTYPE html>
<html><body>
<div>Item 7. MD&amp;A</div>
<p>Discussion body.</p>
<div>Item 8. Financial Statements</div>
<p>Statements.</p>
<h2>SIGNATURES</h2>
</body></html>
"""

WEAK_CANDIDATE_HTML = b"""<!DOCTYPE html>
<html><body>
<div><a href="#x">Item 7. Early page 3</a></div>
<p>filler</p><p>filler</p><p>filler</p><p>filler</p><p>filler</p>
<p>filler</p><p>filler</p><p>filler</p><p>filler</p><p>filler</p>
<h2 id="x">Item 7. Management's Discussion</h2>
<p>Real MD&amp;A.</p>
<h2>Item 8. Financial Statements</h2>
<p>Statements.</p>
<h2>SIGNATURES</h2>
</body></html>
"""

ADVERSARIAL_GLOBAL_HTML = b"""<!DOCTYPE html>
<html><body>
<h2>Item 1. Business</h2>
<p>Early business body.</p>
<h2 id="risk">Item 1A. Risk Factors</h2>
<p>Early strong risks.</p>
<h2 id="late1">Item 1. Business</h2>
<p>Late higher-scoring decoy business.</p>
<div>Item 1A. Risk Factors</div>
<p>Late weaker risks.</p>
<h2>SIGNATURES</h2>
</body></html>
"""
