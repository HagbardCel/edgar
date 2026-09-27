# J — Implementation notes, not a new design

**Status:** independent reply. Architecture review stays **closed**. No
blocking defect remains.

I agree with the three leftover items. They belong in the P4
implementation notes, not in another architecture pass.

| Item | Decision |
|---|---|
| Wrong historical gold | **Adopt as a P4 note.** Correct the label in one PR and merge it. A later PR may change the selector. An ordinary code change cannot rewrite the baseline it is judged against. |
| `<base-sha>` in CI | **Adopt as a P4 note.** The workflow must fetch the PR base commit. A shallow checkout does not make `git show <base-sha>:registry/gold/...` work. |
| Wording | **Adopt.** P1.3 says decision-scope exclusion, not “industry exclude.” P4 says gold CI has two views: historical assertion regression, and current value precision. |

Next work is P0, then the P1 walking skeleton, then the P2 spike.
