# Gate: stop-vs-continue

**Name:** Stop vs Continue Gate  
**Slug:** `stop-vs-continue`  
**Rank / source:** #2 in `docs/cool-use-cases.md`; telemetry evidence: **6,396 agent-initiated requests vs 473 user-initiated** (13.5 autonomous requests per human turn), with the top session consuming **24.8%** of all AI Units and the top 15 sessions **77.9%**.  
**Primary lever:** cost / performance

## Purpose

Cap runaway autonomous loops by asking whether another step still has enough marginal value to justify its cost.

## When to call

During long turns after meaningful progress has been made, especially when the latest tool call repeated or confirmed already-known information.

## State schema

| Field | Type | Notes |
| --- | --- | --- |
| `user_goal` | string | Original ask |
| `progress_summary` | string | What is established so far |
| `open_questions` | string | What genuinely remains |
| `steps_taken` | integer | Tool calls this turn |
| `last_step_yield` | string | What the most recent step actually added |
| `budget_tier` | string | `low` / `normal` / `high` |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `should_stop` | `noul` | Belief that continuing adds little |
| `marginal_value` | `score` | Ordered: `none`, `trivial`, `modest`, `substantial`, `critical` |
| `stop_reason` | `choice` | `goal_met`, `diminishing_returns`, `blocked_needs_user`, `wrong_approach`, `keep_going` |

No free-text questions.

## Thresholds

- **Stop** if `should_stop >= 0.6` or `marginal_value < modest`.
- If the stop reason is `wrong_approach`, return a distinct **re-plan** action rather than silently stopping.
- Otherwise continue.

## Fail mode

**Fail-open** on API or answer-shape errors → `proceed=true` / action `continue` so Jev outages do not strand the agent mid-task.

## Expected efficiency win

Directly targets the Pareto tail of expensive sessions by stopping or re-planning low-yield autonomous work before it compounds.
