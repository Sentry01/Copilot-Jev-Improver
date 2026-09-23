# Gate: tool-worth-it

**Name:** Tool Worth-It Gate  
**Slug:** `tool-worth-it`  
**Rank / source:** #3 in `docs/cool-use-cases.md`; telemetry evidence: `bash` ran **2,060** times at **9.1 s** average for **5.0 h** wall-clock, `kusto_query_readonly` had a **13.2%** failure rate, and `web_search` averaged **39 s**.  
**Primary lever:** cost / performance

## Purpose

Avoid speculative expensive tool calls when the answer is already in hand or a cheaper instrument would do.

## When to call

Immediately before costly tools such as web search, browser automation, expensive shell commands, Kusto, or MCP round trips.

Do **not** gate cheap tools. The short-circuit rule is: only call this gate when `est_latency_ms >= 2000` or `est_cost_tier != low`; the gate exposes `should_gate(state)` for harnesses to enforce this.

## State schema

| Field | Type | Notes |
| --- | --- | --- |
| `user_goal` | string | What the user wants |
| `already_have` | string | Evidence already gathered this turn |
| `proposed_tool` | string | Tool name and intent |
| `est_cost_tier` | string | `low` / `medium` / `high` |
| `est_latency_ms` | integer | Expected duration, from the latency profile |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `tool_worth_it` | `noul` | Belief the call materially improves the answer |
| `primary_blocker` | `choice` | `already_answered`, `wrong_tool`, `low_signal`, `user_not_needed`, `none` |

No free-text questions.

## Thresholds

- **Run** if `tool_worth_it >= 0.65`.
- Otherwise **skip** and log `primary_blocker`.
- Short-circuit without Jev for cheap/fast tools where `est_latency_ms < 2000` and `est_cost_tier == low`.

## Fail mode

**Fail-open** on API or answer-shape errors → `proceed=true` / action `run_tool` so Jev outages do not block real work.

## Expected efficiency win

A 300–500 ms gate pays for itself on expensive calls by avoiding low-signal web, shell, browser, and MCP work.
