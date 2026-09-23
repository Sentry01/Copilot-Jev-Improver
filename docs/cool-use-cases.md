# Copilot × Jev — Ranked Use Cases

**As-of:** 2026-09-23 (Australia/Sydney)
**Scope:** GitHub Copilot CLI agent-ops only
**Evidence:** [`telemetry/reports/baseline-2026-09-23.md`](../telemetry/reports/baseline-2026-09-23.md)
**Sibling:** [`Sentry01/grokbot-improver`](https://github.com/Sentry01/grokbot-improver) — same method, different agent

This is the source of truth for every gate's state schema and Jev question map.
`gates/<slug>/config.json` must match the question map recorded here.

---

## What Jev is good for here

Jev (TypeSafe System One, `jev-latest`) is a **calibrated decision layer, not a writer**.
Copilot still drafts, edits, and explains. Jev gates, ranks, and routes.

| Type | Shape | Returns |
| --- | --- | --- |
| `noul` | 0–1 calibrated belief | `{type, noul}` |
| `score` | ordered criteria array | `{type, score, confidence, legend, probabilities}` |
| `choice` | criteria map, label → description | `{type, choice, confidence, probabilities}` |

Why this beats asking the model to judge itself:

- **Calibration** — a stable number you can threshold on, rather than a mood.
- **Speed and cost** — a few hundred milliseconds, cheap enough to gate every expensive call.
- **Typed** — no parse failures, so software can branch without retries.
- **Constrained** — Jev cannot invent a tool name or an action. Choices are a closed set.
- **Independent** — the thing being judged is not also the judge.

**Do not** use Jev for prose, code, or explanations. Gates only.

---

## The ranking, and how it was derived

Rank is `measured waste × tractability`. Every claim below cites the baseline.

The four numbers that shaped this list:

1. **13.5 autonomous model requests per user request** (6,396 agent vs 473 user).
   Most of the bill is the agent talking to itself → loop and tool gates rank high.
2. **`claude-opus-5 @ high` is 50.3% of all AI Units**, and `gpt-6-astra @ xhigh` costs
   **42.67 AIU/req vs 19.52** for opus-5 high → routing is the single biggest lever.
3. **Spend is Pareto-distributed**: the top session is ~25% of all AI Units, the top 15 are 78%
   → terminating runaway sessions matters more than shaving average turns.
4. **Cache is already 94.4%** and input:output is **260.8:1** → prompt shaping is a dead end.
   The win is avoiding turns and tool calls, not compressing them.

### Cut list

| Rank | Gate | Lever | Difficulty | Evidence |
| ---: | --- | --- | --- | --- |
| 1 | [`model-effort-route`](#1-model-effort-route) | cost | M | One model/effort pair = 50.3% of AIU; 2.2× spread in AIU/req |
| 2 | [`stop-vs-continue`](#2-stop-vs-continue) | cost, performance | S | 13.5 agent turns per user turn; top session ~25% of spend |
| 3 | [`tool-worth-it`](#3-tool-worth-it) | cost, performance | S | 2,060 bash calls at 9.1 s average = 5.0 h wall-clock |
| 4 | [`context-read-budget`](#4-context-read-budget) | cost | S | 40.3% of bash calls do a built-in tool's job; 260.8:1 input:output |
| 5 | [`redundant-tool-call`](#5-redundant-tool-call) | cost | S | 253+ byte-identical repeat calls in-session |
| 6 | [`verification-sufficient`](#6-verification-sufficient) | quality | M | Completion claims are the dominant self-reported failure |
| 7 | [`destructive-action`](#7-destructive-action) | safety | S | A subagent's cleanup destroyed uncommitted work in this repo's own history |
| 8 | [`subagent-spawn`](#8-subagent-spawn) | cost | S | 9.2% of AIU in delegated lanes; `task` averages 174 s |
| 9 | [`retry-worth-it`](#9-retry-worth-it) | performance | S | `browser_click` 78.6% failure, `browser_navigate` 59.6% |
| 10 | [`secret-exposure`](#10-secret-exposure) | safety | M | Keys in env across Kusto, Slack, Salesforce, TypeSafe |
| 11 | [`plan-vs-act`](#11-plan-vs-act) | quality | M | Plan mode is policy but unevenly applied |
| 12 | [`external-write`](#12-external-write) | safety | S | PR/issue/message tools present; standing read-only rule for M365 and Slack |
| 13 | [`response-quality`](#13-response-quality) | quality | S | Ported from grokbot, where it was the #2 gate |
| 14 | [`skill-selection`](#14-skill-selection) | quality | M | 65+ skills installed; `skill` invoked 17 times in 30 days |
| 15 | [`parallel-fanout`](#15-parallel-fanout) | performance | M | Batching is instructed but hard to self-assess |

**Prototype first: `model-effort-route`.** Biggest measured lever, needs only state already on
the turn, and it is reversible — a bad route costs one turn, not a broken repo.

Ranked but **not built** in this pass: see [honourable mentions](#honourable-mentions-16-18).

---

## Gate specifications

Each gate below gives: the failure mode, the telemetry that justifies it, the state Copilot must
supply, the Jev question map, thresholds, and fail mode.

**Fail mode convention.** *Fail-open* means an API error lets the action proceed — correct when
the gate saves money but blocking would stall real work. *Fail-closed* means an API error blocks
— correct when the action is irreversible or externally visible. When in doubt on a safety gate,
fail closed.

---

### 1. model-effort-route

**Lever:** cost · **Difficulty:** M · **Fail mode:** open

**Failure mode.** Every turn runs at whatever model and reasoning effort the session was started
with. A one-line file read and a cross-cutting refactor cost the same. There is no moment where
anything asks "does this turn actually need the expensive tier?"

**Evidence.** `claude-opus-5 @ high` accounts for **50.3%** of all AI Units across 3,861 requests
at 19.52 AIU/req. `gpt-6-astra @ xhigh` costs **42.67 AIU/req** — 2.2× — across 561 requests.
Meanwhile `gpt-5.6-luna @ medium` serves 127 requests at **0.33 AIU/req**, roughly 60× cheaper
than opus-5 high. The spread across tiers is enormous and currently unmanaged.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `user_request` | string | What was asked this turn |
| `turn_kind` | string | `question` / `edit` / `refactor` / `debug` / `research` / `review` |
| `blast_radius` | string | `read_only` / `single_file` / `multi_file` / `cross_cutting` |
| `context_size_tier` | string | `small` / `medium` / `large` |
| `prior_attempts` | integer | Failed attempts so far this turn |
| `current_tier` | string | Model and effort currently selected |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `needs_frontier_model` | `noul` | Belief that a cheaper tier would produce a materially worse result |
| `reasoning_depth` | `score` | Ordered: `trivial`, `shallow`, `moderate`, `deep`, `exhaustive` |
| `recommended_tier` | `choice` | `cheap_fast`, `mid`, `frontier_medium`, `frontier_high`, `frontier_xhigh` |

**Thresholds.** Downgrade when `needs_frontier_model < 0.45` **and** `reasoning_depth ≤ shallow`.
Escalate above the session default only when `needs_frontier_model ≥ 0.8` **and**
`reasoning_depth ≥ deep`. Otherwise keep the current tier — the default is "change nothing".

**Expected win.** Largest single cost lever available. Even moving the cheapest third of turns
down one tier is a double-digit percentage of the bill.

**Caveat.** Downgrade errors are not free: a too-cheap tier that fails and retries costs more
than routing correctly. Hence the deliberately conservative asymmetric thresholds, and hence
`prior_attempts` in the state — after a failure, stop downgrading.

---

### 2. stop-vs-continue

**Lever:** cost, performance · **Difficulty:** S · **Fail mode:** open

**Failure mode.** The agent keeps going: another search, another file, one more confirmation.
Each step is individually defensible and collectively enormous. Nothing computes marginal value.

**Evidence.** **6,396 agent-initiated requests vs 473 user-initiated** — 13.5 autonomous
requests per human turn. The single most expensive session consumed **24.8% of all AI Units**
(951 requests); the top 15 sessions account for **77.9%**. This is not a broad average problem,
it is a runaway-session problem, which is exactly what a stop gate addresses.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `user_goal` | string | Original ask |
| `progress_summary` | string | What is established so far |
| `open_questions` | string | What genuinely remains |
| `steps_taken` | integer | Tool calls this turn |
| `last_step_yield` | string | What the most recent step actually added |
| `budget_tier` | string | `low` / `normal` / `high` |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `should_stop` | `noul` | Belief that continuing adds little |
| `marginal_value` | `score` | Ordered: `none`, `trivial`, `modest`, `substantial`, `critical` |
| `stop_reason` | `choice` | `goal_met`, `diminishing_returns`, `blocked_needs_user`, `wrong_approach`, `keep_going` |

**Thresholds.** Stop if `should_stop ≥ 0.6` **or** `marginal_value < modest`.
`stop_reason = wrong_approach` should trigger a re-plan rather than a silent stop — stopping on a
wrong approach without saying so is how a task gets silently abandoned.

**Expected win.** Directly targets the Pareto tail. Caps the runaway session rather than shaving
the average one.

---

### 3. tool-worth-it

**Lever:** cost, performance · **Difficulty:** S · **Fail mode:** open

**Failure mode.** Expensive tools fire speculatively — a Kusto query, a web fetch, a browser
session, an MCP round trip — when the answer is already in hand or a cheaper instrument would do.

**Evidence.** `bash` ran **2,060 times averaging 9.1 s**, totalling **5.0 hours** of wall clock.
`kusto_query_readonly` ran 152 times at 8.7 s with a **13.2% failure rate**. `web_search`
averaged **39 s** per call. These are the calls worth a 400 ms gate.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `user_goal` | string | What the user wants |
| `already_have` | string | Evidence already gathered this turn |
| `proposed_tool` | string | Tool name and intent |
| `est_cost_tier` | string | `low` / `medium` / `high` |
| `est_latency_ms` | integer | Expected duration, from the latency profile |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `tool_worth_it` | `noul` | Belief the call materially improves the answer |
| `primary_blocker` | `choice` | `already_answered`, `wrong_tool`, `low_signal`, `user_not_needed`, `none` |

**Thresholds.** Run if `tool_worth_it ≥ 0.65`. Otherwise skip and log the blocker.

**Do not gate cheap tools.** A gate costs ~86 ms end-to-end in fixture mode (measured — see
[`experiments/latency/RESULTS.md`](../experiments/latency/RESULTS.md)), plus live Jev network time
on top, assumed ~300–500 ms. Against a live 400 ms scorer, gating `view` (908 ms average) needs to
be right 48% of the time and `edit` (256 ms) needs **171%** — i.e. `edit` can never pay. Apply this
gate only where `est_latency_ms ≥ 2000` or `est_cost_tier ≠ low`. The harness enforces this.

---

### 4. context-read-budget

**Lever:** cost · **Difficulty:** S · **Fail mode:** open

**Failure mode.** Reading far more than needed. Whole files when a range would do; `grep -r`
through a repo and piping it all back; shelling out to `cat` instead of a bounded read. Every
token lands in context and is re-sent on every subsequent request in the session.

**Evidence.** Of 2,060 bash calls, **831 (40.3%)** were doing a purpose-built tool's job:
**747 search**, 44 list, 40 file reads. Copilot CLI ships `grep`, `glob` and `view` with bounded
output and instructs the agent to prefer them; the built-ins were used far less
(`view` 372, `rg` 19, `glob` 18). The cost shape confirms the impact: input:output is
**260.8:1**, so reading is essentially the entire bill.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `goal` | string | What we need from the file or tree |
| `target` | string | Path pattern or search scope |
| `known_size_tier` | string | `small` / `medium` / `large` / `unknown` |
| `proposed_read` | string | e.g. `full_file`, `range`, `recursive_grep` |
| `already_read` | string | What is already in context |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `full_read_justified` | `noul` | Belief the whole thing is genuinely needed |
| `read_strategy` | `choice` | `targeted_search`, `ranged_read`, `full_read`, `already_have_it` |
| `expected_relevance` | `score` | Ordered: `none`, `low`, `moderate`, `high`, `certain` |

**Thresholds.** Allow a full read only if `full_read_justified ≥ 0.7`. Otherwise follow
`read_strategy`. On `already_have_it`, skip entirely.

**Expected win.** Compounding. A wasted 40 KB read is paid on that request *and* every later
request in the session, which is precisely why a 94.4% cache rate has not made this free.

---

### 5. redundant-tool-call

**Lever:** cost · **Difficulty:** S · **Fail mode:** open

**Failure mode.** Calling something already called with the same arguments — re-reading a file
already in context, re-running a status command, re-fetching a page.

**Evidence.** Grouping by `(session_id, tool_name, arguments_json)`, **253+ calls in 30 days were
byte-identical repeats** within a single session: 77 `bash`, 46 `view`, 26 `browser_snapshot`,
13 `create`, 12 `edit`. Every one had its answer already in context. This is the least arguable
waste class in the dataset — no judgment needed, the arguments are identical.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `proposed_call` | string | Tool and arguments summary |
| `prior_calls` | string | Comparable earlier calls this session |
| `elapsed_since_prior` | string | How stale the prior result is |
| `volatility` | string | `static` / `slow` / `volatile` — is the underlying thing likely to have changed? |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `is_redundant` | `noul` | Belief we already hold this answer |
| `reuse_strategy` | `choice` | `reuse_cache`, `narrow_scope`, `call_anyway_stale`, `call_anyway_new` |

**Thresholds.** Skip or reuse if `is_redundant ≥ 0.65`.

**Caveat.** `volatility` carries this gate. Re-running `git status` after an edit is *not*
redundant even though the arguments match. Identical arguments plus a mutation in between means
the call is legitimate — which is why the state includes what changed, not just what was called.

---

### 6. verification-sufficient

**Lever:** quality · **Difficulty:** M · **Fail mode:** **closed**

**Failure mode.** Declaring work done without proving it. Tests not run, build not checked,
the changed path never exercised. The agent's own instructions say a task is not complete until
the outcome is verified — this gate makes that testable instead of aspirational.

**Evidence.** This is a quality failure rather than a spend failure, so it does not show up as
an AIU line. Its cost shows up as rework, and the strongest evidence is local: this very session
shipped an apparent bug fix to an auth header that was never a bug, based on redacted display
output. The check that caught it was reading the bytes — verification, not assertion.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `claimed_outcome` | string | What we are about to claim is done |
| `changes_made` | string | Files and behaviours touched |
| `verification_performed` | string | Commands actually run, and their results |
| `test_coverage` | string | Whether changed paths are exercised |
| `reversibility` | string | `trivial` / `moderate` / `hard` to undo |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `outcome_verified` | `noul` | Belief the evidence actually supports the claim |
| `verification_gap` | `choice` | `none`, `not_executed`, `partial_coverage`, `wrong_check`, `unverifiable` |
| `confidence_in_claim` | `score` | Ordered: `speculative`, `plausible`, `likely`, `demonstrated`, `proven` |

**Thresholds.** Allow the completion claim if `outcome_verified ≥ 0.7` **and**
`confidence_in_claim ≥ demonstrated`. Otherwise keep working, or state plainly what is unverified.

**Fail closed.** If Jev is unreachable, do not emit a confident completion claim. Say what was
done and what was not checked. An unverifiable claim is worse than an honest one.

---

### 7. destructive-action

**Lever:** safety · **Difficulty:** S · **Fail mode:** **closed**

**Failure mode.** Irreversible local damage: `rm -rf`, `git clean -fd`, `git reset --hard`,
force push, history rewrite, dropping a table, killing the wrong process.

**Evidence.** This repository's own history contains the case. A subagent, told to clean up its
verification artifacts, removed the parent session's **uncommitted** `telemetry/` tree and
`.gitignore` and reverted `README.md` to `HEAD`. The work was recoverable only because it could
be rewritten. The command was reasonable in isolation; the blast radius was not checked.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `proposed_command` | string | The exact command |
| `working_tree_state` | string | Uncommitted or untracked work present? |
| `scope` | string | What the command can reach |
| `recoverable` | string | `trivially` / `from_git` / `from_backup` / `no` |
| `user_asked_for_it` | boolean | Did the user explicitly request this destructive step? |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `safe_to_execute` | `noul` | Belief this destroys nothing the user wants |
| `blast_radius` | `score` | Ordered: `none`, `scratch_only`, `recoverable`, `costly`, `catastrophic` |
| `safer_alternative` | `choice` | `none_needed`, `narrow_scope`, `commit_first`, `dry_run_first`, `ask_user` |

**Thresholds.** Execute only if `safe_to_execute ≥ 0.8` **and** `blast_radius ≤ recoverable`.
Otherwise take `safer_alternative`. `commit_first` would have prevented the incident above.

**Fail closed.** No Jev, no destructive command. Ask instead.

---

### 8. subagent-spawn

**Lever:** cost · **Difficulty:** S · **Fail mode:** open

**Failure mode.** Delegating work that should stay inline. A subagent re-reads context the parent
already has, and a factory or fleet run multiplies that across many agents at once.

**Evidence.** **9.2% of AI Units** ran in delegated lanes. `task` calls averaged **174 s** each.
Delegation is also the highest-variance decision available: `run_factory` can spawn dozens of
agents from one call. And delegation is not only a cost risk — the destructive-action incident in
gate 7 *was* a subagent.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `task_description` | string | What would be delegated |
| `context_transfer_size` | string | How much context the child needs |
| `parent_can_do_inline` | string | Honest assessment |
| `parallelism_benefit` | string | Genuinely independent work? |
| `spawn_kind` | string | `subagent` / `background_agent` / `factory_fleet` |
| `writes_to_shared_tree` | boolean | Can the child mutate the parent's working tree? |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `spawn_justified` | `noul` | Belief delegation beats inline |
| `spawn_reason` | `choice` | `context_isolation`, `true_parallelism`, `specialised_skill`, `underspecified`, `should_inline` |
| `expected_multiplier` | `score` | Ordered: `1x`, `2x`, `5x`, `10x`, `20x_plus` |

**Thresholds.** Spawn if `spawn_justified ≥ 0.65` **and** `spawn_reason ≠ underspecified`.
For `factory_fleet`, additionally require `expected_multiplier` to be justified by the task —
this is the one gate where a single wrong answer is very expensive.

**Extra rule.** If `writes_to_shared_tree` is true, require a clean or committed tree first.
Learned the hard way; see gate 7.

---

### 9. retry-worth-it

**Lever:** performance · **Difficulty:** S · **Fail mode:** open

**Failure mode.** Retrying something that structurally cannot succeed. The classic loop is a
browser automation click that fails, gets retried with a slightly different selector, fails
again, and burns a dozen turns before anyone reconsiders the approach.

**Evidence.** The clearest reliability signal in the dataset.
**`browser_click` failed 22 of 28 times (78.6%)**, `browser_navigate` **31 of 52 (59.6%)**,
`browser_type` **3 of 5 (60%)**. Also `kusto_query_readonly` 13.2%, `kusto_mgmt_show` 18.5%,
`open_canvas` 16.2%. These tools are not coin flips — they fail for structural reasons
(wrong selector, missing auth, unsupported surface) that a retry does not fix.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `failed_tool` | string | What failed |
| `error_summary` | string | The error returned |
| `attempt_number` | integer | How many tries so far |
| `change_since_last_attempt` | string | What is actually different this time |
| `tool_historical_failure_rate` | number | From the telemetry baseline |
| `alternative_paths` | string | Other ways to get the same result |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `retry_will_succeed` | `noul` | Belief this attempt differs enough to work |
| `failure_class` | `choice` | `transient`, `auth`, `wrong_target`, `unsupported`, `malformed_input` |
| `next_action` | `choice` | `retry_same`, `retry_adjusted`, `switch_tool`, `ask_user`, `abandon` |

**Thresholds.** Retry if `retry_will_succeed ≥ 0.55` **and** `change_since_last_attempt` is
non-empty. Never `retry_same` on `failure_class ∈ {auth, unsupported}` — those need a different
path, not another go. Hard-stop at `attempt_number ≥ 3` regardless of score.

**Expected win.** Pure latency and turn count. At a 78.6% failure rate, the expected value of a
blind retry is negative, and the gate is far cheaper than the retry it prevents.

---

### 10. secret-exposure

**Lever:** safety · **Difficulty:** M · **Fail mode:** **closed**

**Failure mode.** A credential leaves the machine or lands somewhere durable — committed to
source, echoed into a log, pasted into an artifact, or sent to a third party.

**Evidence.** This environment holds credentials for Kusto, Salesforce, Slack, Microsoft Graph,
Seismic, and TypeSafe. The repo is public. The session store contains customer data. The
telemetry pipeline here needed an enforced allowlist precisely because "be careful" is not a
control — and this session also demonstrated the inverse failure, where redacted *display* output
made correct code look like a leak.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `proposed_output` | string | What is about to be written, printed or sent |
| `destination` | string | `commit` / `log` / `artifact` / `third_party` / `user_visible` |
| `contains_env_reference` | boolean | Does it interpolate environment values? |
| `repo_visibility` | string | `public` / `private` / `internal` |
| `data_classification` | string | `public` / `internal` / `customer` / `credential` |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `safe_to_emit` | `noul` | Belief nothing sensitive escapes |
| `exposure_kind` | `choice` | `none`, `credential`, `customer_data`, `personal_data`, `internal_only` |
| `severity` | `score` | Ordered: `none`, `low`, `moderate`, `high`, `critical` |

**Thresholds.** Emit only if `safe_to_emit ≥ 0.85` **and** `exposure_kind = none`. This bar is
deliberately the highest in the library: the asymmetry between a held-back message and a leaked
key is not close.

**Fail closed.** Always. A gate that fails open on secrets is not a gate.

**This is a second line of defence**, not the first. Deterministic checks — allowlists, ignore
rules, scanners — run first because they are exact. Jev catches what patterns miss.

---

### 11. plan-vs-act

**Lever:** quality · **Difficulty:** M · **Fail mode:** open

**Failure mode.** Two symmetric errors: diving into a sprawling task without a plan and thrashing,
or ceremonially planning a one-line fix. Standing policy says plan for anything non-trivial, but
"non-trivial" is judged inconsistently turn to turn.

**Evidence.** The cost shape argues both ways, which is why this needs calibration rather than a
rule. Unplanned sprawl shows up in the 13.5:1 autonomous-turn ratio and the Pareto tail. But
planning is not free either — it is turns, and the fast path exists for a reason.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `user_request` | string | The ask |
| `estimated_steps` | integer | Rough step count |
| `files_likely_touched` | integer | Rough breadth |
| `ambiguity` | string | What is genuinely unclear |
| `reversibility` | string | `trivial` / `moderate` / `hard` |
| `user_specified_mode` | string | Did the user ask to plan, or to just do it? |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `needs_plan` | `noul` | Belief that planning first improves the outcome |
| `ambiguity_level` | `score` | Ordered: `none`, `minor`, `moderate`, `high`, `blocking` |
| `recommended_mode` | `choice` | `act_now`, `quick_outline`, `full_plan`, `ask_clarifying_first` |

**Thresholds.** Plan if `needs_plan ≥ 0.6` **or** `ambiguity_level ≥ high`.
`ask_clarifying_first` wins over `full_plan` when ambiguity is `blocking` — planning on top of a
misunderstood requirement just produces a confident wrong plan.

**Override.** `user_specified_mode` always wins. If the user said just do it, do it.

---

### 12. external-write

**Lever:** safety · **Difficulty:** S · **Fail mode:** **closed**

**Failure mode.** Something leaves the machine and reaches another person: a PR, an issue, a
review comment, a Slack message, an email, a calendar invite. These are visible, attributed, and
awkward to retract.

**Evidence.** The toolset exposes plenty of these paths, and this operator carries a **standing
read-only rule for Microsoft 365 and Slack** — WorkIQ and Slack integrations must never send on
the user's behalf. A rule that exists only in a prompt is worth encoding as a gate.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `action` | string | e.g. `create_pull_request`, `send_message`, `create_issue` |
| `destination` | string | Who or what receives it |
| `content_summary` | string | What it says |
| `user_authorised` | boolean | Did the user explicitly request this send? |
| `channel_policy` | string | `read_only` / `write_allowed` |
| `reversible` | string | `editable` / `deletable` / `permanent` |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `safe_to_send` | `noul` | Belief this is authorised, correct, and wanted |
| `authorisation_basis` | `choice` | `explicit_request`, `standing_policy`, `inferred`, `none` |
| `audience_risk` | `score` | Ordered: `self`, `team`, `org`, `customer`, `public` |

**Thresholds.** Send only if `safe_to_send ≥ 0.75` **and**
`authorisation_basis ∈ {explicit_request, standing_policy}`. `inferred` is never sufficient for
an external write.

**Hard rule, not a threshold.** If `channel_policy = read_only`, block unconditionally and do not
call Jev at all. A calibrated score must not be able to talk its way past a standing policy.

---

### 13. response-quality

**Lever:** quality · **Difficulty:** S · **Fail mode:** closed for external, open for chat

**Failure mode.** Replying with something vague, incomplete, or unsupported — hedging instead of
answering, or asserting facts no tool established.

**Evidence.** Ported from grokbot-improver, where this was the #2 gate. Its calibration history
is the useful part: the original `ready_to_send ≥ 0.7` bar **false-held good sourced answers**
(their "Trap D"), and was corrected to **0.65** after measurement, with an `evidence_sources`
field added so sourced claims stopped being scored `unsupported`. We adopt the corrected design
rather than repeating the mistake.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `user_request` | string | What was asked |
| `draft` | string | The proposed reply |
| `success_criteria` | string | What a good answer must contain |
| `evidence_sources` | array | `[{tool, claim, excerpt}]` — supply this whenever claims came from tools |
| `unresolved` | string | Anything knowingly unanswered |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `ready_to_send` | `noul` | Belief the draft answers the ask |
| `send_quality` | `score` | Ordered: `unusable`, `weak`, `adequate`, `good`, `excellent` |
| `main_defect` | `choice` | `none`, `incomplete`, `vague`, `unsupported`, `off_target`, `too_long` |

**Thresholds.** Send if `ready_to_send ≥ 0.65` **and** `send_quality ≥ adequate`.
**Do not lower 0.65** without re-running the trap suite.

**Always pass `evidence_sources`** when material claims came from tools. Omitting it is the known
cause of false holds.

---

### 14. skill-selection

**Lever:** quality · **Difficulty:** M · **Fail mode:** open

**Failure mode.** Two errors again: ignoring a skill that encodes hard-won process, or loading a
heavyweight skill for a task that does not need it. Skills carry real context cost.

**Evidence.** **65+ skills are installed** in this environment, and standing policy requires
checking them before any coding task. Yet `skill` was invoked only **17 times in 30 days** across
sessions that made 2,060 bash calls. Either the policy is under-applied or most turns genuinely
do not need a skill — and nothing currently distinguishes the two.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `user_request` | string | The ask |
| `candidate_skills` | array | `[{name, description}]` shortlist |
| `task_domain` | string | e.g. `code_edit`, `data_analysis`, `document`, `research` |
| `skill_context_cost` | string | `small` / `medium` / `large` |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `skill_needed` | `noul` | Belief a skill materially improves the outcome |
| `best_skill` | `choice` | Built dynamically from `candidate_skills`, plus `none` |
| `match_strength` | `score` | Ordered: `none`, `weak`, `partial`, `strong`, `exact` |

**Thresholds.** Load if `skill_needed ≥ 0.6` **and** `match_strength ≥ partial`.

**Note.** This is the only gate whose `choice` map is built at call time from the candidate
shortlist rather than fixed in `config.json`. Shortlist first by name and description; do not
send 65 options.

---

### 15. parallel-fanout

**Lever:** performance · **Difficulty:** M · **Fail mode:** open

**Failure mode.** Running independent operations one at a time when they could have gone in one
batch — or the reverse, batching calls that actually depend on each other and acting on stale
results.

**Evidence.** Standing instructions already require batching independent calls, so the remaining
problem is judging *independence*, which is exactly the kind of thing a calibrated scorer is
better at than a self-assessment. The upside is bounded by the slowest call in the batch, and the
latency profile shows how uneven those are: `bash` 9.1 s, `web_search` 39 s, `task` 174 s.

**State schema**

| Field | Type | Notes |
| --- | --- | --- |
| `proposed_calls` | array | Tools and intents in the candidate batch |
| `dependency_notes` | string | Any known ordering requirements |
| `shared_state_touched` | string | Files or resources more than one call touches |
| `est_latencies_ms` | array | Per-call expected durations |

**Question map**

| Key | Type | Role |
| --- | --- | --- |
| `independent` | `noul` | Belief no call depends on another's result |
| `max_parallel` | `score` | Ordered: `1`, `2`, `3`, `5`, `8` |
| `ordering_risk` | `choice` | `none`, `read_after_write`, `write_conflict`, `rate_limit`, `unknown` |

**Thresholds.** Parallelise if `independent ≥ 0.6` **and** `ordering_risk = none`, capped at
`max_parallel`. Any write conflict forces sequential.

---

## Honourable mentions (16–18)

Ranked, specified enough to build, deliberately **not** built in this pass.

**16. `prompt-injection`** — *safety*. Detect fetched or tool-returned content attempting to
steer the agent. Genuinely important, and the deferral is about shape rather than value: it
inspects untrusted *content* rather than a proposed *action*, so it belongs in the retrieval path
and needs its own evaluation set. Deterministic guards remain first-line meanwhile.

**17. `memory-save`** — *quality*. Decide what deserves durable memory. `store_memory` ran 31
times in 30 days, which is neither obviously too high nor too low; there is no measured failure
to point at yet, and the existing instructions already impose a strict filter.

**18. `mcp-route`** — *performance*. Choose among overlapping MCP servers. Real ambiguity exists
(WorkIQ vs Slack vs Kusto vs Salesforce for related questions), but routing skills already handle
the common cases deterministically, so this is redundant until they demonstrably fail.

---

## Harness wiring

```
user turn
  → [11] plan-vs-act
  → [14] skill-selection
  → [1]  model-effort-route
  → loop:
       → [3] tool-worth-it  /  [5] redundant-tool-call  /  [4] context-read-budget
       → [7] destructive-action     (before any irreversible local command)
       → [8] subagent-spawn         (before task / factory / fleet)
       → [15] parallel-fanout       (before a multi-call batch)
       → tool
       → [9] retry-worth-it         (on failure, before trying again)
       → [2] stop-vs-continue
  → [6]  verification-sufficient    (before claiming done)
  → [10] secret-exposure            (before any emit)
  → [13] response-quality
  → [12] external-write             (only for sends that leave the machine)
  → reply
```

**Short-circuit rules**, without which gating costs more than it saves:

- Skip all gates on trivial turns — a single bounded read, one cheap edit, a direct answer.
- Gate a tool only when `est_latency_ms ≥ 2000` or `est_cost_tier ≠ low`.
- Run `model-effort-route` at most once per user turn, not per step.
- Hard-coded policy beats a score: `channel_policy = read_only` and a hard retry cap at 3 are
  rules, not thresholds, and must not be negotiable by a calibrated number.

---

## What we are not claiming

- **Jev does not write anything.** Copilot still drafts every reply, edit and explanation.
- **Gates are not free.** ~86 ms each end-to-end in fixture mode (measured), plus live Jev network
  time. The win is avoided tool spend and avoided bad actions, not lower latency. A gate on a cheap
  call is a net loss, and on `edit` it is an unrecoverable one.
- **Thresholds here are starting points.** They are informed guesses, not measured optima.
  grokbot's send gate needed correction after real measurement; expect the same, which is what
  [`ci-loop/`](../ci-loop/) exists for.
- **The telemetry is one developer on one machine.** It is strong enough to *order* this backlog
  and far better than ordering it by intuition. It is not a population estimate.
