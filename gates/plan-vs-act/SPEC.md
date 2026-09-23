# Gate: plan-vs-act

**Name:** Plan vs Act Gate  
**Slug:** `plan-vs-act`  
**Rank / source:** #11 in `cool-use-cases.md`  
**Primary lever:** quality

## Purpose

Choose between acting immediately, giving a quick outline, making a full plan, or asking a clarifying question. The gate prevents both unplanned sprawl on multi-step work and ceremonial planning for a one-line change.

## When to call

At the start of a user turn, before choosing a workflow mode for non-trivial implementation, debugging, review, or analysis work.

## State schema (agent-ops only)

| Field | Type | Notes |
| --- | --- | --- |
| `user_request` | string | The ask |
| `estimated_steps` | integer | Rough step count |
| `files_likely_touched` | integer | Rough breadth |
| `ambiguity` | string | What is genuinely unclear |
| `reversibility` | string | `trivial` / `moderate` / `hard` |
| `user_specified_mode` | string | Did the user ask to plan, or to just do it? |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `needs_plan` | `noul` | Belief that planning first improves the outcome |
| `ambiguity_level` | `score` | Ordered: `none`, `minor`, `moderate`, `high`, `blocking` |
| `recommended_mode` | `choice` | `act_now`, `quick_outline`, `full_plan`, `ask_clarifying_first` |

No free-text questions.

## Thresholds

- **Plan** if `needs_plan.noul >= 0.6` or `ambiguity_level >= high`
- If `ambiguity_level == blocking`, **ask_clarifying_first** wins over `full_plan`
- `user_specified_mode` always overrides the Jev result; if the user said just do it, return `act_now`

## Fail mode

**Fail-open** on API error or missing answers → `proceed=true` / action `act_now` so Jev does not block fast-path work.

## Expected efficiency win

Quality and cost control. The ranking evidence cites the 13.5:1 autonomous-turn ratio and Pareto tail as the cost of unplanned sprawl, while still preserving the fast path when planning would be overhead.
