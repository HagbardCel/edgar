# H — Response to the last contract inconsistencies

**Status:** independent reply. Architecture review stays **closed**.
Later pins are in [I](I-feedback-response.md).

I agree with all three inconsistencies and with both implementation notes.

| Item | Decision |
|---|---|
| Stale rejected hash in `05` §9 | **Adopt.** Accepted stale hash fails CI/build. Rejected stale hash is inactive history, reported as review-needed, and does not suppress the queue. |
| `broader_only` | **Adopt.** `status=missing`, `reason=broader_only`. Not a sixth status. Form guard stays `unsupported` / `wrong_form`. |
| Scope exclusion | **Adopt.** Look at the **set** of exact accepted decisions. All of them scope-excluded → `unsupported` / `decision_scope`. At least one applicable exact decision and no candidate → `missing`. |
| Gold IDs | **Adopt.** Every slot id resolves to exactly one assertion across gold files. |
| Baseline | **Adopt.** `--check-gold --require-precision-floor --baseline-ref <sha>`. CI passes the PR base SHA. |

No further architecture pass. Next evidence is P0/P1 implementation and the P2 spike.
