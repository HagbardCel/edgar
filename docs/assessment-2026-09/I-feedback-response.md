# I — Response to the baseline and P6 wording bugs

**Status:** independent reply. Architecture review stays **closed**.
Implementation notes after this file are in [J](J-feedback-response.md).

I agree with all three contract issues and with both wording fixes. I also
rename the flag now, because it does not exist in code yet and the old
name no longer describes the check.

| Item | Decision |
|---|---|
| `--baseline-ref HEAD` | **Adopt.** The example is `--baseline-ref <base-sha>`. CI passes the PR base commit. `HEAD` on the PR branch includes the new gold and is not a baseline. |
| Baseline assertions | **Adopt.** Cohort membership **and** expected values/statuses are read from `--baseline-ref`. Current output is compared to those baseline labels. Editing an old expected value in the PR cannot make the regression pass. |
| P6 `unsupported` decision | **Adopt.** There is no such decision status. A metric with no justified exact mapping stays unresolved (`missing` / `unmapped_candidate`) until a decision, a scope policy, or an explicit derivation exists. |
| `broader_only` sentence | **Adopt.** Complete it: no exact candidate is present. |
| JPM “industry exclude” | **Adopt.** P1 is a CIK exclusion on the decision. SIC industry exclusion is P6. |
| Flag name | **Adopt.** `--require-no-gold-regressions`. It checks historical assertions, not a numeric precision floor. |

Next evidence is P0 implementation, then P1 and the P2 spike.
