# G — Response to the last implementation-contract bugs

**Status:** independent reply. Architecture review stays **closed**.
Later cleanup is in [H](H-feedback-response.md).

I agree with all six items. They are contradictions introduced by earlier
pins, not a new design.

| Item | Decision |
|---|---|
| Issuer expansion | **Adopt.** `family: issuer` matches `origin == issuer` and the filing CIK, not `semantic_family == "issuer"` (that is never true). Same local name across year-specific issuer namespaces is the required test. |
| `slot_eligible` | **Adopt.** Eligibility is requested metric and allowed form only. Decision `exclude_*` affects `decision_applicable`, not the publication denominator. `n_no_applicable_decision` covers era gaps and scope exclusions with no alternative. |
| Gold cohorts | **Adopt.** Regression is the **union** of every cohort already on the base branch. P1.3 creates `registry/gold/cohorts/m0.yml`. P2.8 adds `p2-audit.yml`. |
| Stale rejected hash | **Adopt.** P1.8 matches P1.2: accepted mismatch fails the build; stale rejection is inactive history and does not. |
| Non-value gold | **Adopt.** `--require-precision-floor` requires zero regressions on **all** prior assertions (`value`, `missing`, `unsupported`, `conflict`). `value_precision` by tier stays numeric-only. |
| `05` §8 | **Adopt.** Same vocabulary as P2: `publication_rate`, `selector_yield`, typed non-publication. R&D `missing` stays eligible. |

After this, further plan review should not outrank implementing P0/P1 and running P2.
