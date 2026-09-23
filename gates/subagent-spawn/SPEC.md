# Gate: subagent-spawn

**Name:** Subagent Spawn Gate  
**Slug:** `subagent-spawn`  
**Rank / source:** #8 in `docs/cool-use-cases.md`  
**Primary lever:** cost

## Purpose

Before spawning a subagent, background agent, or factory fleet, ask Jev whether delegation is worth the context transfer, latency, and cost. The gate also protects shared working trees from delegated writers.

## When to call

Immediately before `task`, background-agent launch, factory runs, or any fleet-style delegation.

## State schema

| Field | Type | Notes |
| --- | --- | --- |
| `task_description` | string | What would be delegated |
| `context_transfer_size` | string | How much context the child needs |
| `parent_can_do_inline` | string | Honest assessment |
| `parallelism_benefit` | string | Genuinely independent work? |
| `spawn_kind` | string | `subagent` / `background_agent` / `factory_fleet` |
| `writes_to_shared_tree` | boolean | Can the child mutate the parent's working tree? |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `spawn_justified` | `noul` | Belief delegation beats inline |
| `spawn_reason` | `choice` | `context_isolation`, `true_parallelism`, `specialised_skill`, `underspecified`, `should_inline` |
| `expected_multiplier` | `score` | Ordered: `1x`, `2x`, `5x`, `10x`, `20x_plus` |

No free-text questions.

## Thresholds

Spawn if `spawn_justified >= 0.65` and `spawn_reason != underspecified`. If `writes_to_shared_tree` is true, require a clean or committed tree first regardless of score.

For `factory_fleet`, apply stricter handling because one call can spawn dozens of agents: this implementation requires `spawn_reason = true_parallelism` and `expected_multiplier <= 5x`; otherwise it asks for a narrower spawn or inline work.

## Fail mode

**Fail open** on Jev/API failure, except for the shared-tree hard rule. Delegation is a cost risk rather than an irreversible safety boundary, but a shared-tree writer can destroy sibling work.

## Expected efficiency win

Avoids unnecessary delegated turns. The telemetry evidence is **9.2% of AI Units** in delegated lanes and `task` calls averaging **174 seconds** each; delegation also contributed to the destructive-action incident.
