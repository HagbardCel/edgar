# P2 spike sample

This directory is the frozen six-filing baseline from `fixtures/corpus.toml`.
It is a format-and-tooling sample. It is not a 500–1,000 filing census and it
is not a probability sample of the market.

`p2-accessions.txt` is one canonical dashed accession per line. `edgar filings
extract --accessions-file` reads that file and rejects blank lines, comments,
malformed accessions, and duplicates.

`p2-sample.csv` holds metadata joined by the quality report on accession.
Industry buckets come from this file. Fiscal year and taxonomy release in the
quality report are computed from the filing (required-context fiscal year, else
`source.filing` period metadata; US-GAAP declaration namespaces). They are not
taken from a selected metric. Empty SIC and taxonomy-era note cells are
intentional.

Whether these filings have been retrieved is runtime state under
`EDGAR_DATA_ROOT`. A live retrieve must not add accessions to these files.
Extra local filings stay uncommitted. The 500–1,000 stratified list, the
semantic audit, and the storage and taxonomy ADRs are follow-up work after
those measurements exist.

The name census in a quality report counts distinct accessions per expanded
Clark QName of facts whose context has no `source.context_dimension` row. A
concept that appears only on a dimensional context is absent. A concept that
appears both ways is counted once. A separate `name_reuse_aggregate` groups by
semantic family, namespace release, and local name. That rollup is not source
identity.

`edgar filings companyfacts --accessions-file p2-accessions.txt` is the
explicit cache population path. `edgar build` only reads that cache.
