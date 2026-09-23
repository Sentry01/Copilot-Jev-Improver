# The gate library

15 decision gates that sit in front of Copilot CLI actions and ask Jev a small,
calibrated question before an expensive or irreversible thing happens.

Start with **[INDEX.md](INDEX.md)** for the full table of gates, thresholds,
fail modes and Jev questions. It is generated from the configs, so it is always
current.

## What a gate is

A gate is not a rule engine and not a linter. It is a narrow question asked at a
decision point where the model is about to commit to something, plus a threshold
that turns the answer into an action.

Each gate is a directory:

```
gates/<slug>/
├── SPEC.md             purpose, when to call, state schema, thresholds, fail mode
├── config.json         the Jev question map and the thresholds in force
├── gate.py             state -> decision; importable as decide(state)
├── example_state.json  a realistic input
├── fixtures/           a recorded Jev answer, so the gate runs offline
└── dry/                a captured request/response artifact, auth stripped
```

Run any gate with no API key:

```bash
JEV_MODE=fixture python3 -B gates/tool-worth-it/gate.py
```

Run all 15:

```bash
for d in gates/*/; do s=$(basename "$d"); [ "$s" = common ] && continue
  JEV_MODE=fixture python3 -B "gates/$s/gate.py"
done
```

## The three design rules

**1. Hard rules resolve before Jev is called.**

Some things are not judgement calls. A read-only integration is never writable;
a third identical retry is never worth trying; spawning a subagent into a dirty
shared tree is never safe. These are evaluated locally and return
`source=policy` with zero Jev calls.

This started as a latency optimisation. It became a security property: a
`preToolUse` hook **timeout is fail-open**, even for safety gates, so any
decision that depends on the network can be bypassed by making the network slow.
A local decision cannot time out. See
[`docs/copilot-hook-api.md`](../docs/copilot-hook-api.md).

**2. Safety gates fail closed; cost gates fail open.**

If Jev is unreachable or answers unusably, a safety gate refuses and a cost gate
allows. The asymmetry is deliberate: the cost of wrongly blocking a cheap action
is an annoyed user, and the cost of wrongly allowing a destructive one is lost
work. `tests/test_repo_hygiene.py` asserts that no safety gate can proceed on
error.

**3. Every decision is labelled with its source.**

`live` is a real Jev answer. `fixture` is a recorded one — enough to prove
plumbing, not enough to prove judgement. `policy` is a deterministic local rule.

A fixture-backed *block* is downgraded to `ask` rather than `deny`, because
denying on a replayed answer claims more confidence than we have. Interactively
a human adjudicates; under a cloud agent `ask` is treated as `deny`, so it still
fails safe.

## Where the gates came from

The ranking is in [`docs/cool-use-cases.md`](../docs/cool-use-cases.md), and it
is grounded in measured telemetry from real Copilot CLI sessions rather than in
judgement about what *sounds* wasteful. A few of the numbers that drove it:

| Signal | Measured |
|---|---|
| Autonomous turns per user turn | 13.5 |
| `claude-opus-5 @ high` share of AI Units | 50.3% |
| Cheapest tier vs dominant tier | ~60× |
| Input:output token ratio | 260.8:1 |
| `bash` calls doing a built-in's job | 40.3% |
| `browser_click` failure rate | 78.6% |

The last one is why `retry-worth-it` exists. The 260.8:1 ratio is why the cost
gates target *context* rather than generation.

One notable negative result: the cache hit rate was already **94.4%**, so prompt
shaping was ruled out as a lever. It is not in the library.

## Verifying

```bash
JEV_MODE=fixture python3 -m unittest discover -s tests   # 73 tests
python3 -B experiments/traps/run_traps.py                # 9 traps
python3 gates/build_index.py                             # regenerate INDEX.md
```

Regenerate `INDEX.md` after changing any `config.json`, or it will drift.

## What is not proven

No gate has run against live Jev — `TYPESAFE_API_KEY` was unavailable, so every
result in this repo is `fixture` or `policy`. Thresholds are reasoned from
telemetry, not validated against outcomes; [`ci-loop/`](../ci-loop/) is the
machinery for validating them. Aggregate gate latency is unmeasured, and is the
main risk to the approach being net-positive.
