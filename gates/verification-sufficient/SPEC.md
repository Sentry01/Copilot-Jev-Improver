# Gate: verification-sufficient

**Name:** Verification Sufficient Gate  
**Slug:** `verification-sufficient`  
**Rank / source:** #6 in `cool-use-cases.md`  
**Primary lever:** quality

## Purpose

Before claiming work is complete, ask whether the actual verification evidence supports the claim. This prevents confident completion claims when tests were not run, the changed path was not exercised, or the check proves the wrong thing.

## When to call

Immediately before a final completion claim, merge-readiness statement, or any statement that implies the requested outcome is verified.

## State schema (agent-ops only)

| Field | Type | Notes |
| --- | --- | --- |
| `claimed_outcome` | string | What we are about to claim is done |
| `changes_made` | string | Files and behaviours touched |
| `verification_performed` | string | Commands actually run, and their results |
| `test_coverage` | string | Whether changed paths are exercised |
| `reversibility` | string | `trivial` / `moderate` / `hard` to undo |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `outcome_verified` | `noul` | Belief the evidence actually supports the claim |
| `verification_gap` | `choice` | `none`, `not_executed`, `partial_coverage`, `wrong_check`, `unverifiable` |
| `confidence_in_claim` | `score` | Ordered: `speculative`, `plausible`, `likely`, `demonstrated`, `proven` |

No free-text questions.

## Thresholds

- **Allow the completion claim** if `outcome_verified.noul >= 0.7` and `confidence_in_claim >= demonstrated`
- Else **keep working** or state plainly what remains unverified

## Fail mode

**Fail-closed** on API error or missing answers → `proceed=false` / action `block_completion_claim`. If Jev is unreachable, do not emit a confident completion claim.

## Expected efficiency win

Quality rework reduction. The cut-list evidence ranks this #6 because completion claims are the dominant self-reported failure; the section evidence cites a local false bug-fix claim that was caught only by byte-level verification rather than assertion.
