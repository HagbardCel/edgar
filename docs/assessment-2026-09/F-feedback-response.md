# F — Response to the implementation-contract notes

**Status:** independent reply. Architecture review stays **closed**. This
file records the last contract pins only.

I agree with all five items and with the two semantic notes. None of them
reopens Git decisions, the selector, P0→P1→P2, storage, or the semantic
model.

| Item | Decision |
|---|---|
| Standard vs issuer | **Adopt.** Two axes: `semantic_family` (`us-gaap` / `dei` / `srt` / `other`) and `origin` (`standard` / `issuer`). After the three families, any `xbrl.sec.gov`, `fasb.org`, or `xbrl.us` host is standard (CYD, ECD, FFD, country, …). Filer hosts are `issuer`. P3 packages replace the host rule with package provenance. |
| Coverage denominator | **Adopt.** No economic-applicability layer. `slot_eligible` = requested metric ∧ supported form ∧ not excluded by explicit decision scope. `publication_rate` = values / eligible. `selector_yield` stays. R&D `missing` can be correct; it is not “not applicable.” |
| Observation field name | **Adopt.** Context keeps `period_kind` (`duration` / `instant` / `forever`). Observations use `period_role` (`annual` / `YTD` / `quarter` / `quarter_ytd` / `instant`). |
| Gold baseline | **Adopt.** Cohort files under `registry/gold/cohorts/`. `--require-precision-floor` compares `regression_precision` to the prior cohort. No numeric publication floor until a P2/P6 ADR sets one. |
| Derived Q4 slot | **Adopt.** Same CIK, metric, unit, and scope. Dates: start = day after Q3 YTD end, end = FY end. |
| One relation per concept | **Document, do not change.** Exclusion is enough for publication. A later need is a scoped exception on the same file, not scope algebra. |
| “Issuer override” | **Reword** to issuer exclusion/exception. The schema does not have a positive override. |

Next evidence is P0/P1 implementation and P2 measurements.
