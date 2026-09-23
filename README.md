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

## Why measured, not asserted

The baseline was mined from real Copilot CLI usage on one developer's machine (30-day window).
Highlights:

| Finding | Number | Implication |
| --- | --- | --- |
| Autonomous turns per user turn | **13.5** (6,375 agent vs 473 user requests) | Most spend is the agent talking to itself — gate the loop |
| Single model/effort pair | `claude-opus-5 @ high` = **50.4%** of AI units | Model + effort routing is the biggest single $ lever |
| Most expensive per request | `gpt-6-astra @ xhigh` = **42.7 AIU/req** (2.2× opus-5 high) | Escalation needs justification |
| Spend concentration | Top session = **28.4%** of all spend; top 12 = **77.6%** | Runaway sessions dominate — stop gates matter |
| `bash` doing built-in tools' job | **40.3%** of bash calls are search/read/list | Read amplification |
| Duplicate identical calls | **253+** repeat calls with identical arguments | Straightforward redundancy waste |
| Browser automation reliability | `browser_click` **78.6%** failure, `browser_navigate` **59.6%** | Retry loops burn turns |
| Cache hit rate | **94.4%** | Already good — do *not* chase prompt shaping |

Full method and the complete report: [`telemetry/`](telemetry/).

## Layout

```
docs/        ranked use-case research, exec brief, wiring, and the write-up
telemetry/   session-store queries, the miner, and redacted baseline reports
gates/       the runnable Jev gate library (one directory per gate)
harness/     Copilot CLI skill + ordered gate pipeline for a turn
experiments/ trap suite and proof artifacts
ci-loop/     decision log, proposals, baselines — calibration over time
tests/       offline tests, including the redaction test
```

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
```

Python 3.13, standard library only. No dependencies to install.

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

Early. The gate library and the ranked research are the current focus. Live-Jev proof runs are
pending an API key.

## Provenance

Agent-ops artifact for improving GitHub Copilot CLI with TypeSafe System One (Jev).
Method ported from `Sentry01/grokbot-improver`. Not affiliated with TypeSafe or GitHub.
