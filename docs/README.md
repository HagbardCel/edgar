# Documentation

The [target architecture package](architecture/README.md) records the historical
M0–M4 recommendation ([ADR 0012](adr/0012-adopt-bounded-financial-architecture.md)).
**Current implementation sequence: P1 complete. P2 software is implemented
(batch extract, companyfacts cache and oracle, quality report). The P2 measurement exit
gate is not met** ([ADR 0014](adr/0014-adopt-lean-mapping-sequence.md),
[assessment plan](assessment-2026-09/plan/)). Phase 2B/2C remain live production
behavior until P3 consolidation changes them. For P1/P2, `registry/metrics.yml`,
`registry/decisions/`, and `registry/gold/` are the durable governed inputs.
`var/builds/` is regenerable. `registry.canonical_metric` is not a P1/P2 runtime
authority.

## What is implemented

| Topic | Current contract |
|---|---|
| Application boundaries and live flow | [Architecture](architecture.md) |
| Source and registry persistence | [Data model](data-model.md) |
| Phase 2C metrics and mapping decisions | [Normalization](normalization.md) and [ADR 0010](adr/0010-curated-semantic-registry.md) |
| Source extraction cutover | [ADR 0011](adr/0011-source-extraction.md) |
| Local commands, migrations and tests | [Development](development.md) |
| Artifact/corpus acceptance and refresh | [Fixture policy](fixture-policy.md) |
| Failure and provenance posture | [Data quality](data-quality.md) |
| Financial distinctions and research cautions | [Metric semantics](metric-semantics.md); domain reference, not another implementation plan |
| Repository work rules | [AGENTS.md](../AGENTS.md) |

Current production truth is the code, tests and implemented contracts above. The target package identifies intended changes and existing gaps; proposed features must not be described as live behavior. ADRs retain their historical status until explicitly superseded.

## Completed milestones and current boundary

- **Phase 1:** immutable acquisition, offline Arelle integration, document structure and fixture work established the foundation. Its projection/attempt data model and old projection commands were removed in Phase 2B. Its old completion checklist is not a guarantee that today's SQL retains every XBRL resource.
- **Phase 2A:** the Git JSON semantic registry closed with 20 historical v1 contracts and three reviewed real-corpus rules. `semantic-registry/` is now an archive, never production authority. Do not infer current ledger contents from those rules.
- **Phase 2B:** FilingBundle → `filings catalog|extract` → native `ReportExtraction` → `source.*` is the sole live source path. `0001_source_v2` replaced the old baseline. No dual writes or projection-attempt tables. Phase-1 databases cannot upgrade through the deleted migration lineage; see development guidance, with explicit authorization before resetting user data.
- **Phase 2C:** `registry/metrics.yml` authors current contracts; `registry.canonical_metric` mirrors them; `registry.mapping_assertion` records append-only decisions (`0002_registry`). Propose/accept require YAML/mirror agreement and definition-hash checks; rejected is terminal; affected facts are queried live. The inspected YAML has 41 metrics (39 original plus two P1 walking-skeleton keys). Constructed-fixture coverage includes validate → sync → propose → accept → export; this is not financial observation selection.
- **Lean sequence (forward):** [P0–P6 plan](assessment-2026-09/plan/) via [ADR 0014](adr/0014-adopt-lean-mapping-sequence.md). **P0 and P1 are complete.** P2 software (parallel extract, companyfacts cache and oracle, filing-level quality report) is implemented on the six-filing baseline. The 500–1,000 filing census, independent audit labels, and storage/taxonomy ADRs are not done, so the P2 exit gate is not met and P3 has not started. Historical [M0–M4 migration](architecture/migration-plan.md) ([ADR 0012](adr/0012-adopt-bounded-financial-architecture.md)) remains reference only for superseded items. ADR 0014 supersedes the earlier SQLMesh / durable PostgreSQL semantic-layer plan where they conflict.

## Plans and evidence

- [September 2026 assessment implementation plan](assessment-2026-09/plan/) (P0–P6; governing forward work per ADR 0014).
- [Target and migration entry point](architecture/README.md): historical M0–M4 package; selected and deferred decisions.
- [Feedback assessment](architecture/feedback-assessment.md): accepted feedback and disagreements.
- [Consolidation record](architecture/documentation-consolidation.md): useful requirements retained from seven removed plans, reasons for removal and exact Git recovery instructions.
- [August code assessment](reviews/2026-08-22-project-assessment.md) and [lineage review](reviews/2026-08-31-xbrl-lineage-review.md): retained diagnostic evidence, not current plans or newly verified results.
- [Offline closure spike](spikes/0001-arelle-offline-closure.md): historical integration evidence; production does not import spike code.

The root [planning changelog](../PLANNING-CHANGELOG.md) records earlier changes. Superseded plans can be recovered from Git; there is no duplicate archive of competing target designs in the working tree.
