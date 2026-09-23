# Gate: context-read-budget

**Name:** Context Read Budget Gate  
**Slug:** `context-read-budget`  
**Rank / source:** #4 in `docs/cool-use-cases.md`; telemetry evidence: **831 of 2,060 bash calls (40.3%)** duplicated built-in search/list/read tools, while the token profile was **260.8:1 input:output**.  
**Primary lever:** cost

## Purpose

Keep unnecessary file and tree reads out of context by preferring targeted search, bounded ranges, or reuse of already-read content.

## When to call

Before full-file reads, recursive searches, broad `cat`/`grep` shell calls, or any read likely to add substantial tokens to context.

## State schema

| Field | Type | Notes |
| --- | --- | --- |
| `goal` | string | What we need from the file or tree |
| `target` | string | Path pattern or search scope |
| `known_size_tier` | string | `small` / `medium` / `large` / `unknown` |
| `proposed_read` | string | e.g. `full_file`, `range`, `recursive_grep` |
| `already_read` | string | What is already in context |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `full_read_justified` | `noul` | Belief the whole thing is genuinely needed |
| `read_strategy` | `choice` | `targeted_search`, `ranged_read`, `full_read`, `already_have_it` |
| `expected_relevance` | `score` | Ordered: `none`, `low`, `moderate`, `high`, `certain` |

No free-text questions.

## Thresholds

- Allow a **full read** only if `full_read_justified >= 0.7`.
- Otherwise follow `read_strategy` with a bounded alternative.
- On `already_have_it`, skip entirely.

## Fail mode

**Fail-open** on API or answer-shape errors → `proceed=true` / action `use_proposed_read` so Jev outages do not block progress.

## Expected efficiency win

Compounding context savings: every avoided large read saves tokens on the current request and on subsequent turns that would otherwise re-send that context.
