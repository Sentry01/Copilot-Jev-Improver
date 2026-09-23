# Gate: skill-selection

**Name:** Skill Selection Gate  
**Slug:** `skill-selection`  
**Rank / source:** #14 in `cool-use-cases.md`  
**Primary lever:** quality

## Purpose

Decide whether to load a workflow skill before doing the task. The gate balances two errors: ignoring a relevant skill that encodes process knowledge, or loading a heavyweight skill when the task does not need it.

## When to call

After a short candidate-skill shortlist has been assembled from skill names and descriptions, before invoking the `skill` tool.

## State schema (agent-ops only)

| Field | Type | Notes |
| --- | --- | --- |
| `user_request` | string | The ask |
| `candidate_skills` | array | `[{name, description}]` shortlist |
| `task_domain` | string | e.g. `code_edit`, `data_analysis`, `document`, `research` |
| `skill_context_cost` | string | `small` / `medium` / `large` |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `skill_needed` | `noul` | Belief a skill materially improves the outcome |
| `best_skill` | `choice` | Built dynamically from `candidate_skills`, plus `none` |
| `match_strength` | `score` | Ordered: `none`, `weak`, `partial`, `strong`, `exact` |

No free-text questions.

## Thresholds

- **Load** if `skill_needed.noul >= 0.6` and `match_strength >= partial`
- Do not load when `best_skill=none`
- Shortlist first and send at most about 8 candidates, always keeping a `none` option

## Fail mode

**Fail-open** on API error or missing answers → action `skip_skill` so the task can continue without forcing context load.

## Expected efficiency win

Quality with controlled context cost. The telemetry evidence is concrete: 65+ skills are installed, yet `skill` was invoked only 17 times in 30 days across sessions that made 2,060 bash calls.
