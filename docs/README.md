# Documentation

The [target architecture package](architecture/README.md) is the **adopted** forward plan ([ADR 0012](adr/0012-adopt-bounded-financial-architecture.md)). **Current implementation phase: M0 — complete; next: M1A.** Phase 2B/2C remain live production behavior until M1A/M2 change them. Consolidating documents does not authorize later-phase implementation ahead of its gate.

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
- **Phase 2C:** `registry/metrics.yml` authors current contracts; `registry.canonical_metric` mirrors them; `registry.mapping_assertion` records append-only decisions (`0002_registry`). Propose/accept require YAML/mirror agreement and definition-hash checks; rejected is terminal; affected facts are queried live. The inspected YAML has 39 metrics. Constructed-fixture coverage includes validate → sync → propose → accept → export; this is not financial observation selection.
- **Adopted target:** [M0–M4 migration](architecture/migration-plan.md) via [ADR 0012](adr/0012-adopt-bounded-financial-architecture.md). **M0 is complete** (adoption, inventory/restore proof, bounded benchmark, review profile, static validation). No applicability/selection or canonical financial observation publication is implemented. Current Phase 2A/2B/2C invariants remain in force until M1A/M2 explicitly change them. **Next phase: M1A.**

## Plans and evidence

- [Target and migration entry point](architecture/README.md): selected and deferred decisions, source model, mapping/review, selection and testing.
- [Feedback assessment](architecture/feedback-assessment.md): accepted feedback and disagreements.
- [Consolidation record](architecture/documentation-consolidation.md): useful requirements retained from seven removed plans, reasons for removal and exact Git recovery instructions.
- [August code assessment](reviews/2026-08-22-project-assessment.md) and [lineage review](reviews/2026-08-31-xbrl-lineage-review.md): retained diagnostic evidence, not current plans or newly verified results.
- [Offline closure spike](spikes/0001-arelle-offline-closure.md): historical integration evidence; production does not import spike code.

The root [planning changelog](../PLANNING-CHANGELOG.md) records earlier changes. Superseded plans can be recovered from Git; there is no duplicate archive of competing target designs in the working tree.
