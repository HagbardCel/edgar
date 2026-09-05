# Testing, quality, and proposal review

## Test the semantic promises

Use existing pytest, Hypothesis, real PostgreSQL, and a small mixture of constructed and real filing fixtures. No new testing platform is required. Test consequences visible to a researcher, not every helper's control flow.

| Invariant / failure | Test boundary | Evidence of success |
|---|---|---|
| Every supported item occurrence survives | Adapter → wire → SQL, independently inventoried XML/Inline fixture | Expected locator/occurrence multiset equals persisted multiset; not just three counts derived from one list |
| Identical occurrences do not collapse | Duplicate facts in separate elements/documents; hidden Inline occurrences | Both source rows/pins survive and appear as co-support only after qualification |
| Context/unit ID collision does not overwrite | Multi-document IXDS with conflicting identifiers | Clear extraction failure or supported occurrence resolution; never silently picks a context |
| Exact values remain exact | Large/tiny Decimals, negatives, scale, sign, INF/omitted accuracy, nil/invalid transforms | Wire, NUMERIC, export round-trip without float coercion or double scale/sign application |
| Dimensions cannot disappear | Explicit/typed/default/non-dimensional context fixtures | Filed occurrence rows/XML preserved; unsupported qualifiers block strict observation |
| XBRL network identity survives | Two base sets sharing role/arcrole but differing link/arc QName | Separate effective sets and complete arc locators; role definitions/targetRole preserved |
| Resources retain evidence | Multiple label roles/languages, ordered reference parts, shared footnote resources | Every association/resource locator retained; no continuation/footnote conflation |
| Report provenance is exact | Same payload with changed URI bindings, aliases or report inputs | Receipts differ appropriately; old publication replays against its original descriptor |
| Cross-report references are invalid | Deliberately mismatched context/unit/declaration relationships | Named DB constraint or pre-persist error rolls back the complete replacement |
| Candidate cannot publish | Candidate exact mapping with perfect label/value match | Query state `candidate_only`, no trusted value |
| Stale meaning cannot publish currently | Contract edit after proposal/acceptance | Accept fails or query marks stale; historical snapshot remains inspectable |
| Conditions cannot become implicit overrides | Overlapping issuer/report/interval predicates | Conflict or explicit atomic replacement; unknown disjointness is not accepted |
| One fact cannot silently acquire contradictory exact meaning | Concurrent proposals and corrupt/legacy conflict input | Acceptance transaction rejects; application additionally detects conflicting matches |
| Selection is not arbitrary | Permute fact insert order, IDs, labels, SQL result order | Same support set/value/state; distinct values never resolved by order |
| Nil, absent and zero differ | Three separately requested slots | Explicit nil/absent state versus valid Decimal zero |
| Consolidation is not inferred from empty dimensions alone | Other context entity, parent-only/broader disclosures, opaque qualifiers | Strict scope checks fail with evidence |
| Period identity is exact | Fiscal year vs calendar year, quarter vs YTD, date-only/aware/timezone-less values | Separate slots; original lexicals survive; no manufactured timezone |
| Time cutoffs are honored | Before/at/after acceptance and decision revisions | No future public/semantic/local information in the constrained query |
| Amendment is not whole-filing replacement | Partial amendment and later comparative | Only relevant slots change; unchanged original observations remain available |
| History is immutable and repairable | UPDATE/DELETE attempts, branching, concurrent replace, sync/accept race | Rejection/rollback; predecessors byte-equivalent; atomic new state |
| Published lineage survives change | Export, re-extract, revoke/redefine, restore DB separately | Old values/decisions still explain from snapshots/pins; new outputs reflect correction |
| Failed operations do not publish | Inject DB/serialization/fsync/rename failures | Old extraction/publication intact; incomplete temp output never listed as success |

Default tests have no live SEC calls and no required LLM. Source and financial tests must pass with LLM disabled. Security/closure tests continue to verify no ambient cache/network access; a valid filing is insufficient to test hostile or malformed resource behavior.

## Fixtures and benchmark design

Use small hand-built XML/Inline fixtures for one edge case at a time. Existing rich, IXDS, invalid-transform and document helpers are a strong base. Keep adapter-boundary fakes for focused failure paths, but ensure each important new semantic feature has at least one real Arelle contract test.

Real financial benchmark starting inventory:

| Filing set | Role in validation | Limitation |
|---|---|---|
| eBay `0001065088-23-000006`, `0001065088-24-000036` | Annual source continuity, taxonomy changes, repeat issuer periods | Two filings do not establish universal extension reuse |
| eBay `0001065088-24-000094` | Partial amendment semantics and evidence inspection | Do not assume it changes financial values without reading its contents |
| Walmart `0000104169-24-000056` | Second annual issuer, retail/fiscal-period contrast | Not broad industry coverage |
| JPMorgan `0000019617-24-000453` | Bank meaning as a negative/generalization case; quarterly aspects | Operating-company revenue is not a bank revenue contract |
| Coca-Cola `0000021344-24-000044` | Quarterly/YTD and dimensional qualification cases | Additional years needed for longitudinal claims |

The source corpus manifest lists these filings, but full acquisition snapshots are not all committed/pinned across machines today. M0 must create a verified local bundle inventory for the benchmark, not describe the current corpus as a universally reproducible packaged dataset. Keep full bundles outside Git and follow the existing explicit fixture refresh policy.

The benchmark expected-value manifest records: exact contract/hash, issuer, accession/report, period/unit/scope, rendered row/location, expected Decimal or missing reason, supporting source occurrences, reviewer and review date. Use both positive and negative cases. Do not produce expected output by running the implementation under test and blessing it.

Initial release gate is **zero false exact matches on the bounded reviewed benchmark**, not a statistical precision guarantee. Report denominator counts: requested slots, supported slots, selected values, expected missing cases, unexpected missing cases, conflicts, source concepts reviewed, and filings covered. Do not use all-fact coverage to conceal failure on economically important statement lines.

For broader reuse/AI work, separate development and held-out reports, including later years and unreviewed issuers. Track false exact positives, coverage conditional on precision, review minutes per new report/concept, and mappings invalidated by drift. No numerical precision claim is credible without sample size and review methodology.

## Accounting and longitudinal checks

Use reconciliation as a diagnostic, not as mapping authority or a mechanism to invent missing facts:

- Assets versus liabilities plus the appropriate equity/noncontrolling-interest/mezzanine scope, using compatible periods, units, entity basis, and filed accuracy.
- Operating/investing/financing cash flow plus relevant FX/other changes against the corresponding cash definition. Cash including restricted cash must not be checked against an excluding-restricted-cash target without a reconciled bridge.
- Reported gross profit versus the compatible revenue/cost basis; negative/expense conventions handled explicitly.
- Duplicate/comparative continuity across filings; changed values flag a basis/restatement review rather than imply an extraction error.
- Calculation linkbase checks through supported Arelle functionality; absence of an arc is not evidence of a missing economic component, and a weighted edge does not authorize our own derivation.

Use accuracy-aware tolerances only where a test explicitly models them. Do not weaken value comparison globally to make reconciliation pass. A successful accounting identity does not prove correct semantic equivalence: several wrong classifications can still balance.

## Practical test execution by phase

Run targeted tests for changed behavior first, then the repository's broader checks. Existing commands are:

```bash
uv run pytest -q -m 'not database and not network'
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run edgar registry validate
```

For schema/repository work, use the repository's guarded `edgar_test` database and run:

```bash
EDGAR_TEST_DATABASE_URL=postgresql+psycopg://edgar:edgar@localhost:5432/edgar_test uv run pytest -q -m 'database and not network'
make corpus-acceptance
```

The existing helper's reset operation is destructive test setup. Harden `reset_test_database` itself to validate the target name before DDL, rather than relying only on callers; include that small guard change with M1's migration tests. Never reuse it for local user data. Testcontainers is unnecessary while one guarded local PostgreSQL service and CI service suffice.

Add upgrade tests from populated `0002_registry` and later adopted revisions, downgrade tests for reversible source changes, full schema/constraint parity for source and registry, and restore tests for durable knowledge. Empty-head creation alone cannot validate a data migration. New source fields need SQL assertions after actual Arelle extraction; a wire-only round trip can preserve a field never populated by the extractor.

## Final critical review of this recommendation

| Challenge | Review outcome / revision incorporated |
|---|---|
| Too many layers? | Removed mandatory reference warehouse, accounting resolver and binding ledger; mapping application/candidates remain query records |
| Too few distinctions? | Retained source declaration vs QName, contract vs slot, reporting basis vs dimensions, public vs semantic/local time |
| Fighting XBRL? | Use native aspects and Arelle networks; add missing role/base-set/footnote fidelity rather than a second concept framework |
| Is every custom abstraction justified? | Keep only source pins, contracts, assertions, request/result and publication; no generic workflow/DAG/entity framework |
| Is the ledger overengineered? | Reuse its linear append-only revisions; add only immutable conditions, contract content and atomic correction needed for trusted output |
| Could one exact mapping still mislead? | Report-scoped extension reuse and precise contracts address declaration/context drift; selector separately checks basis/period/unit/slice |
| Does the plan reach utility soon enough? | M3 ships bounded direct annual analysis; large corpus research, codec cleanup, ontology and dimensional rewriting do not gate it |
| Is M1 too large? | Split into receipt, native evidence, integrity and inspector changes; retain existing structures and codec. Each addition supplies concrete review/lineage information |
| Does current-state replacement lose history? | Ad hoc unexported queries are not historical products; published results retain content and input receipts independently of mutable SQL IDs |
| Are we pretending to know historical state? | Require explicit historical contract pins; exact old deployments are established by exported manifests, not guessed from today's parser |
| Could we delete more? | Delete unused codecs/shims and empty entrypoint column; retain worker and documents because their evidence/security value is demonstrated |
| Is this local-project friendly? | One application, PostgreSQL and files, no required model server/scheduler/graph/cloud service |
| Which assumptions remain speculative? | Broader extension reuse, canonical member equality, typed equality, Meta Model resolution, derivations and materialization remain gated |

The main remaining economic risk is insufficient review evidence, not a missing framework. The main engineering risk is claiming source completeness from self-consistent projections without independent occurrence and provenance checks. Both receive explicit acceptance tests before the first financial release.

## Validation performed for this package

This is a documentation-only architecture task. Commands actually executed:

```bash
uv run pytest -q -m 'not database and not network' tests/contract/test_arelle_report_extraction.py tests/unit/test_source_extract_adapt.py tests/unit/registry
```

**Result:** 51 passed in 6.92s. These validate selected existing behavior; they do not validate unimplemented target behavior or establish financial mapping correctness.

Repository inspection used `git status --short`, `git diff --stat`, `git log -1 --format='%H %s'`, `rg`, and targeted file reads. The current metric count was checked with `rg -c '^  - key:' registry/metrics.yml` (39). Primary documentation was consulted for XBRL/OIM/Dimensions, Arelle, SEC APIs, FASB Meta Model, ontology/schema tools, and technology alternatives; citations appear alongside the corresponding decisions.

Document validation command:

```bash
uv run python /private/tmp/edgar_architecture_check.py
```

**Result:** eight Markdown files, 36 local links/anchors and two Mermaid code blocks; local link/anchor, balanced code-fence, and Git whitespace checks passed. The temporary checker invokes `git diff --no-index --check /dev/null <document>` for each new file. Its first invocation incorrectly treated Git's normal exit code 1 for new-file differences as a whitespace failure; the checker was corrected and rerun successfully. Mermaid blocks were inspected as text, not rendered or syntax-validated by a Mermaid engine.

No database integration tests, full corpus acceptance, live SEC acquisition, model experiment, architecture implementation, schema migration, or benchmark financial validation was performed for this package.
