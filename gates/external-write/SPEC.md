# Gate: external-write

**Name:** External Write Gate  
**Slug:** `external-write`  
**Rank / source:** #12 in `docs/cool-use-cases.md`  
**Primary lever:** safety

## Purpose

Before creating, sending, or posting anything that leaves the machine, ask Jev whether the write is authorized, correct, and wanted. This covers PRs, issues, review comments, Slack messages, emails, calendar invites, and similar externally visible operations.

## When to call

Immediately before an external write tool or API call, after deterministic channel policies have already been checked.

## State schema

| Field | Type | Notes |
| --- | --- | --- |
| `action` | string | e.g. `create_pull_request`, `send_message`, `create_issue` |
| `destination` | string | Who or what receives it |
| `content_summary` | string | What it says |
| `user_authorised` | boolean | Did the user explicitly request this send? |
| `channel_policy` | string | `read_only` / `write_allowed` |
| `reversible` | string | `editable` / `deletable` / `permanent` |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `safe_to_send` | `noul` | Belief this is authorised, correct, and wanted |
| `authorisation_basis` | `choice` | `explicit_request`, `standing_policy`, `inferred`, `none` |
| `audience_risk` | `score` | Ordered: `self`, `team`, `org`, `customer`, `public` |

No free-text questions.

## Thresholds

Send only if `safe_to_send >= 0.75` and `authorisation_basis` is `explicit_request` or `standing_policy`. `inferred` is never sufficient for an external write.

Hard rule, not a threshold: if `channel_policy = read_only`, block unconditionally and do not call Jev at all. A calibrated score must not be able to talk its way past a standing policy.

## Fail mode

**Fail closed.** On missing answers or Jev failure, block the write. Failing open would be wrong because writes are visible, attributed, and sometimes impossible to fully retract; this operator also has a standing read-only rule for Microsoft 365 and Slack.

## Expected efficiency win

This is a safety and trust gate. It prevents externally visible mistakes and avoids the follow-up cost of deleting, correcting, or explaining an unauthorized write. The telemetry evidence is the available write-capable toolset plus the standing read-only policy for M365 and Slack.
