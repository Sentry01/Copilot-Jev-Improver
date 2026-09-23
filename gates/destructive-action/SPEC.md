# Gate: destructive-action

**Name:** Destructive Action Gate  
**Slug:** `destructive-action`  
**Rank / source:** #7 in `docs/cool-use-cases.md`  
**Primary lever:** safety

## Purpose

Before running an irreversible local or remote action, ask Jev whether the command is safe enough and whether the blast radius is recoverable. The gate prevents plausible cleanup or recovery steps from destroying work the user still needs.

## When to call

Immediately before destructive commands or operations such as `rm -rf`, `git clean -fd`, hard resets, force pushes, history rewrites, table drops, or broad process kills.

## State schema

| Field | Type | Notes |
| --- | --- | --- |
| `proposed_command` | string | The exact command |
| `working_tree_state` | string | Uncommitted or untracked work present? |
| `scope` | string | What the command can reach |
| `recoverable` | string | `trivially` / `from_git` / `from_backup` / `no` |
| `user_asked_for_it` | boolean | Did the user explicitly request this destructive step? |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `safe_to_execute` | `noul` | Belief this destroys nothing the user wants |
| `blast_radius` | `score` | Ordered: `none`, `scratch_only`, `recoverable`, `costly`, `catastrophic` |
| `safer_alternative` | `choice` | `none_needed`, `narrow_scope`, `commit_first`, `dry_run_first`, `ask_user` |

No free-text questions.

## Thresholds

Execute only if `safe_to_execute >= 0.8` and `blast_radius <= recoverable`. Otherwise take `safer_alternative`. The motivating incident was a cleanup step that destroyed another session's uncommitted work; `commit_first` would have prevented it.

## Fail mode

**Fail closed.** On missing answers or Jev failure, do not execute the destructive action. Failing open would be wrong because the damage can be irreversible and can affect other agents' or the user's uncommitted work.

## Expected efficiency win

This is a safety gate, not a spend gate. It avoids high-cost recovery and rework from destructive mistakes; the telemetry evidence is this repo's own incident where a subagent removed uncommitted telemetry work and reverted files.
