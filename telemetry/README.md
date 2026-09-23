# Telemetry

The ranking in [`docs/cool-use-cases.md`](../docs/cool-use-cases.md) is grounded in measured
Copilot CLI usage rather than judgment. This directory holds the queries, the miner, and the
redacted baseline reports.

## Why this exists

`grokbot-improver` ranked its gates by reasoning about likely failure modes. That works, but it
cannot tell you *how much* any given waste class is worth, so it cannot tell you what to build
first. Copilot CLI records per-request model, reasoning effort, billed AI Units, token counts,
latency, and initiator. That turns "this seems wasteful" into a number.

## Running it

```bash
python3 telemetry/mine_waste.py                      # writes reports/baseline-<date>.{md,json}
python3 telemetry/mine_waste.py --stdout             # print instead of writing
python3 telemetry/mine_waste.py --window '-7 days'   # different window
python3 telemetry/mine_waste.py --db /path/to/store  # different store
```

Standard library only. The store is opened **read-only** (`mode=ro`) — mining never mutates it.

## Data sources

| Queries | Source | How to run |
| --- | --- | --- |
| `01`–`06` | **Local** `~/.copilot/session-store.db`, table `assistant_usage_events` | `mine_waste.py` runs these directly |
| `07`–`09` | **Cloud** session store views `tool_executions`, `tool_requests` | Run via the Copilot CLI `session_store_sql` tool (DuckDB dialect) |

The split exists because tool-level execution records are not mirrored into the local SQLite
store. The cloud queries are committed so the tool-level findings are reproducible, even though
this script cannot execute them.

## What each query answers

| Query | Lever | Question it settles |
| --- | --- | --- |
| `01-cost-by-model-effort` | cost | Which model/effort pair dominates the bill, and what does each request cost? |
| `02-initiator-split` | cost, performance | How much of the spend is the agent talking to itself vs responding to a human? |
| `03-token-shape-and-cache` | cost | Is there anything left to win from prompt shaping and caching? |
| `04-session-cost-concentration` | cost | Is spend Pareto-distributed across sessions? |
| `05-latency-profile` | performance | What latency budget must a gate fit inside to be worth calling? |
| `06-main-vs-subagent` | cost | How much of the bill flows through delegated lanes? |
| `07-tool-mix` | cost, performance | Which tools dominate calls, wall-clock time, and failures? |
| `08-redundant-tool-calls` | cost | How many calls repeat byte-identical arguments inside one session? |
| `09-bash-intent-split` | cost, safety | How often does the shell do a purpose-built tool's job? |

## Redaction

This repository is **public**, and the session store contains client and customer work. The rule
is **aggregate-only**: counts, ratios, durations, costs, model names, and tool names.

Never published: session IDs, repository names, branch names, working directories, file paths,
prompts, assistant responses, tool arguments, or customer names.

This is enforced in code, not by convention. `mine_waste.py` checks every emitted cell:

1. **Column allowlist** — `ALLOWED_COLUMNS` lists every publishable column name. Anything else
   raises `RedactionError` and no artifact is written.
2. **Value scan** — `looks_identifying()` rejects UUIDs, home-directory paths, and strings over
   64 characters, so an allowed column cannot smuggle an identifier through.

Both failure modes abort the run rather than writing a partial report. Query `04` deliberately
drops `session_id` and publishes only a rank; queries `08` and `09` use `arguments_json` as a
grouping key and never select it.

Verify the guard:

```bash
python3 -m unittest discover -s tests -v
```

## Caveats

- **One machine, one developer.** These numbers are directional, not a population estimate. They
  are used to *order* the gate backlog, not to claim an industry benchmark.
- **AI Units are not dollars.** `total_nano_aiu` already folds in per-model billing multipliers.
  Treat it as relative cost.
- **Mixed workload.** This developer's sessions include GTM data analysis, not just coding, so
  the tool mix skews toward data and browser tools more than a pure engineering workload would.
- **Cache is already at 94%.** Recorded here mainly as a *negative* result: prompt shaping is not
  where the remaining win is.
