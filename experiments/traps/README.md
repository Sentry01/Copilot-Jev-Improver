# Copilot × Jev trap suite

A trap is a realistic Copilot CLI situation, drawn from measured telemetry, where the ungated default is wrong and a Jev gate changes the action.
It is not a unit test of one threshold: each trap names the situation, the natural ungated behavior, measured evidence, the gated outcome, and a falsifier that could prove the gate is not helping.

## Run

From the repository root:

```bash
JEV_MODE=fixture python3 -B experiments/traps/run_traps.py
```

To prove fixture mode does not need a key:

```bash
env -u TYPESAFE_API_KEY JEV_MODE=fixture python3 -B experiments/traps/run_traps.py
```

The runner reads every `experiments/traps/*/trap.json`, invokes the real gate code under `gates/<slug>/gate.py`, and prints a table.
It exits non-zero when the actual `action` or `proceed` differs from the trap's expected values.

## Reading results

- `source=fixture` means the decision used fixture answers in `trap.json`; this proves the gate's offline decision logic, **not live Jev behavior**.
- `source=policy` means a deterministic hard rule fired before Jev. For `slack-send-under-read-only`, the runner also asserts zero Jev calls.
- `source=live` appears only when run in live mode with credentials; live scores may legitimately disagree with fixtures.

## Honesty rules

1. Fixture-backed results are labelled as fixtures everywhere. They are not live evidence.
2. Savings estimates use only numbers present in `docs/cool-use-cases.md` and `telemetry/reports/baseline-2026-09-23.md`; otherwise the trap says `unmeasured`.
3. A failing trap should stay failing until the gate is improved intentionally. Do not reshape a state or threshold just to pass.
4. Safety policy beats calibration. Read-only Slack/M365 sends must block before Jev is consulted.
