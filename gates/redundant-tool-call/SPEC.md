# Gate: redundant-tool-call

**Name:** Redundant Tool Call Gate  
**Slug:** `redundant-tool-call`  
**Rank / source:** #5 in `docs/cool-use-cases.md`; telemetry evidence: **253+ byte-identical repeat calls** within a single session, including 77 `bash`, 46 `view`, and 26 `browser_snapshot` repeats.  
**Primary lever:** cost

## Purpose

Reuse answers already in context instead of repeating tool calls with the same arguments, unless volatility or an intervening mutation makes the repeat legitimate.

## When to call

Immediately before a proposed tool call whose tool name and arguments match, or nearly match, a prior call in the same turn or session.

## State schema

| Field | Type | Notes |
| --- | --- | --- |
| `proposed_call` | string | Tool and arguments summary |
| `prior_calls` | string | Comparable earlier calls this session |
| `elapsed_since_prior` | string | How stale the prior result is |
| `volatility` | string | `static` / `slow` / `volatile` — is the underlying thing likely to have changed? |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `is_redundant` | `noul` | Belief we already hold this answer |
| `reuse_strategy` | `choice` | `reuse_cache`, `narrow_scope`, `call_anyway_stale`, `call_anyway_new` |

No free-text questions.

## Thresholds

- **Skip or reuse** if `is_redundant >= 0.65`.
- If volatility is `volatile`, or the state indicates a mutation happened between calls, call anyway because the repeat may be legitimate.
- Otherwise use `reuse_strategy` to reuse cached context or narrow the call.

## Fail mode

**Fail-open** on API or answer-shape errors → `proceed=true` / action `call_tool` so Jev outages do not block progress.

## Expected efficiency win

Eliminates the least ambiguous waste class: byte-identical repeat calls whose result is already in context.
