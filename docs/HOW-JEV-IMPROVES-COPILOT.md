# How Jev improves GitHub Copilot

A synthesis of what this repository found, built, and failed to prove.

The other documents are reference: [`cool-use-cases.md`](cool-use-cases.md) ranks and specifies
the gates, [`copilot-hook-api.md`](copilot-hook-api.md) documents the enforcement contract,
[`top-10-brief.md`](top-10-brief.md) is the executive version. This one is the argument.

---

## 1. The thesis

GitHub Copilot CLI is a generalist agent with a large action surface: shell, files, MCP servers,
subagents, GitHub writes. Its cost, its failure modes, and its risk are all concentrated in
**decisions to act** — which model to think with, whether a tool call is worth making, whether to
retry, whether to keep going, whether an irreversible thing should happen at all.

Copilot makes those decisions with the same expensive frontier model it uses to write code. That
is the waste. A frontier model asked *"is this worth doing?"* costs nearly as much as one asked
to do it.

Jev ([TypeSafe System One](https://api.typesafe.ai)) is a different instrument: a fast,
calibrated scorer that returns a typed answer — a score, a boolean, a choice from a fixed set —
rather than prose. That is exactly the shape of a gate decision.

So: **Copilot writes; Jev decides whether writing should happen.**

That framing is not novel — the sibling project `Sentry01/grokbot-improver` established it. What
this repo adds is two things that project could not do:

1. **The ranking is measured, not asserted.** Real Copilot CLI telemetry decided which gates
   exist and which do not.
2. **The gates are enforced, not advised.** Copilot CLI has a hook API that can deny a tool call
   before it runs.

Both turned out to matter more than expected, and both produced surprises.

---

## 2. The ranking is measured

The cheapest way to build a gate library is to reason about what *sounds* wasteful. That produces
a plausible library that gates the wrong things.

Instead, the use cases were ranked against a 30-day window of real Copilot CLI usage from one
developer's machine (method and full report in [`telemetry/`](../telemetry/); published figures
are aggregate-only). The headline numbers:

| Signal | Measured | What it decided |
| --- | --- | --- |
| Autonomous turns per user turn | **13.5** (6,398 agent vs 473 user) | Gate the agent's own loop, not the user's prompts |
| `claude-opus-5 @ high` | **50.3%** of all AI Units, 19.52 AIU/req | Model+effort routing is the single biggest lever |
| `gpt-6-astra @ xhigh` | **42.67 AIU/req** | Escalation must be justified, not reflexive |
| Cheapest tier (`gpt-5.6-luna @ medium`) | **0.33 AIU/req** | ~60× spread — routing is worth real money |
| Input:output token ratio | **260.8:1** | Cost is accumulated *context*, not generation |
| Spend concentration | Top session **24.8%**, top 15 **77.9%** | A few runaway sessions dominate everything |
| `bash` doing a built-in's job | **40.3%** of 2,060 calls | Read amplification is systemic |
| Identical repeat calls | **253+** | Redundancy is not hypothetical |
| `browser_click` failure rate | **78.6%** | Retry loops burn turns on tools that mostly fail |
| Subagent share of AI Units | **9.2%** | Real, but not the main event |

### The negative results mattered most

Two measurements **removed** gates from the library:

- **Cache hit rate was already 94.4%.** Prompt shaping and prefix stabilisation — an obvious,
  attractive optimisation — had almost nothing left to win. It was cut.
- **Subagents were only 9.2% of spend.** Worth one gate, not the three the intuition suggested.

The 260.8:1 input:output ratio redirected the cost gates entirely. The instinct is to make the
model generate less. The data says generation is a rounding error and the cost is what you feed
it, so the cost gates target *reads, redundancy and routing*.

A library built on judgement would have shipped prompt-shaping and under-weighted context reads.

---

## 3. The gates are enforced

The plan for this repo originally assumed Copilot CLI had no enforcement point, and that the
deliverable was a skill the agent could consult. That assumption was wrong: Copilot CLI has a
**hook API**, and a `preToolUse` hook can return `deny`.

That changes the artifact from documentation into a control plane. The harness in
[`harness/copilot-jev-gates/`](../harness/copilot-jev-gates/) is a Copilot CLI plugin that routes
each tool call to the right gate and converts the gate's verdict into an
`allow` / `ask` / `deny` decision.

It matters because advisory policy has a structural hole: the agent decides whether to consult
it, and an agent behaving badly is precisely the one that skips the check. A hook does not offer
that choice.

### Three decisions worth defending

**Hard rules resolve before Jev is called.** Read-only integrations, the third identical retry,
spawning into a dirty shared tree — these return `source=policy` with zero network calls. This
began as latency engineering. It became a security property when the hook docs revealed that
`preToolUse` hooks **fail closed on crash but fail open on timeout**. A gate that depends on the
network can therefore be defeated by making the network slow. A local rule cannot time out.

That same finding exposed a real bug in this repo: `jev_client` defaulted to a 60-second HTTP
timeout under a 10-second hook budget, so a slow Jev would have silently allowed destructive and
secret-exposing calls — failing open exactly when conditions were worst. Fixed by giving the gate
a fraction of the hook budget with headroom to report.

**Safety fails closed, cost fails open.** Wrongly blocking a cheap action annoys a user; wrongly
allowing a destructive one loses work. `tests/test_repo_hygiene.py` asserts no safety gate can
proceed on error.

**A fixture-backed block returns `ask`, not `deny`.** Replayed evidence is not live evidence, and
denying on it claims confidence the repo does not have. Under a cloud agent `ask` is treated as
`deny`, so it still fails safe. `source=policy` denies outright, because deterministic local
logic is not a replay.

---

## 4. The three bugs are the most interesting result

Every bug found in this repo was in **this repo's own gate code**, and each one is a live
instance of the failure mode its gate exists to prevent. They are the strongest available
evidence that these failure modes are real rather than imagined.

### Bug 1 — prose matched as substrings (safety, fail-open)

`violates_read_only()` checked whether a tool name contained a read verb. The string
`"slack-SendMessageToChannel"`, lowercased, contains `"get"`. A Slack **send** was classified as
a read and allowed.

Fixed by tokenising on separators and camelCase and requiring whole-token matches, with
unrecognised names blocking rather than passing.

### Bug 2 — negation ignored (cost, found by the trap suite)

`redundant-tool-call` looked for the token `"mutation"` to decide whether state had changed since
an identical earlier call. The evidence string `"no intervening mutation"` contains `"mutation"`,
so the gate concluded a mutation *had* occurred and approved exactly the redundant call it exists
to stop.

**Same root cause as bug 1: substring-matching prose.** Fixed by preferring an explicit boolean
and falling back to negation-aware matching that is clause-scoped — an early fix using a fixed
four-word window wrongly negated `"no mutation, then later edited"`, so the window now stops at
clause boundaries.

This one was found by the adversarial trap suite rather than by reading the code, which is the
argument for [`experiments/traps/`](../experiments/traps/) existing.

### Bug 3 — the timeout asymmetry (safety, fail-open)

Described in §3. Found by reading the hook specification closely enough to notice that the
failure semantics differ between crash and timeout.

### What they have in common

Two of the three were **fail-open** bugs in **safety** paths, and they were invisible to ordinary
testing because the gate returned a confident, well-formed, wrong answer. A gate that fails
loudly is a nuisance; a gate that fails silently is worse than no gate, because it is trusted.

This is why the repo ships traps and a decision log rather than only unit tests.

---

## 5. What is actually proven

Stated plainly, because the temptation to overclaim here is strong.

**Proven:**

- 16 gates run offline, deterministically, with no API key. 87 tests, 10 traps, all passing.
- **The enforcement layer genuinely enforces.** Verified by controlled A/B against Copilot CLI
  1.0.89-0: the same benign shell command wrote its marker file (6 bytes) with no plugin loaded,
  and wrote nothing (0 bytes) with a `preToolUse` deny hook installed, the CLI reporting
  `Denied by preToolUse hook`. `${PLUGIN_ROOT}` expands inside `args`, so this repo's `hooks.json`
  loads as written. An earlier single-ended version of this test was discarded as worthless: the
  command was blocked by Copilot's *own* built-in safety, so the null result proved nothing about
  our hook. The control is what makes the claim.
- The enforcement path works end to end: a tool call reaches a hook, routes to a gate, and the
  verdict becomes an `allow` / `ask` / `deny` decision Copilot CLI honours.
- Hard rules work without the network. The Slack trap denies with `source=policy` and **zero Jev
  calls** — verified by assertion, not inspection.
- All four hooks exit 0 on malformed input, so a broken payload cannot deny every tool call.
- `modifiedArgs` works: an unbounded `view` of a large file is rewritten to a bounded range, using
  a local `stat` rather than a network round trip.
- The telemetry baseline is real, reproducible from the queries in `telemetry/`, and
  aggregate-only by construction — enforced by an allowlist and a test.

**Not proven:**

- **No gate has ever called live Jev.** `TYPESAFE_API_KEY` was unavailable. Every result in this
  repo is `fixture` or `policy`, and every artifact says which. Nothing here demonstrates that
  Jev's judgement is good — only that the machinery around it is correct.
- **Thresholds are reasoned, not calibrated.** They come from telemetry and argument, not from
  observed outcomes. [`ci-loop/`](../ci-loop/) is the machinery for fixing that, and it has no
  live data in it.
- **Aggregate latency is now measured, and the answer is *mixed*.** See
  [`experiments/latency/RESULTS.md`](../experiments/latency/RESULTS.md). End-to-end hook cost is
  **40 ms** for an ungated cheap tool and **86 ms** for a full fixture-mode gate — far below the
  300–500 ms this document previously assumed. Python interpreter startup (**43.3 ms**) dominates,
  not the gate logic; local hard rules cost **0.1 ms**. Modelled against the real telemetry, the
  current matcher costs **196 s over 30 days (3.3 s/session)**, repaid by 22 prevented duplicate
  `bash` calls or 2 avoided `task` calls. But the break-even is brutal for cheap tools: gating
  `edit` would require being right **171%** of the time against a live 400 ms scorer — i.e. it can
  never pay. **Gate expensive and failure-prone tools; never gate cheap ones.**
- **Live Jev latency is still unmeasured**, because there is no API key. The 400 ms used in the
  break-even model is an assumption, not a measurement, and live numbers will be worse than the
  fixture numbers above.
- **`${PLUGIN_ROOT}` expansion inside `args` is now verified**, so the hooks do load. See §3.
- One-machine, one-developer telemetry. The *shape* of the findings should generalise; the
  specific percentages should not be assumed to.

---

## 6. What would falsify this

The honest failure modes, in order of likelihood:

1. **Gate overhead exceeds gate savings.** **Partly confirmed, and now bounded.** Measurement
   shows this is real for cheap tools — gating `edit` can never pay — and false for expensive ones,
   where a single avoided `task` repays a month of overhead. The mitigation (route only expensive
   tools, resolve hard rules locally) is load-bearing rather than precautionary: widening the
   matcher to all tools costs 37% more overhead for no additional savings.
2. **Jev's calibration does not transfer.** Scores tuned on other decision types may cluster near
   the thresholds, making gates either permissive or obstructive. Detectable only with live data.
   **This is now the single largest unknown.**
3. **False denials train users to disable it.** A safety gate that blocks legitimate work twice
   gets uninstalled, which is strictly worse than never shipping it. This is why cost gates fail
   open and fixture-backed blocks degrade to `ask`.
4. **The telemetry was idiosyncratic.** If the 13.5:1 autonomous turn ratio is peculiar to this
   machine's workload, the ranking shifts.

## 7. The measurements that would settle it

In priority order:

1. **Live Jev, one gate, one session.** `tool-worth-it` against real calls, logging score
   distribution. Answers whether calibration transfers. **Now the top priority**, since the
   latency question below is largely answered.
2. **Latency A/B with live Jev.** The offline half is done
   ([`experiments/latency/`](../experiments/latency/)); what remains is substituting a real
   network round trip for the assumed 400 ms.
3. **Trap replay against live Jev.** All 10 traps with `source=live`. Answers whether Jev catches
   what the fixtures assume it catches.
4. **Decision-log precision over ~100 live decisions.** `ci-loop/score_decisions.py` already
   suppresses aggregates below threshold; it needs rows.

Until at least (1) exists, the correct description of this repository is: *a
telemetry-grounded, enforcement-verified, latency-measured gate library whose judgement layer has
never been switched on.*

---

## 8. What transfers regardless

Even if Jev proves to be the wrong scorer, three findings outlive it:

- **The telemetry method.** Mining an agent's own session store to rank its waste is cheap,
  repeatable, and produced results that contradicted intuition twice.
- **The hook API as a control plane**, including its sharp edges — the timeout asymmetry, the
  single-JSON-object stdout contract, the PascalCase tool-name remapping that silently matches
  nothing. Documented in [`copilot-hook-api.md`](copilot-hook-api.md) because they are not
  obvious from the reference and each one fails open.
- **Automatic decision logging.** The reference project asked the agent to log its own decisions.
  The decisions least likely to be logged are the ones made while the agent is misbehaving —
  exactly the ones worth studying. Hooks remove the agent's ability to forget.

The gate library is an argument about where an agent's cost, risk and quality actually live. That
argument is grounded in measurement, and it is testable. Switching Jev on is the next step, not
the foundation.
