# The continuous improvement loop

A gate library is a set of guesses until you measure it. This directory holds
the machinery for finding out whether the gates are actually right.

The honest framing: **none of the thresholds in `gates/` are validated.** They
were chosen from the telemetry baseline and from judgement about where the
failure modes sit. This loop is how they stop being guesses.

## Flow

1. **Log** — the harness appends one JSON line per gate decision to
   `logs/decisions.jsonl`, automatically.
2. **Judge** — decisions get an `outcome_later` verdict once the consequence is
   known: was the block right, was the allow right.
3. **Score** — `score_decisions.py` turns the log into per-gate precision,
   suppressing any gate with too few judgements to speak about.
4. **Propose** — threshold or question-map changes go in `proposals/`, with the
   evidence that motivated them.
5. **Regress** — re-run the trap suite into `baselines/` so a threshold change
   that fixes one case and breaks another is visible.
6. **Apply** — small nudges (±0.05) can apply with a note; anything larger is a
   human decision.

## Logging is automatic, and that is the point

The reference implementation this repo is modelled on required the agent to
remember to log its own gate decisions. That has a structural flaw: the
decisions least likely to be recorded are the ones made when the agent is
already behaving badly — which are exactly the ones worth studying.

Because Copilot CLI exposes real hooks, the harness logs from the enforcement
point itself. The agent cannot forget, and cannot decline.

Enable it:

```bash
export COPILOT_JEV_LOG_DECISIONS=1
```

It is **off by default**, deliberately: a decision log is local telemetry about
real work, and turning that on should be a choice.

## Privacy

`logs/decisions.jsonl` is **gitignored and never published.** It records gate
signals and tool names from real sessions.

Only the aggregates from `score_decisions.py` are publishable, and it applies
the same floor as the telemetry baseline: a precision computed from three
judgements is not a precision, so it is suppressed rather than printed.

## Usage

```bash
# What have the gates been doing?
python3 ci-loop/score_decisions.py

# Machine-readable, for a report
python3 ci-loop/score_decisions.py --json

# Log a decision by hand (e.g. attaching a verdict)
echo '{"gate":"tool-worth-it","action":"skip_tool","proceed":false,
       "source":"live","outcome_later":"good_skip"}' | python3 ci-loop/log_decision.py
```

## Decision log schema

One JSON object per line:

```json
{
  "ts": "ISO-8601",
  "gate": "tool-worth-it",
  "tool": "bash",
  "action": "skip_tool",
  "proceed": false,
  "source": "live | fixture | policy",
  "permission_decision": "allow | deny | ask",
  "signals": {},
  "outcome_later": null
}
```

`source` is mandatory and is not cosmetic. A `fixture` decision is a replayed
answer; scoring it as though it were live evidence would corrupt the loop with
its own assumptions. `score_decisions.py` says so explicitly when a report
contains no live rows.

`outcome_later` is one of `good_skip`, `bad_skip`, `good_hold`, `bad_hold`,
`good_allow`, `bad_allow`, or `null` when the consequence is not yet known.

## What this loop cannot tell you yet

- **Nothing live has run.** `TYPESAFE_API_KEY` was unavailable, so every
  decision recorded so far is `fixture` or `policy`.
- **Gate latency is unmeasured in aggregate.** Individual gates are ~300–500ms
  in fixture mode. Whether the gates are net-positive on wall-clock time across
  a whole session is the central open question, and this loop does not answer
  it yet. That measurement should come before any claim that the gates help.
