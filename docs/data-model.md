# Phase 1 data model

**Status:** Authoritative conceptual persistence model for Phase 1 (post–Slice 0).

SQL table names and physical uniqueness constraints may change during implementation. **The distinctions in this document must survive.** Physical schema and migrations begin with later PRs; this document freezes meaning, not Alembic DDL.

Related:

- Architecture: [`architecture.md`](architecture.md)
- Lean XBRL projection decision: [ADR 0008](adr/0008-lean-xbrl-semantic-projection.md)
- Effective networks: [ADR 0004](adr/0004-preserve-xbrl-semantic-networks.md)
- Offline replay / URI bindings: [ADR 0007](adr/0007-manifest-only-replay-uri-bindings.md)
- Immutable raw layer / `payload_hash`: [ADR 0002](adr/0002-immutable-raw-layer.md)
- Amendment relationships: [ADR 0005](adr/0005-amendment-restatement-semantics.md)

Both offline branches of a FilingBundle appear below: Arelle semantic projection and document parsing.

---

## 1. Catalog identity

```text
issuer
  cik                # durable identity only

filing
  issuer
  accession_number
  form_type
  base_form_type
  amendment status
  filed_date
  accepted_at
  report_period_end
  issuer name/SIC/etc. where captured for that filing/snapshot
```

Then:

```text
filing
  └── filing_bundle
```

### `filing_relationship`

When discovery evidence supports it, record an explicit directed filing-to-filing relationship ([ADR 0005](adr/0005-amendment-restatement-semantics.md)):

```text
filing_relationship
  source_filing
  relationship_type = amends
  target_filing
  provenance / discovery evidence
```

Example: `10-K/A --amends--> 10-K`. This does **not** assert filing-wide supersession. Both filings remain independently queryable; no raw fact, section, or document from the original is deleted because an amendment exists. Point-in-time `known_at` / `superseded_at` observation semantics remain deferred. Physical table shape is not frozen here—`filing_relationship` is the conceptual home (not a premature `amends_filing_id` column).

CIKs are zero-padded ten-digit strings. Accession numbers use canonical dashed form. Tickers are never issuer primary keys.

Distinguish filing date, SEC acceptance timestamp, and report-period end; never substitute one for another.

**Point-in-time rule:** Mutable issuer attributes (legal name, SIC, FYE, etc.) must either be snapshot-/validity-dated or treated as convenience metadata—**never** silently used as historical filing-time truth via a mutable “latest company profile” on `issuer`.

---

## 2. FilingBundle and content identity

```text
Immutable replay state
  filing
    └── filing_bundle
           ├── xbrl_report_input / replay_entrypoint  (one or more)
           │         └── entrypoint document(s) ──► bundle_uri_binding
           ├── bundle_artifact ──► content_object
           └── bundle_uri_binding ──► bundle_artifact

Append-only operational history (adjacent; not replay membership)
  artifact_acquisition_observation  ──► (references artifact / bundle context)
```

### `content_object`

- SHA-256
- byte size
- CAS location (`objects/sha256/{aa}/{sha256}`)
- immutable bytes

Same verified bytes may back multiple artifacts. SHA equality never creates URI ownership.

### `filing_bundle`

An immutable replay snapshot comprising:

- filing / accession
- acquisition policy / version
- payload
- identified replay entrypoints / report inputs
- authoritative URI bindings

Bundle-level publication metadata may exist, but it does **not** substitute for per-artifact retrieval observations (below). One filing may have multiple immutable acquisition snapshots.

### `xbrl_report_input` / replay entrypoint

Identifies the **complete Arelle loading input** for one XBRL report. It may consist of:

- **one** URI binding (ordinary XBRL instance), or
- a **deterministically identified collection** of URI bindings sufficient to reproduce the Arelle report input (Inline XBRL Document Set / IXDS)

Whether physical ordering belongs to identity is deferred. Production must **not** assume that one XBRL report is represented by one source document URI. The common case remains a single document.

Phase 1 requires the **primary SEC IXDS/report**. Additional independently processed XBRL report types may be explicitly deferred—without baking in a false one-document assumption.

### `payload_hash`

Identifies the deterministic **payload snapshot/inventory** under the applicable payload-hash contract ([ADR 0002](adr/0002-immutable-raw-layer.md)). It excludes the authoritative replay contract (report inputs / URI bindings) and volatile operational metadata such as retrieval timestamps. Exact production hash construction is deferred.

`payload_hash` alone—or filing + policy + `payload_hash`—must **not** be assumed to provide complete FilingBundle identity. Bundles with identical payload snapshot/inventory but different authoritative URI mappings remain distinguishable. Exact bundle equality/reuse and physical uniqueness constraints are deferred to implementation. **Do not introduce another permanent production `bundle_hash` here.**

### `bundle_artifact`

- bundle membership
- logical path
- kind / content type
- content object

### `artifact_acquisition_observation`

Operational provenance for how bytes were obtained (distinct from replay identity):

```text
artifact_acquisition_observation
  bundle_artifact          # conceptual reference for published bundles; FK not frozen
  source/retrieval URI
  retrieved_at / observed_at
  relevant HTTP metadata
  acquisition attempt (if useful)
```

Rules:

- Retrieval / observation times stay distinct from filing, acceptance, and projection times.
- Observations are **operational** and **must not participate in `payload_hash` or immutable FilingBundle identity**.
- `artifact_acquisition_observation` is adjacent operational provenance referencing an artifact/bundle context; it is **not itself immutable FilingBundle membership or replay state**. Appending an observation does not mutate the replay snapshot.
- Once recorded, an acquisition observation is immutable; corrections or later observations are appended as new observations rather than rewriting prior evidence.
- Repeated acquisition/observation of the same CAS-backed artifact can append observations without duplicating the immutable bundle.
- Non-replay artifacts need not have a `bundle_uri_binding`; acquisition provenance still applies.
- An acquisition observation does **not by itself** establish an authoritative replay URI binding. Replay bindings remain explicit domain relationships, and SHA equality never creates one. Observations often contribute evidence for a binding, but the two notions are not identical.
- Do not freeze a physical foreign key to `bundle_artifact` in this PR—an implementation may retain observations from acquisition attempts that never reached bundle publication.

### `bundle_uri_binding`

Canonical replay URI → bundle artifact (plus binding/alias provenance as needed). This is the production domain relationship required by ADR 0007, **not** the Slice-0 `uri-bindings-v2` wire format.

### Provenance preference

Semantic and document rows prefer:

```text
source_bundle_uri_binding_id
source_locator  (locator_scheme + locator_value)
```

rather than sprinkling separate URI, path, and artifact fields through every projected table. Locators must be deterministic from immutable source content and must **not** be Arelle in-memory object identifiers.

---

## 3. Projection attempts vs materializations

Replace any conflated “semantic run” that mixed interpretation identity with execution metadata.

### Component-level cardinality

```text
(optional later) orchestration/batch run
       │
       ├── projection attempt A ──┐
       ├── projection attempt B ──┼──► semantic_projection P
       └── projection attempt C ──┘     filing_bundle
                                        xbrl_report_input
                                        extractor/projection version
                                        Arelle version
                                        semantic configuration fingerprint
                                        semantic status (e.g. complete / incomplete)
                                              │
                                              ├── concept declarations, labels, references
                                              ├── relationships, contexts, units, facts

failed projection attempt D ──► (no projection)
```

The zero-or-one cardinality applies to a **component-level projection attempt for one report input** (or one document-parse target), not to a higher-level orchestration or batch run.

- A component-level attempt may produce or revalidate **zero or one** logical projection.
- A logical projection may be associated with **multiple** such attempts.
- A projection **must not** contain a single owning `processing_run_id` / attempt id.
- Batch / orchestration run grouping is deferred.

Exact rerun of the same bundle + **report input** + parser / Arelle / config **reuses or revalidates the same `semantic_projection`** and may record another attempt. A parser or config change produces a **new** projection that can coexist with the old one. Independently loadable XBRL reports within one bundle remain distinguishable via `xbrl_report_input` in projection identity.

Projected XBRL rows belong to a **`semantic_projection`**, not to a processing attempt.

### Status (illustrative, not frozen enums)

- Operational status on the attempt (e.g. running / completed / failed) — crashes, timeouts, runtime failures.
- Semantic status on `semantic_projection` (e.g. complete / incomplete) — semantic completeness / cleanliness.

If a semantic projection is materialized in the presence of an unrecognized Arelle diagnostic, it **cannot** be marked complete / clean. A diagnostic or load failure that prevents coherent projection materialization may instead leave **no** projection.

### `quality_issue`

Must scope whether the issue is operational, semantic projection, or document projection—so a disk / database failure is not an XBRL semantic defect and an Arelle diagnostic is not merely a run log.

This XBRL decision is locked by [ADR 0008](adr/0008-lean-xbrl-semantic-projection.md) independently of [ADR 0006](adr/0006-regenerable-parser-outputs-vs-curated-overlays.md) (still Proposed).

### Document side (parallel identity)

```text
document_parse_target
    bundle_artifact / filing_document
    # a defined set later only if genuinely needed

document_projection
    filing_bundle
    document_parse_target
    document-parser version
    parser configuration fingerprint
```

**Document projection identity includes its parse target; bundle + parser version alone is insufficient.** Exact rerun of the same bundle + document parse target + parser / config reuses the same logical `document_projection`. Many component-level attempts may associate with one document projection; no owning attempt id. PR #7 may find `filing_document_id` sufficient as the parse-target key—this document only freezes the distinction.

---

## 4. Lean XBRL entities

### Model-wide QName invariant

QName-valued semantic fields (concept identity, data type, substitution group, unit measures, Inline XBRL `format`, dimension / member values, `usedOn`, etc.) are represented using **namespace URI + local name**, or an equivalent prefix-independent representation. Source lexical prefixes may be retained for provenance but **never** define semantic identity.

### `concept_identity`

Exact expanded QName (`namespace_uri` + `local_name`). Permits exact joins where the QName is unchanged. **Not** an economic-equivalence or canonical-metric identifier; cross-namespace / taxonomy equivalence belongs to later mapping.

### `concept_declaration`

Projection-specific effective declaration (type, period type, balance, abstract, nillable, substitution group, source URI binding). Uniqueness roughly `(semantic_projection_id, concept_identity_id)`. Arelle remains authoritative for which declaration is effective in that DTS.

### `concept_label` / `concept_reference`

Separate conceptual entities. Both are **projection-scoped and source-provenanced**. Phase 1 preserves **supported** concept-label and concept-reference relationship occurrences, including:

- `resource_role_uri` (standard / terse / verbose label role, reference role, etc.)
- language / structured reference parts
- `link_role_uri` (ELR)
- `arcrole_uri` (concept-label / concept-reference / …)
- source provenance

Distinguish these three role concepts; do not collapse them to “role”:

- `link_role_uri` — ELR
- `arcrole_uri` — concept-label / concept-reference / …
- `resource_role_uri` — standard / terse / verbose label role, reference role, etc.

Encountering a resource relationship class the projection does not support must be **explicit** and make semantic completeness fail rather than silently drop (aligns with ADR 0007 deferral of generic 2008 element-label / element-reference). Phase 1 is not “every generic XBRL resource relationship Arelle can expose.”

### `role_declaration` / `arcrole_declaration`

Require at least:

```text
role_declaration
  role_uri, definition, used_on
  source binding + locator

arcrole_declaration
  arcrole_uri, definition, used_on, cycles_allowed
  source binding + locator
```

URI alone is **not** declaration identity (XBRL permits more than one declaration of a given arcrole URI across a DTS). An umbrella table plus discriminator is an implementation choice. `cycles_allowed` applies to arcrole declarations only.

### `xbrl_context`

At least:

- `source_context_id`
- source binding + locator
- entity **scheme** + identifier
- period
- dimensions via child rows

**No** canonical `dimensions_json`.

Period kinds:

```text
period_kind:
  instant
  duration
  forever
```

Unsupported / future period semantics must not be silently coerced.

### `xbrl_context_dimension`

One row per **filed / reported** explicit or typed dimension occurrence:

```text
dimension_concept_declaration_id
context_element             # segment | scenario
member_kind                 # explicit | typed
explicit: member_concept_declaration_id
typed:    typed_member_xml, typed_member_hash
```

`typed_member_hash` is an indexing / integrity aid, not an identity key unless a later canonicalization contract is adopted.

Dimension and explicit-member references are projection-scoped **declarations**. Segment-versus-scenario placement is part of context identity and must not be silently removed.

**Reported vs default:** records filed context dimension occurrences **only**. An implicit default member must **not** be materialized as though it appeared in the source context. Dimension-default semantics remain in the effective definition network; any later effective-dimension view is derived.

**Typed member XML:** `typed_member_xml` means a **namespace-complete, self-contained** representation of the typed member value, or an equivalent lossless representation. It must not depend on namespace declarations that existed only on ancestors in the original source document. Do not freeze a canonicalization algorithm here.

### Segment / scenario policy

Non-dimensional `<segment>` / `<scenario>` content is either preserved as canonical / raw semantic content **or** declared unsupported with incomplete projection status—never silently dropped.

### `xbrl_unit`

```text
source_unit_id
source binding + locator
numerator measures
denominator measures
```

Measure values are **expanded QNames** (namespace URI + local name), not prefix-dependent lexical strings. A compact canonical representation may additionally be stored.

### `xbrl_fact`

One row per **source occurrence** (source binding + deterministic locator). Forbid uniqueness on `(concept, context, unit, value)`.

Explicit semantic FKs:

```text
concept_declaration_id
context_id
unit_id                   # nullable where not applicable
```

Fact-value fidelity (Arelle is the semantic authority; the adapter projects Arelle semantics rather than independently reimplementing Inline XBRL processing):

```text
source artifact + locator      mandatory (authoritative filed representation)
retained lexical value         where adapter exposes/derives it (raw_lexical_value)
resolved typed value           where Arelle produces it
value/validation status        enough to distinguish valid / nil / invalid / unresolved
```

`raw_lexical_value` is the adapter's retained lexical / source-level fact value, preserving the distinction from Arelle's resolved typed value. Its exact extraction semantics must be documented and versioned by the projection implementation. Immutable source bytes + locator remain authoritative and are **not** substituted by the lexical column. Numeric resolved values retain exact decimal semantics (Python `Decimal` / PostgreSQL `NUMERIC`).

Also preserve interpretation-relevant filed attributes where applicable: transformation `format` QName, `xml:lang`, scale / sign, decimals / precision, nil, Inline XBRL continuation / escape semantics.

Phase 1's SEC projection models **item facts**. Unsupported fact structures (for example tuples) must fail semantic completeness rather than disappear silently.

### `xbrl_relationship`

Arelle **effective** presentation, calculation, and definition relationships. Network identity fields are required ([ADR 0004](adr/0004-preserve-xbrl-semantic-networks.md)):

```text
semantic_projection
network_type              # presentation | calculation | definition (stored or derived)
link_role_uri             # required; cannot omit
arcrole_uri               # required; cannot omit
source_concept_declaration_id
target_concept_declaration_id
order
weight
preferred_label_role
target_role_uri
closed
usable
context_element
source_bundle_uri_binding
source_locator
```

`network_type` may be stored or derived; **link role and arcrole cannot be omitted**. Endpoints are concept declarations, not bare global identities. No permanent `xlink_locator` / `xlink_arc` / generic graph tables. Issuer-extension relationships survive as filed.

---

## 5. Minimal document model

Full block / section schema design is deferred to PR #7. Phase 1 retains these conceptual distinctions:

- `document_parse_target` — which document(s) within the bundle are being parsed (typically a `bundle_artifact` / `filing_document`)
- `document_projection` — identity includes `filing_bundle` + `document_parse_target` + document-parser version + config fingerprint
- `filing_document` — occurrence is **bundle-scoped** or resolves through a `bundle_artifact`; must never depend solely on `filing_id` as “the document for this filing”
- `document_block` — document order, parent / child relationships, source locator, projection version
- `filing_section` — section boundaries, extraction method / confidence

Preserve document order and source locators. Missing sections become quality issues, not inferred content.

---

## 6. Acceptance invariants

A Phase 1 data-model change is complete only when all of the following are unambiguous from this document (and ADR 0008) alone:

1. Can two otherwise identical fact occurrences coexist without information loss?
2. Can explicit and typed dimensions be queried without reparsing XML?
3. Can a QName remain stable while its DTS-specific declaration / provenance differs?
4. Can all **supported** Arelle-available concept-label / concept-reference occurrences be recovered (unsupported classes fail completeness explicitly)?
5. Can effective presentation, calculation, and definition trees be reconstructed—**including link-role and arcrole identity**?
6. Can every semantic record be traced to a semantic projection and immutable source artifact / URI binding?
7. Can issuer-extension concepts and relationships survive untouched?
8. Can an unknown Arelle diagnostic prevent clean / successful status without forcing filing discard (and may leave no projection if materialization is incoherent)?
9. Can everything be regenerated from an immutable bundle with networking disabled and no ambient cache / state?
10. Have Slice-0 hashes, manifests, XLink mechanics, and Arelle object graphs been avoided as permanent production APIs?
11. **Bundle / resource identity:** Can two bundles with identical payload bytes but different authoritative URI mappings remain distinguishable, while SHA equality never creates URI ownership?
12. **Idempotent interpretation:** Can an exact rerun reuse the same logical `semantic_projection`; can a changed parser / config coexist as a new projection; does a projection have no single owning attempt id; is zero-or-one cardinality component-level only?
13. **QName ≠ economic equivalence:** Is it impossible to mistake exact QName identity for cross-taxonomy economic equivalence?
14. **Context completeness:** Does every context distinction either survive the projection or cause explicit incomplete / unsupported status—**including segment / scenario placement**; reported dimensions only (no fabricated default members)?
15. **Fact value fidelity:** Does every retained fact preserve authoritative source + locator, retained lexical value where the adapter exposes / derives it, and, **where Arelle produces one**, its exact resolved typed value; are valid / nil / invalid / unresolved distinguishable?
16. **QName stability:** Can semantically identical QNames with different source prefixes resolve to the same QName identity while source representation can be preserved for provenance?
17. **XBRL report input:** Can one semantic projection be loaded from a multi-document SEC IXDS without pretending that one URI is the complete entrypoint, and can independently loadable XBRL reports within one bundle remain distinguishable?
18. **Document projection identity:** Can multiple independently parsed documents in one FilingBundle produce distinct document projections while exact reruns of the same parse target reuse the same logical projection?
19. **Amendment relationship:** When discovery evidence supports it, can a directed `amends` relationship be recorded without implying filing-wide supersession or deleting original filing evidence?
20. **Acquisition provenance:** Can per-artifact retrieval/observation metadata (including `retrieved_at`) be retained without entering `payload_hash` or FilingBundle replay identity, including for artifacts without URI bindings—and without treating an observation as an automatic replay binding?
