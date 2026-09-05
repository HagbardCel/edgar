# Current-state assessment

This assessment distinguishes the checked implementation from historical plans. Baseline commit and worktree limitations are in [README](README.md). Relative code links resolve within this repository. No production behavior was changed during assessment.

## What works today

The executable path is:

```text
filings retrieve --accession
  → submissions lookup + attachment reconciliation + controlled retrieval
  → online Arelle DTS closure through parent fetcher
  → immutable filesystem FilingBundle
filings catalog / filings extract --bundle-dir
  → issuer / filing / document catalog
  → offline isolated Arelle worker → ReportExtraction
  → HTML blocks / sections
  → transactional replacement of source extraction rows
registry validate / sync
  → YAML validation / database mirror
mappings propose / accept / reject / show / list / export
  → immutable decision revisions + live affected-fact enumeration
```

Discovery functionality exists inside acquisition (`sec/submissions.py`, `sec/accession.py`); there is no separate discovery command in the inspected CLI. `metrics list/show` inspect definitions, not observed financial values. There is no general concept evidence command, no observation selector, and no canonical financial-value publication path. `MappingMethod` vocabulary names possible model/structural candidates; that does not mean a candidate generator exists.

The CLI is [cli.py](../src/edgar/cli.py); orchestration is in [ingestion](../src/edgar/ingestion/source_extract.py). Catalog commits separately before parsing, so a catalogued filing can have no successful extraction. A failed extraction retains the previous successful snapshot. This distinction must remain visible in missing-data explanations.

## Current persistent entities

All source table definitions are in [source_schema.py](../src/edgar/db/source_schema.py); registry definitions are in [registry_schema.py](../src/edgar/db/registry_schema.py). There are 17 source tables and two registry tables. “Source” here denotes extracted evidence, not immutable SQL rows.

| Entity | Real-world thing and grain | Current identity | Class / target disposition |
|---|---|---|---|
| Filesystem object | Exact artifact bytes | SHA-256 | Immutable evidence; KEEP |
| FilingBundle | Acquisition/replay contract with inventory, inputs, URI bindings | Accession + opaque directory; validated descriptor equality | Immutable evidence; KEEP |
| Acquisition attempt files | Operational retrieval observations | Attempt identifier | Infrastructure provenance; KEEP outside interpretation identity |
| `source.issuer` | SEC registrant | Ten-digit CIK | Catalog; KEEP; not every context entity is this registrant |
| `source.filing` | Submission | Accession, bigint local PK | Catalog; KEEP; acceptance time may be absent |
| `source.document` | Catalogued artifact within a filing, including external taxonomy artifacts | Filing + relative path | Catalog mirror of bundle inventory; KEEP |
| `source.concept` | Exact expanded QName | Namespace + local name; deterministic UUIDv5 | Shared identity; KEEP, no economic equivalence implied |
| `source.xbrl_report` | Current extraction of one report input | Filing + `report_key` | Regenerable state; MODIFY to pin extraction receipt |
| `source.concept_declaration` | Effective declaration encountered in a report's DTS | Report + concept | Extracted taxonomy evidence; KEEP and enrich |
| `source.concept_label` | Effective concept-to-label association occurrence | Report + source order | Evidence; KEEP language, ELR, resource role, arc/resource locators |
| `source.concept_reference` | Effective concept-to-reference association occurrence | Report + source order | Evidence; KEEP ordered structured reference parts |
| `source.context` | A context in one loaded report | Report + source context ID | Evidence; KEEP lexical periods and entity scheme/identifier |
| `source.context_dimension` | Filed explicit/typed dimension occurrence | Local row ID under context | Evidence; KEEP multiplicity and segment/scenario location |
| `source.unit` | Filed unit | Report + source unit ID | Evidence; KEEP |
| `source.unit_measure` | Numerator/denominator measure occurrence | Unit + side + ordinal | Evidence; KEEP expanded QName and multiplicity |
| `source.fact` | One item-fact occurrence | Report + source order; local bigint | Evidence; KEEP, never deduplicate at storage |
| `source.relationship` | Effective concept-network edge | Report + source order | Evidence; MODIFY network identity completeness |
| `source.extraction_issue` | Diagnostic from the current extraction | Local ID with filing/report/document scope | Regenerable diagnosis; KEEP |
| `source.document_block` | Located structural text block | Document + ordinal | Regenerable evidence; KEEP |
| `source.filing_section` | Parser's section-boundary assertion | Document + section key | Regenerable interpretation; KEEP method/confidence |
| `registry.canonical_metric` | Current contract copied from YAML | Metric key | Regenerable mirror; KEEP, add historical content separately |
| `registry.mapping_assertion` | Immutable revision of a semantic claim | Integer revision + unique predecessor | Curated knowledge; KEEP and extend carefully |

`report_key` hashes report input URIs/target, not bundle bytes, bindings, parser version, or extraction time. It identifies a report input, not a frozen interpretation. [report_key.py](../src/edgar/domain/report_key.py) makes this explicit.

## Domain knowledge worth preserving

- **Acquisition/replay:** reconciliation of submissions metadata, index tables, and complete-submission DOCUMENT records; bounded access; per-hop network controls; closure capture; URI aliases and canonical bases. A simple download helper does not replace this contract.
- **IXDS:** multi-document report inputs and synthetic Arelle document identity handling. [report_input.py](../src/edgar/ingestion/report_input.py), [extract.py](../src/edgar/xbrl/extract.py), and [IXDS fixtures](../tests/helpers/ixds_xbrl_fixture.py) encode hard-won constraints.
- **Occurrence and values:** invalid transformations remain explicit facts; exact Decimal values; filed `decimals`/`precision` including INF; scale/sign/format; continuations; nil states; deterministic element locators.
- **Dimensions and networks:** typed XML, explicit members, no fabricated defaults, effective relationship sets, target roles, closed/usable/context-element attributes, separate label and reference roles.
- **Atomic replacement:** filing lock, no shared-concept garbage collection, rollback on insertion failure. [source.py](../src/edgar/db/source.py) and [persistence tests](../tests/integration/test_source_persist.py) are valuable contracts.
- **Review semantics:** definition-hash pinning, rejected terminal revisions, no branching, stale accepted decisions visible, exact-map conflicts checked under a source-concept lock. These are small mechanisms for expensive human knowledge.
- **Documents:** deterministic DOM order, tables and locators, section disambiguation. Located disclosure text helps reviewers decide what an extension means; removing it would trade existing useful evidence for later reimplementation.

## Gaps that matter before financial publication

### Source completeness is a declared subset, not all XBRL semantics

The live extractor calls concept/context/unit/fact/network extraction. It does **not** call `_role_declarations` or `_arcrole_declarations`; `ReportExtraction` has no corresponding fields. Keeping unused helpers is not equivalent to retaining role definitions in SQL. Neither the native declaration DTO nor table carries typed-domain references or resolved datatype derivation information.

The extractor enumerates exact `(arcrole, linkrole, link QName, arc QName)` base sets, but only the first two identities survive into `source.relationship`. The full base-set key should survive rather than relying on all relevant networks using standard link/arc element names.

Fact-footnote arcs are explicitly excluded and counted in issues. Generic labels/references and unsupported arcroles can produce nonfatal omissions. Tuples, fractions, and non-dimensional context content can block extraction. These policies are visible in [config.py](../src/edgar/xbrl/config.py) and [extract.py](../src/edgar/xbrl/extract.py). Raw artifacts retain the evidence, but the SQL surface is not a complete DTS archive. The target should label supported capabilities honestly and materialize the small missing pieces that review needs.

### Portable lineage is incomplete at the extraction boundary

`source.document` pins artifact hashes and the report pins its input, but SQL does not record the exact bundle descriptor/URI-binding snapshot used for extraction. A report can be traced to bytes; reproducing its exact load contract requires finding the correct bundle. `entry_document_id` is always inserted as `None`; it is not an IXDS provenance solution.

Fact/report IDs change on replacement. Mapping evidence correctly avoids durable fact IDs, but future published outputs need the same discipline. Add portable pins and publication snapshots before persisting analytical foreign keys to replaceable rows.

### Count equality is necessary but not independent evidence of completeness

`_build_facts` checks one output per ordered item; persistence checks row counts. However `_source_build.py` sets `arelle_item_fact_count = len(facts)`. The repeated equality check cannot detect an upstream iterator missing a class of item occurrences. Keep these checks, but add independently inventoried fixture occurrence counts/locators and Arelle collection comparisons with documented IXDS/tuple scope.

### The registry is curated, but some contracts are economically elastic

There are **39** entries in [metrics.yml](../registry/metrics.yml). Examples needing review before use:

- `cash_and_cash_equivalents` allows restricted cash when included in the issuer's line, while also excluding a broader combined total. A common key should not change its boundary based on presentation.
- `intangible_assets_net` can include goodwill when combined; identifiable intangibles excluding goodwill is a different contract.
- `accounts_receivable` says “typically” net; gross and net require a definite choice.
- `depreciation_and_amortization` lists depreciation and amortization separately under includes; a component is not the combined total.
- Revenue's industry/accounting boundary and capex's asset coverage need explicit decisions.

Tighten the initial subset, retain inactive/unreviewed definitions visibly, and create distinct contracts where economic boundaries differ. Do not approve all 39 simply because they pass structural YAML validation.

### Conditions, evidence, history, and inspection need strengthening

Today the scope is global/issuer plus an inclusive interval on **filing report-period end**, not fact period or knowledge time. It cannot express a particular report/declaration boundary or dimensional semantic condition. Exact mappings conflict across overlapping scopes even if a hypothetical new condition could distinguish them.

`MappingEvidenceItem.data` is an arbitrary dictionary. Nonempty data proves neither valid source pins nor adequate evidence; the fact-ID key check is only top-level. The same `method` field describes generation and review on different revisions. Preserve the chain, but present those as different activities in evidence reports.

Old definition hashes are retained in assertions; historical definition content is not a DB entity. It may be recoverable from Git, but an audit export should contain the exact reviewed contract. `show` computes all affected facts before slicing to 25; use SQL counts and bounded pages for an agent-friendly inspector.

There is no live `amends` table/field despite the earlier amendment ADR's intent and the corpus manifest's explicit eBay pair. Do not describe an amendment lineage feature as implemented.

## Accidental complexity and justified complexity

The live worker internally translates `records.py` → `_source_build.py` → `source_records.py` → handwritten `source_wire.py`. Two record vocabularies and repetitive codecs are reasonable consolidation targets. Keep boundary validation and explicit persistence fields; avoid replacing them with a generic reflection framework. Some unused role helpers should be connected to the target model, not reflexively deleted as dead code.

Old projection-attempt ownership is already gone. SQLMesh cannot earn its cost by “removing” machinery no longer present. Frozen migrations duplicate current metadata intentionally: they preserve historical DDL. Add parity checks and use reviewed Alembic generation for future changes; do not import live schema into old revisions.

The subprocess, immutable bundle, URI resolver, and fail-closed diagnostics remain justified by untrusted filing resources, Arelle global state, and reproducible offline loading. A single well-behaved filing in offline mode would not establish that these controls are redundant.

## Historical hypotheses reconsidered

| Historical proposal | Assessment |
|---|---|
| v2: SQLMesh owns all derived layers | Premature for a bounded query and export; ordinary SQL/Python suffices |
| v2.1: extensions must map to reference concepts before metric bindings | Adds two semantic assertions and a taxonomy warehouse without eliminating comparability judgment; reject as mandatory |
| v2.1: canonical roles should become thin names | Loses the explicit economic contract researchers need; retain precise measurement definitions |
| v2.1: large semantic spike precedes useful data | Start with the existing corpus and a small manually checked subset; expand on observed failures |
| August review: remove worker after quiescent offline trial | Evidence bar too weak; retain controls, simplify serialization |
| August review: delete document parsing | Existing located disclosure text is useful for semantic review; retain and bound it |
| Older metric plan: narrower rules automatically take precedence | Specificity is not proof of correctness; explicit corrections or conflicts are safer |
| Older metric plan: many semantic relation/status types | Separate relationship, review status, method, scope, and derivation; do not encode all in one enum |

Historical documents considered: [v2](../docs/plans/edgar_v2_target_architecture_and_plan.md), [v2.1](../docs/plans/edgar_v2_1_xbrl_native_target_architecture_and_plan.md), [implementation proposal](../docs/plans/xbrl-native-implementation-plan.md), [August assessment](../docs/reviews/2026-08-22-project-assessment.md), [lineage review](../docs/reviews/2026-08-31-xbrl-lineage-review.md), and [refactoring plan](../docs/reviews/2026-08-31-refactoring-plan.md). These untracked historical documents were present before this work and have not been edited.
