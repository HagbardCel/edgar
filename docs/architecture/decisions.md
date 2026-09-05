# Architectural decisions and technology

**Status convention:** “Made” is the independent recommendation selected here. Adoption is M0; this document does not supersede live ADRs by itself. Each decision includes a reconsideration trigger. Deferred questions are listed separately.

## D1 — Native XBRL evidence plus a small application model: made

**Problem:** preserve meaning while supporting cross-company quantities.

**Options:** persist Arelle objects; replace source with xBRL-JSON/OIM export; maintain a relational subset of native XBRL plus application contracts; discard semantics into standardized statement rows.

**Recommendation:** retain the relational native subset, immutable artifacts, and an isolated Arelle adapter. Add only measurement contracts, assertions, query policies and publication lineage above it.

**Reasoning:** source occurrence, declared concept, context, and network are already suitable domain entities. Arelle engine objects are not a durable API. An interchange export may be excellent for consumers but is not demonstrated to retain this project's occurrence locators, Inline provenance, and unsupported/invalid evidence. The existing adapter's fixture-covered behavior is more valuable than theoretical LOC savings.

**Trade-off:** some explicit DTO and SQL code remains. Complete DTS/raw-arc reconstruction uses original artifacts and Arelle, not SQL alone.

**Reconsider when:** a maintained third-party export/adapter passes the same occurrence, value, locator, dimensional, resource and offline contract suite. Do not replace it based on one filing or a feature list.

**Delivery:** M1A preserves the existing complete base-set identity and establishes receipts/integrity. Role/arcrole tables, typed-domain enrichment and full footnote persistence are case-triggered M1B additions. Required evidence can first be supplied by a bounded offline Arelle reader and retained packet. Unassessed relevance blocks the affected case; omitted SQL storage never proves irrelevance.

## D2 — Direct conditional mapping to a measurement contract: made

**Problem:** separate source identity from comparability without multiplying decisions.

**Options:** direct source-QName→contract assertions; mandatory source→reference accounting concept→metric binding; individual fact overrides; unrestricted expression mapping.

**Recommendation:** direct concept claims with explicit report/declaration and optional aspect guards. Preserve full fact aspects on application. Reference concepts and packages supply evidence. Fact-specific exceptions are represented by an explicit narrow report/context condition, not editable normalized numbers.

**Reasoning:** a second reference target is not always available or uniquely appropriate, especially for issuer/non-GAAP measures and industry distinctions. Two reviewed edges introduce two histories and conflicting paths while the application still needs a contract. Reusing exact XBRL identity does not require adopting a taxonomy concept as the only possible economic target.

**Coverage rule:** additional reviewed reports create disjoint accepted roots; correction/revocation is not the default coverage-expansion mechanism. All existing scope fields and new conditions are conjunctive. Same-key contract versions may coexist accepted after independent review, without revocation for mere noncurrentness; same-reference and cross-key overlaps remain conservatively blocked. Each request pins one ContractRef per key. This bounded rule avoids a semantic-compatibility ontology.

**Trade-off:** the project owns concise economic definitions and reviews them. Pure concept guards cannot express every concept-plus-dimension substitution; those remain unsupported until an explicit aspect transformation is introduced.

**Reconsider when:** evidence shows many independently reused source-to-reference conclusions feeding several analytical contracts, and factoring them materially reduces reviews without hiding semantic differences. Such factoring must preserve existing decisions; it is not an excuse to force a reference target onto old claims.

**Review discipline:** answer “what does the source mean?” and “why does it fit this contract?” separately in one [review packet](mapping-and-review.md#two-review-questions-one-durable-claim). This preserves two reasoning obligations without requiring two independently maintained claims.

## D3 — Relational semantic registry, no ontology runtime: made

**Problem:** searchable knowledge, explicit relations, and history for humans and AI.

**Options:** no canonical registry; lightweight registry; canonical taxonomy; relational/property graph; RDF/OWL; LinkML schema toolchain.

**Recommendation:** contracts in YAML, history/evidence in PostgreSQL, typed JSON reports. This is a lightweight semantic registry. Optional canonical hierarchy is a later relational relation, not an inference engine.

**Reasoning:** current requirements are constrained claims with scope, evidence, revisions, and numeric selection. FKs, joins, and small graph traversals express them directly. OWL provides formal inference over classes/properties and uses open-world semantics, which do not replace this application's explicit “insufficient evidence means no trusted value” policy. [OWL primer](https://www.w3.org/TR/owl2-primer/).

LinkML can generate multiple schema/code representations and semantic exports. That is useful for a shared external schema ecosystem; here it would add another authoritative model alongside Pydantic, SQLAlchemy and Alembic. It also does not decide whether two revenue measures are equivalent. [LinkML overview](https://linkml.io/linkml/intro/overview.html), [generators](https://linkml.io/linkml/generators/index.html).

**Trade-off:** no generic inference, ontology editor, or federated SPARQL. Structured exports can later map to RDF without changing the ledger.

**Reconsider when:** external collaborators require a shared semantic interchange vocabulary or actual cross-domain inference queries that cannot be maintained as simple relations. A graph visualization alone is not that trigger.

## D4 — Ordinary SQL plus typed Python; no transformation platform yet: made

**Problem:** apply mappings and select observations deterministically with useful explanations.

**Options:** SQL views/functions; Python; dbt/SQLMesh; a bespoke dependency/versioning engine.

**Recommendation:** SQL for bounded joins/filtering/counts; typed Python for a single policy implementation, explanation and export. Views are installed through Alembic when needed. One CLI command invokes the sequence; no scheduler.

**Reasoning:** the proposed first pipeline is a bounded query, not a warehouse DAG. SQLMesh provides model plans, audits, environments, backfills and state; those solve real scale/dependency problems, but do not remove the need to design financial semantics. [SQLMesh overview](https://sqlmesh.readthedocs.io/en/stable/concepts/overview/).

**Trade-off:** the application must manage a consistent read snapshot and atomic export. It must not grow its own DAG scheduler or dependency invalidation framework.

**Reconsider when:** profiling shows recurring materialized dependency/backfill management across many models, multiple environments, or datasets too large to recompute acceptably. Compare SQLMesh/dbt then using measured operational needs.

## D5 — Keep replaceable source state; retain publications and knowledge: made

**Problem:** parser fixes must not destroy evidence or invalidate historical outputs.

**Options:** append every parse forever; event-source all database rows; keep only mutable current values; replace current extraction and snapshot published inputs/results.

**Recommendation:** the last option. Exact bundle receipts close input provenance; immutable publications preserve what was actually delivered. Mapping decisions and contract content are durable. No extraction-attempt ownership of semantic rows.

**Reasoning:** researchers need explainable results and reproducible selected studies, not every failed parser run as an alternative ontology. Per-publication snapshots preserve historical interpretations at much lower conceptual cost.

**Trade-off:** ad hoc queries are not guaranteed to reproduce after parser upgrades unless exported. Old publication explanation survives; executable replay also needs retained software/dependencies. State that limit instead of claiming perfect perpetual reproducibility.

**Reconsider when:** a real consumer requires interactive simultaneous parser-version comparisons at scale or exact historical API responses that were never exported.

## D6 — Retain Git contracts and database decisions: made

**Problem:** assign one authority to authored meaning and expensive review history.

**Options:** all Git; all PostgreSQL; current split with content snapshots.

**Recommendation:** current split, plus historical contract snapshots and backup/restore verification. Do not rebuild the existing decision ledger just to align storage ownership aesthetically.

**Reasoning:** small definitions benefit from code review and DB-free validation; transactional review/correction and affected-fact joins fit PostgreSQL. Old hashes without content are insufficient portable evidence. A mirrored snapshot is a copy of authority, not another definition editor.

**Identity refinement:** `metric-v1` and `metric-v2` explicitly identify the definition-hash contract; preserve the original digest bytes and label only verified original-schema legacy records. New ContractRefs include scheme/digest/content. This is a fixed pair of supported hash contracts, not a plugin or serialization migration framework.

**Trade-off:** YAML/mirror synchronization remains. Implement common contract locking and take one loaded YAML snapshot per operation; never accept against a drifting mirror.

**Reconsider when:** multiple concurrent curators need an interactive contract authoring service. At that point move authoring authority explicitly, with an auditable cutover; never enable both editors.

## D7 — Preserve dimensions; defer canonical dimensional rewriting: made

**Problem:** concept representation can encode economic detail either in a concept or a dimension.

**Options:** ignore dimensions; clone metrics by each slice; generic aspect algebra now; preserve source aspects and add specific reviewed transformations later.

**Recommendation:** the last option. Initial consolidated selection supports a narrow dimension-free profile; unsupported slices remain inspectable and unresolved.

**Reasoning:** native axes/members are already a good evidence model. Cross-issuer member equality and typed value normalization need evidence. A conditional mapping that consumes no dimensions is simple; consuming/remapping a dimension changes observation identity and must be explicit.

FASB's Meta Model includes relationships addressing concept-dimensional equivalence, and its entry point is separate from the base GAAP schema. It is useful evidence, not proof that every filing DTS already contains it or that an arbitrary arc can be treated as simple synonymy. [2026 technical guide](https://xbrl.fasb.org/resources/annualrelease/2026/GAAP_Financial_Reporting_Taxonomy_and_Data_Quality_Committee_Rules_Taxonomy_Technical_Guide.pdf), [relationship descriptions](https://xbrl.fasb.org/resources/metamodelrelationships.pdf).

**Trade-off:** lower initial segment/product coverage. Native slices remain available without pretending to have harmonized them.

**Reconsider when:** a benchmarked query fails specifically because a proven aspect substitution is missing. Implement that substitution with residual-aspect and conflict tests before generalizing.

## D8 — Explicit publication policies and multiple knowledge clocks: made

**Problem:** as-filed, latest comparative, restated, and historically knowable values differ.

**Options:** latest row per issuer/metric/year; single `known_at`; full bitemporal versioning on every table; request-level public/semantic/local cutoffs plus immutable outputs.

**Recommendation:** request-level clocks and policies described in [target architecture](target-architecture.md#time-amendments-and-restatements). No universal source-fact supersession column. Filing-slot coverage must distinguish assessed absence from unknown; temporal scans cannot silently skip unreviewed filings. Byte integrity, known defects and semantic currentness of exports are independent.

**Reasoning:** a 10-K/A may amend only part of a filing. A later comparative can change a particular observation without replacing every earlier fact. Economic time and semantic decision time answer different questions.

**Trade-off:** clients must choose a mode. Strict historical reconstruction is unavailable for missing acceptance timestamps or unrecoverable historic contract content.

**Reconsider when:** a user needs systematic assertion-level restatement classifications or financial-statement set coherence across versions. Add evidence-backed basis/statement-set models; do not infer them from accession order.

## D9 — One pinned exact-review profile: made

**Problem:** consistent minimum evidence assessment across curators without another review system.

**Options:** free-form rationale alone; a fixed typed checklist with versioned content; a configurable review/workflow framework.

**Recommendation:** one Git-authored profile, retained with per-check outcomes in accepted evidence. Required positive support cannot be replaced by assessed absence; conditional evidence needs a reasoned relevance conclusion. Case requirements can strengthen, not weaken, the baseline. Profile identity is independent of economic contract identity. Selector-facing conclusions are typed and bound to occurrences/report/receipt; standalone reviewed packets reuse the evidence format when a reusable mapping does not own report qualification. Negative slot coverage in M4 uses the same packet discipline.

**Trade-off:** this improves process consistency, not proof of accounting correctness. Sampling and availability limits stay explicit; no checklist can certify unseen future reports. M0 verifies that the initial profile can be assessed with M1A and any specifically required M1B reader.

**Reconsider when:** actual review cases require incompatible procedures. Evidence-only reaffirmation of unchanged accepted claims is deferred until a changed profile must apply retroactively; define that transition before changing query eligibility. Routine new report coverage does not require it.

## Technology choices and avoided custom code

| Recommendation | Problem solved / custom code avoided | Cost | Credible alternative and why it does not win now |
|---|---|---|---|
| Python + uv lock | Typed business policies and repeatable environment | Lockfile/runtime maintenance | JVM/.NET can work, but would discard tested Python/Arelle integration with no identified benefit |
| Pinned Arelle | XBRL loading, resolution, transformations, networks, validation | Adapter API and release regression testing | Custom XML engine duplicates standards; high-level normalized financial APIs omit needed evidence |
| PostgreSQL + SQLAlchemy Core + psycopg | Exact NUMERIC, transactions, constraints, JSON evidence and joins | One local database process | SQLite lowers setup but changes numeric/concurrency behavior; DuckDB is attractive for read-only exports, not concurrent semantic review authority |
| Alembic | Ordered reviewed schema changes | Migration files intentionally retained | Ad hoc CREATE TABLE or current metadata as history is unsafe; generation is a draft, not automatic approval |
| Pydantic at wire/CLI/evidence boundaries | Validation and serialization; replaces repetitive manual codecs | Strict Decimal/QName/XML serializers still need tests | LinkML/codegen stack adds an authoring model; untyped dicts lose validation. [Pydantic serialization](https://docs.pydantic.dev/latest/concepts/serialization/) |
| Existing httpx client + filelock/CAS | Controlled network/retry/atomic acquisition | Specialized security and provenance logic remains | EdgarTools offers broad SEC access/analysis, but has not demonstrated parity for this bundle/IXDS/closure contract. Use as an optional comparison, not a mandatory replacement project. [EdgarTools documentation](https://edgartools.readthedocs.io/en/latest/) |
| lxml + existing document parser | DOM parsing, source locations, inspectable disclosure text | Heuristic fixtures remain necessary | An HTML-to-text service loses deterministic structure; full text intelligence is not needed |
| Typer, plain JSON/Markdown | Human and agent workflow with one interface | Some CLI formatting | Web application/API service adds deployment/auth/state before a user need |
| pytest + Hypothesis + guarded PostgreSQL tests | Semantic contracts and a few algebraic invariants | Local DB setup for integration | Testcontainers is optional when CI isolation needs it; no separate testing platform now |
| JSONL/CSV first | Portable Decimal-safe results and evidence | Larger than columnar files | Parquet plus DuckDB/Polars becomes useful for larger analysis; select decimal precision/scale explicitly when introduced |
| Functions and SQL checks | Orchestration, data quality, and result lineage | Explicit small checks | Airflow/Dagster, Great Expectations/Pandera, OpenLineage/catalog services add operational/schema layers without a current requirement |

The SEC company-facts APIs aggregate selected standard-taxonomy, entity-wide facts; frames apply a calendar-oriented latest-filing selection. They are useful comparators and discovery aids, not a replacement for extension/dimensional filing evidence or this project's declared selection policy. [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

## Decisions deliberately deferred

| ID / question | Reason for deferral | Evidence needed | Decision trigger / safe interim |
|---|---|---|---|
| F1 Wider extension reuse | Declaration equality alone may miss changing disclosure scope | Multi-year approved cases and observed semantic drift | Review queue becomes costly; default to listed reports |
| F2 Reference package warehouse | Filing DTS already supplies much review evidence | Missing evidence examples and repeated package queries | Repeated package inspection justifies index; use pinned attachments first |
| F3 Canonical axes/members | No universal issuer segment identity | Two issuers/years with defensible member correspondence | Requested comparable segment dataset; retain native slices |
| F4 Aspect substitution engine | Requires consumption/residual-aspect rules | Real concept-versus-dimensional equivalent example, counterexamples, official guidance | Required metric blocked by representation; fail closed meanwhile |
| F5 Rounded duplicate resolution | Identical-value support is sufficient for initial subset | Accuracy-only conflicts blocking reviewed outputs | Add Arelle-based tested policy; return accuracy review now |
| F6 Derived metrics and quarter subtraction | Accounting basis and availability of inputs matter | Named formula, compatible-period fixtures, unit/accuracy contract | Explicit research request; direct facts only now |
| F7 Typed dimension equality beyond preserved XML | XML canonicalization is not universal typed equality | Actual typed-domain schemas and comparison requirements | Canonical slice query needs equality; no speculative merging |
| F8 Formal restatement/statement-set model | An amendment flag does not classify affected values | Cases separating restatement, reclassification, and partial amendments | Consumer needs classifications/coherent revised statement sets; expose filed assertions now |
| F9 Materialization/SQLMesh | No measured bottleneck or large DAG | Query timings, corpus size, rebuild cost | Repeated operational pain; live bounded queries now |
| F10 Ontology/LinkML/RDF | No external semantic interoperability contract | Named consumer and required inference/interchange | Concrete integration, not semantic terminology alone |
| F11 Acquisition replacement | Parity unknown, current code is tested | Full bundle/security/closure comparison on representative cases | Maintenance burden exceeds demonstrated replacement cost; keep now |
| F12 Richer relational evidence | Not every resource needs a dedicated table before analysis | Named blocked review or repeated costly retrieval | Activate only needed M1B capability; pinned packets first, unknown relevance blocks publication |
| F13 Standard-taxonomy release continuity | Different releases remain distinct QNames; repeat work is unmeasured | Reviewed release comparisons and measured transition effort | Consider reviewed equivalence sets if they reduce work without hiding definition changes |
| F14 Factored accounting meaning | Recurrence alone does not establish multiple independent consumers | Several real uses sharing the same source-meaning conclusion and duplicated review effort | Compare factoring cost with direct claims; no mandatory intermediary now |
| F15 Separate DB writer role | Trusted-local setup already has one owner connection | Shared/untrusted writers or deployment requirements | Keep M2 immutability triggers; add restricted roles/grants before extending the trust boundary |
| F16 Publication automation | A bounded manifest scan serves the first exports | Measured scan cost or repeated missed/manual correction work | Keep M3 explicit status/notices; add indexing/propagation only with a scoped operational need |

F1, F13 and F14 address issuer recurrence, standard release transitions and multiple semantic consumers respectively. Measure them separately in the [M3 review report](testing-and-quality.md#review-effort-and-taxonomy-continuity-measurement). None automatically authorizes inference or delays M4.

These are not TODOs that an implementation agent should fill with invented requirements. Each new decision needs a bounded evidence report and an explicit updated phase scope.
