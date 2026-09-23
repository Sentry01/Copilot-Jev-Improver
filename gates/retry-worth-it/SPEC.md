# Gate: retry-worth-it

**Name:** Retry Worth-It Gate  
**Slug:** `retry-worth-it`  
**Rank / source:** #9 in `docs/cool-use-cases.md`  
**Primary lever:** performance

## Purpose

Before retrying a failed tool call, ask Jev whether the next attempt is materially different enough to work. This prevents structural failures from becoming retry loops.

## When to call

After a tool failure and before another attempt with the same tool, same surface, or same overall path.

## State schema

| Field | Type | Notes |
| --- | --- | --- |
| `failed_tool` | string | What failed |
| `error_summary` | string | The error returned |
| `attempt_number` | integer | How many tries so far |
| `change_since_last_attempt` | string | What is actually different this time |
| `tool_historical_failure_rate` | number | From the telemetry baseline |
| `alternative_paths` | string | Other ways to get the same result |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `retry_will_succeed` | `noul` | Belief this attempt differs enough to work |
| `failure_class` | `choice` | `transient`, `auth`, `wrong_target`, `unsupported`, `malformed_input` |
| `next_action` | `choice` | `retry_same`, `retry_adjusted`, `switch_tool`, `ask_user`, `abandon` |

No free-text questions.

## Thresholds

Retry if `retry_will_succeed >= 0.55` and `change_since_last_attempt` is non-empty. Never `retry_same` when `failure_class` is `auth` or `unsupported`; those need a different path. Hard-stop at `attempt_number >= 3` regardless of score.

## Fail mode

**Fail open** on Jev/API failure, except for deterministic hard stops. Retrying may waste time, but blocking all retries when Jev is unavailable would make ordinary tool recovery too brittle.

## Expected efficiency win

Pure latency and turn-count reduction. The telemetry evidence is strongest here: `browser_click` failed **22 of 28 times (78.6%)**, `browser_navigate` failed **31 of 52 (59.6%)**, and `browser_type` failed **3 of 5 times (60%)**.
