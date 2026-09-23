# Top 10 Jev Gates for GitHub Copilot CLI — Brief

**As-of:** 2026-09-23 · **Scope:** Copilot CLI agent-ops
**Full specs:** [`cool-use-cases.md`](./cool-use-cases.md) · **Evidence:** [`../telemetry/reports/baseline-2026-09-23.md`](../telemetry/reports/baseline-2026-09-23.md)

---

## The argument in five lines

1. **13.5 model requests fire per user request.** The bill is the agent talking to itself.
2. **One model/effort pair is 50.3% of all AI Units**, and tiers differ by up to 60× per request.
3. **Spend is Pareto**: the top session is ~25% of all AI Units; the top 15 are 78%.
4. **Cache is already 94.4%** — prompt compression is a dead end, so the lever is *avoided turns*.
5. Every one of those is a **decision**, and decisions are what a calibrated gate is for.

Copilot is good at doing the work. It is structurally bad at judging its own work mid-flight,
because the thing being judged is also the judge. Jev is a second, independent, calibrated
opinion that returns a typed number in a few hundred milliseconds — cheap enough to put in front
of an expensive action, and constrained enough that software can branch on it without parsing prose.

---

## The ten

| # | Gate | Lever | Why it earns the slot | Effort |
| ---: | --- | --- | --- | --- |
| 1 | `model-effort-route` | cost | 2.2× spread between the two most-used tiers; 60× across the range | M |
| 2 | `stop-vs-continue` | cost, perf | Caps the runaway session that *is* the top quartile of spend | S |
| 3 | `tool-worth-it` | cost, perf | 2,060 bash calls at 9.1 s = 5.0 h of wall clock in 30 days | S |
| 4 | `context-read-budget` | cost | 40.3% of bash calls did a built-in tool's job; 260.8:1 input:output | S |
| 5 | `redundant-tool-call` | cost | 253+ byte-identical repeat calls — the least arguable waste in the data | S |
| 6 | `verification-sufficient` | quality | Turns "done" from an assertion into a claim with evidence behind it | M |
| 7 | `destructive-action` | safety | An agent in *this repo's own history* destroyed uncommitted work | S |
| 8 | `subagent-spawn` | cost | 9.2% of AI Units delegated; one `run_factory` call can spawn dozens | S |
| 9 | `retry-worth-it` | perf | `browser_click` fails 78.6% of the time; blind retry has negative EV | S |
| 10 | `secret-exposure` | safety | Public repo, customer data in the store, six credentialed integrations | M |

Ranks 11–15 (`plan-vs-act`, `external-write`, `response-quality`, `skill-selection`,
`parallel-fanout`) are built and shipped in [`gates/`](../gates/) but are second-wave: smaller
measured waste, or already partly handled by standing policy.

---

## Where the money actually is

Three gates cover the majority of the addressable waste, and they are the three cheapest to build:

> **`model-effort-route` + `stop-vs-continue` + `context-read-budget`**

They attack the same underlying fact from three angles — *too many turns, at too high a tier,
carrying too much context.* Nothing in the current loop questions any of the three.

The rest of the library is insurance and polish. Valuable, but if only one thing gets built,
build routing.

---

## What would make this fail

Stated up front, because a brief that only lists upside is marketing.

**Gate latency eats the win.** Each gate costs roughly 300–500 ms. Put one in front of a 256 ms
`edit` call and you have made things worse. The harness short-circuits trivial turns and only
gates calls where `est_latency_ms ≥ 2000` or cost tier is above `low`. If that discipline slips,
the whole thing is net negative.

**Thresholds start wrong.** They are informed guesses. The upstream sibling project shipped a
send-gate at 0.70 that false-held genuinely good answers, and had to drop it to 0.65 and add an
`evidence_sources` field before it behaved. Expect one or two of these numbers to be wrong in the
same way. That is what [`ci-loop/`](../ci-loop/) exists for — it is not optional scaffolding.

**A downgrade that fails costs more than no gate.** Routing a hard task to a cheap tier, watching
it fail, and retrying at the top tier is strictly worse than never routing. Hence the deliberately
asymmetric thresholds (downgrade below 0.45, escalate above 0.80, otherwise change nothing) and
the rule that a failed attempt disables further downgrades.

**Scores must not override policy.** Some things are rules, not beliefs: a read-only channel, a
hard retry cap, a clean tree before a shared-tree spawn. Those are early returns that never reach
Jev. A calibrated number that can argue its way past a standing policy is a liability.

---

## How we would know it worked

The same miner that produced the baseline re-runs after the harness is live, on the same window
length. Targets, in priority order:

| Metric | Baseline | What good looks like |
| --- | --- | --- |
| Share of AI Units at top tier | 50.3% | Down, with no rise in rework or retries |
| Agent requests per user request | 13.5 | Down |
| Top-session share of AI Units | 24.8% | Down — the tail is the target |
| Byte-identical repeat calls | 253+ | Near zero |
| bash calls doing a built-in's job | 40.3% | Down |
| Failed-tool retry attempts | — | Down, especially on browser paths |
| Completion claims without evidence | — | Zero |

The honest version of this table also needs a **guardrail**: if turns and cost fall while task
success falls too, the gates are not saving money, they are just doing less. The trap suite and a
live gated session are there to catch exactly that.

---

## Status

Ranked against measured telemetry ✅ · Gate library built ✅ · Trap suite and CI loop in progress ·
Live end-to-end proof **pending a `TYPESAFE_API_KEY`**.

Everything in this repo runs offline against recorded fixtures. Every result carries a
`source: live | fixture` field, so a fixture is never presented as live proof.
