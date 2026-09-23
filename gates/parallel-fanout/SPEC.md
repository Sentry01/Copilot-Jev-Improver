# Gate: parallel-fanout

**Name:** Parallel Fanout Gate  
**Slug:** `parallel-fanout`  
**Rank / source:** #15 in `cool-use-cases.md`  
**Primary lever:** performance

## Purpose

Decide whether a candidate batch of tool calls should run in parallel or sequentially. The gate catches both missed batching opportunities and unsafe batching when one call depends on another result or writes conflict.

## When to call

Immediately before launching a multi-call batch, especially when the calls mix slow tools or may touch shared state.

## State schema (agent-ops only)

| Field | Type | Notes |
| --- | --- | --- |
| `proposed_calls` | array | Tools and intents in the candidate batch |
| `dependency_notes` | string | Any known ordering requirements |
| `shared_state_touched` | string | Files or resources more than one call touches |
| `est_latencies_ms` | array | Per-call expected durations |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `independent` | `noul` | Belief no call depends on another's result |
| `max_parallel` | `score` | Ordered: `1`, `2`, `3`, `5`, `8` |
| `ordering_risk` | `choice` | `none`, `read_after_write`, `write_conflict`, `rate_limit`, `unknown` |

No free-text questions.

## Thresholds

- **Parallelise** if `independent.noul >= 0.6` and `ordering_risk = none`
- Cap the batch at `max_parallel`
- Any `write_conflict` forces **sequential**

## Fail mode

**Fail-open** on API error or missing answers → action `sequential`, so the work continues without unsafe batching.

## Expected efficiency win

Performance on slow independent calls. The telemetry evidence shows why batching matters: `bash` averaged 9.1 s, `web_search` 39 s, and delegated `task` calls 174 s, so safe fanout is bounded by the slowest call rather than the sum.
