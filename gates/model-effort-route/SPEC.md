# Gate: model-effort-route

**Name:** Model Effort Route Gate  
**Slug:** `model-effort-route`  
**Rank / source:** #1 in `docs/cool-use-cases.md`; telemetry evidence: `claude-opus-5 @ high` accounts for **50.3%** of AI Units across 3,861 requests, and `gpt-6-astra @ xhigh` costs **42.67 AIU/req** versus `gpt-5.6-luna @ medium` at **0.33 AIU/req**.  
**Primary lever:** cost

## Purpose

Route each Copilot CLI turn to the least expensive model/effort tier that can still satisfy the request, instead of letting trivial reads and cross-cutting refactors use the same expensive tier.

## When to call

At most once near the start of a user turn, after the turn kind, blast radius, context size, prior attempts, and current tier are known.

## State schema

| Field | Type | Notes |
| --- | --- | --- |
| `user_request` | string | What was asked this turn |
| `turn_kind` | string | `question` / `edit` / `refactor` / `debug` / `research` / `review` |
| `blast_radius` | string | `read_only` / `single_file` / `multi_file` / `cross_cutting` |
| `context_size_tier` | string | `small` / `medium` / `large` |
| `prior_attempts` | integer | Failed attempts so far this turn |
| `current_tier` | string | Model and effort currently selected |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `needs_frontier_model` | `noul` | Belief that a cheaper tier would produce a materially worse result |
| `reasoning_depth` | `score` | Ordered: `trivial`, `shallow`, `moderate`, `deep`, `exhaustive` |
| `recommended_tier` | `choice` | `cheap_fast`, `mid`, `frontier_medium`, `frontier_high`, `frontier_xhigh` |

No free-text questions.

## Thresholds

- **Downgrade** only when `needs_frontier_model < 0.45` and `reasoning_depth <= shallow`.
- If `prior_attempts > 0`, never downgrade even when the downgrade signals are present.
- **Escalate** above the session default only when `needs_frontier_model >= 0.8` and `reasoning_depth >= deep`.
- Otherwise **keep the current tier**. The default action is change nothing.

## Fail mode

**Fail-open** on API or answer-shape errors → `proceed=true` / action `keep_current_tier` so routing uncertainty does not block work.

## Expected efficiency win

Largest single measured cost lever. Even moving the cheapest third of turns down one tier can remove a double-digit percentage of spend while preserving expensive tiers for deep work.
