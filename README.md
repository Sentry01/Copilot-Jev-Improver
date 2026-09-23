# Copilot × Jev Improver

Using **Jev** ([TypeSafe System One](https://api.typesafe.ai)) as a calibrated decision layer in
front of **GitHub Copilot CLI**'s expensive and irreversible moves — to improve **cost, quality,
safety, and performance**.

Sibling project: [`Sentry01/grokbot-improver`](https://github.com/Sentry01/grokbot-improver),
which proved the pattern on Grok Bot. This repo ports it to Copilot CLI and, crucially, ranks the
use cases against **measured telemetry** rather than judgment.

---

## The idea in one paragraph

Copilot CLI is a capable generalist: it runs shell commands, reads files, calls MCP servers,
spawns subagents, and writes to GitHub. Left ungated, that power is expensive. Jev is not a
writer — it is a **fast, calibrated scorer** that returns typed answers (`noul` / `score` /
`choice`) in a few hundred milliseconds. Putting Jev in front of Copilot's costly decisions makes
it leaner without making it dumber. **Copilot still writes; Jev gates, ranks, and routes.**

The gates are not advice. Copilot CLI has a **hook API** that can deny a tool call before it
runs, so this repo ships a plugin that enforces the gates at the point of action rather than a
policy document the agent may choose to read. See
[`docs/copilot-hook-api.md`](docs/copilot-hook-api.md) for the hook contract and its sharp edges
— one of which caused a real fail-open bug in this repo.

## Why measured, not asserted

The baseline was mined from real Copilot CLI usage on one developer's machine (30-day window).
Highlights:

| Finding | Number | Implication |
| --- | --- | --- |
| Autonomous turns per user turn | **13.5** (6,398 agent vs 473 user requests) | Most spend is the agent talking to itself — gate the loop |
| Single model/effort pair | `claude-opus-5 @ high` = **50.3%** of AI units | Model + effort routing is the biggest single $ lever |
| Most expensive per request | `gpt-6-astra @ xhigh` = **42.67 AIU/req** (2.2× opus-5 high) | Escalation needs justification |
| Spend concentration | Top session = **24.8%** of all spend; top 15 = **77.9%** | Runaway sessions dominate — stop gates matter |
| Input:output token ratio | **260.8:1** | Cost is the context you accumulate, not what you generate |
| `bash` doing built-in tools' job | **40.3%** of bash calls are search/read/list | Read amplification |
| Duplicate identical calls | **253+** repeat calls with identical arguments | Straightforward redundancy waste |
| Browser automation reliability | `browser_click` **78.6%** failure, `browser_navigate` **59.6%** | Retry loops burn turns |
| Cache hit rate | **94.4%** | Already good — do *not* chase prompt shaping |

Full method and the complete report: [`telemetry/`](telemetry/).

## Layout

```
docs/        ranked use-case research, exec brief, the hook API reference, and the write-up
telemetry/   session-store queries, the miner, and redacted baseline reports
gates/       the runnable Jev gate library — 16 gates, one directory each (see gates/INDEX.md)
harness/     the Copilot CLI plugin: hooks that route a tool call to the right gate
experiments/ trap suite — adversarial scenarios each gate must catch
ci-loop/     automatic decision logging, scoring, and baselines — calibration over time
tests/       offline tests, including redaction, routing, semantics and repo hygiene
```

## The 16 gates

| Lever | Gates |
| --- | --- |
| **Safety** | `destructive-action`, `secret-exposure`, `external-write`, `prompt-injection` |
| **Cost** | `model-effort-route`, `tool-worth-it`, `redundant-tool-call`, `subagent-spawn`, `context-read-budget` |
| **Performance** | `stop-vs-continue`, `retry-worth-it`, `parallel-fanout` |
| **Quality** | `plan-vs-act`, `skill-selection`, `verification-sufficient`, `response-quality` |

Thresholds, fail modes and Jev question maps: [`gates/INDEX.md`](gates/INDEX.md), generated from
the configs so it cannot drift. Ranking and evidence: [`docs/cool-use-cases.md`](docs/cool-use-cases.md).

## Running it without an API key

Every gate runs offline. The client picks its mode automatically:

| `JEV_MODE` | Behaviour |
| --- | --- |
| unset | `live` if `TYPESAFE_API_KEY` is set, otherwise `fixture` |
| `fixture` | Replays a recorded response from `gates/<slug>/fixtures/`. No network. |
| `live` | Real `POST https://api.typesafe.ai/v1/systemone`, model `jev-latest` |

Every result carries a `source` field (`live` or `fixture`), and so does every artifact written.
**A fixture result is never presented as live proof.**

```bash
# Offline, no key needed
cd gates/<slug> && python3 gate.py

# Live
export TYPESAFE_API_KEY=...        # never commit this
cd gates/<slug> && JEV_MODE=live python3 gate.py

# The whole thing, offline
JEV_MODE=fixture python3 -m unittest discover -s tests   # 87 tests
python3 -B experiments/traps/run_traps.py                # 10 adversarial traps
```

Python 3.13, standard library only. No dependencies to install.

## Installing the gates into Copilot CLI

The harness is a Copilot CLI plugin. Its `hooks.json` registers `preToolUse`,
`postToolUseFailure`, `agentStop` and `sessionStart`; the `preToolUse` hook is the one that can
actually stop a tool call. Hard rules (read-only integrations, retry caps, dirty-tree spawns)
resolve locally before Jev is consulted at all — which is both faster and, because hook
**timeouts fail open**, the only way to make a safety rule survive a slow network.

Decision logging is **off by default**; set `COPILOT_JEV_LOG_DECISIONS=1` to record what the
gates decided into `ci-loop/logs/` (gitignored — see Privacy).

## Secrets

**Never commit API keys.** `TYPESAFE_API_KEY` is read from the environment only, and is never
logged, printed, or written into any artifact. See [`.gitignore`](.gitignore) for excluded
patterns.

## Privacy

This repository is **public**, and the telemetry source contains client and customer work.
Published telemetry is **aggregate-only**: counts, ratios, durations, costs, and tool names.
No repository names, file paths, branch names, session content, prompts, or customer names are
ever published. This is enforced by an allowlist in the miner and covered by a test, not just by
policy — see [`telemetry/README.md`](telemetry/README.md).

## Status

The ranked research, the 16-gate library, the enforcing plugin, the trap suite and the
improvement loop are built and pass offline: **87 tests, 16 gates, 10 traps**.

**Verified against a running CLI (1.0.89-0):** the plugin's hooks load, `${PLUGIN_ROOT}` expands
inside `args`, and a `preToolUse` deny genuinely prevents execution — proven by A/B control, where
the same benign command ran without the plugin and was blocked with it.

**Measured:** end-to-end hook cost is **40 ms** ungated / **86 ms** for a fixture gate, dominated
by Python startup rather than gate logic — see
[`experiments/latency/RESULTS.md`](experiments/latency/RESULTS.md). The verdict is deliberately
*mixed*: gates pay for themselves on expensive and failure-prone tools, and can **never** pay on
cheap ones like `edit`.

What is **not** proven: no gate has run against live Jev, because `TYPESAFE_API_KEY` was
unavailable — every result here is `fixture` or `policy`, and is labelled as such. Thresholds are
reasoned from telemetry rather than validated against outcomes, and live Jev network latency
remains an assumption in the break-even model.
[`docs/HOW-JEV-IMPROVES-COPILOT.md`](docs/HOW-JEV-IMPROVES-COPILOT.md) keeps a running list of
what would have to be measured to call any of this proven.

## Provenance

Agent-ops artifact for improving GitHub Copilot CLI with TypeSafe System One (Jev).
Method ported from `Sentry01/grokbot-improver`. Not affiliated with TypeSafe or GitHub.
