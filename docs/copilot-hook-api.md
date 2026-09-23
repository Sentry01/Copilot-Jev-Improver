# The Copilot CLI hook API, as a control plane

> Status: verified against the official [hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference)
> and against this repo's own working plugin in `harness/copilot-jev-gates/`.
> Everything marked **verified in-repo** is exercised by `tests/test_harness_routing.py`.

This document exists because the project's original plan was wrong.

We assumed Copilot CLI had no programmable interception point, and that the
best a gate library could do was publish *advice* — a skill that asks the model
nicely to check with Jev before doing something expensive or dangerous. Advice
is not enforcement. A model that is already mis-routing is exactly the model
that will skip the advice.

Copilot CLI does have a real interception point. `preToolUse` hooks can **deny
a tool call outright**, before it runs. That changes what this repo is: not a
set of suggestions, but a control plane that a gate can actually sit in.

This document records the contract, and — more usefully — the four places where
the contract behaves in a way that will quietly break a naive gate.

---

## 1. The shape of the thing

A hook is an external command (or HTTPS endpoint) that the CLI runs at a
lifecycle point. It receives a JSON payload on stdin and may write a JSON
decision to stdout.

The events this repo uses:

| Event | Fires | Can it block? | What we use it for |
|---|---|---|---|
| `sessionStart` | session begins | no | inject the gate policy summary as context |
| `preToolUse` | before each tool runs | **yes — allow / deny / ask** | the enforcement point for all 16 gates |
| `postToolUseFailure` | after a tool fails | no, but can inject context | feed `retry-worth-it` guidance back to the model |
| `agentStop` | main agent finishes a turn | **yes — force another turn** | `verification-sufficient`, opt-in |

Other events exist (`postToolUse`, `permissionRequest`, `subagentStart`,
`subagentStop`, `preCompact`, `userPromptSubmitted`, `userPromptTransformed`,
`notification`, `errorOccurred`, `sessionEnd`). See §7 for the ones worth
knowing about.

Hooks load from several places and are **combined**, not overridden — policy,
then repository, then user, then plugins. When the same event appears in
multiple sources, every hook entry runs. There is no "my hook wins".

```
/etc/github-copilot/policy.d/*.json     # machine-wide, root-owned, cannot be disabled
.github/hooks/*.json                    # repository
~/.copilot/hooks/*.json                 # user
.github/copilot/settings.json           # inline "hooks" block
~/.copilot/settings.json                # inline "hooks" block
<plugin>/hooks/hooks.json               # plugins  <- this repo
```

This repo ships as a **plugin**, so the gates travel with the plugin install
and do not require the user to hand-edit settings.

---

## 2. Trap one: the timeout asymmetry

This is the single most important thing in this document, and it is the one
that had a real bug in this repo.

For a command `preToolUse` hook:

- A **crash or non-zero exit is fail-CLOSED.** The tool call is denied — even
  if the hook's stdout said `"permissionDecision": "allow"`. A hook that throws
  an exception blocks the tool.
- A **timeout is fail-OPEN.** The tool call proceeds through the normal
  permission flow. This is true *even for admin-deployed policy hooks*.

Those two are opposite directions, and the difference is the one variable a
gate does not fully control: how long the network takes.

The consequence for a safety gate is sharp:

> A safety gate that calls a remote decision service cannot rely on being
> allowed to finish. If the call is slow, the gate is killed, and being killed
> means the dangerous tool call goes ahead.

**The bug this repo had.** `gates/common/jev_client.py` defaulted to a 60-second
HTTP timeout. `hooks.json` gave `preToolUse` a `timeoutSec` of 10. So a slow or
hanging Jev endpoint meant the hook was killed at 10s, the timeout was treated
as fail-open, and a `destructive-action` or `secret-exposure` gate would let the
call through — silently, with no error, precisely when the network was unhealthy.

**The fix**, in `harness.py`:

```python
DEFAULT_HOOK_TIMEOUT_S = 10.0
GATE_BUDGET_FRACTION = 0.6          # -> 6s of network, 4s of headroom
```

The gate's network call is constrained to a fraction of the hook budget, so the
gate always has time to reach its *own* fail-mode decision — fail-closed for
safety gates — and emit it, rather than being killed into fail-open. Verified
in-repo by `TimeoutBudgetTests`.

**The general rule.** Push every decision you can make locally *before* the
network call, because local decisions cannot time out. In this repo the hard
rules — read-only channel policy, the retry cap, clean-tree-before-spawn — are
all evaluated before Jev is contacted, and they return `source=policy`. A Jev
outage cannot unblock them. That was originally a latency optimisation; the
timeout asymmetry is what makes it a security property.

---

## 3. Trap two: stdout is parsed once, not per line

Progress lines look line-oriented, so it is natural to assume the whole
protocol is:

```bash
echo '{"type":"progress","message":"Checking policy...","temporary":true}'
echo '{"permissionDecision":"allow"}'
```

What actually happens: the CLI scans stdout line by line and removes lines that
are a complete JSON object with `"type":"progress"`. **Everything else is kept
verbatim, concatenated, trimmed, and parsed with a single `JSON.parse`.**

So:

- Emitting two decision objects produces `{...}{...}`, which is invalid JSON.
  The hook is treated as having produced *no* output and falls through to
  default behaviour. Your deny silently evaporates. **Emit exactly one.**
- A stray `print()` for debugging is not ignored — it is concatenated into the
  JSON and breaks the parse. Debug output must go to stderr.
- A pretty-printed, multi-line progress object is *not* recognised as progress,
  so it stays in the stream and corrupts the parse. Progress objects must be
  one line each.
- The final decision object *may* span multiple lines. Only progress
  recognition is line-oriented.

Combined with §2, this yields the rule every hook script in this repo follows:

> **Always exit 0. Print exactly one JSON object on stdout. Send everything
> else to stderr.**

Exiting non-zero to signal "deny" technically works for `preToolUse`, but it
conflates *deny* with *crashed*, and it gives up the ability to attach a
`permissionDecisionReason`. We always deny explicitly, in JSON.

---

## 4. Trap three: two payload shapes, chosen by how you spell the event

The event name in your config decides the payload format you receive:

| Config event name | Payload style | Tool name field | Tool name value |
|---|---|---|---|
| `preToolUse` (camelCase) | camelCase | `toolName` | runtime name — `bash` |
| `PreToolUse` (PascalCase) | snake_case | `tool_name` | **Claude name — `Bash`** |

The PascalCase form is for VS Code / Claude Code plugin compatibility, and it
changes three things at once: the field names, the *tool names themselves*, and
the matcher semantics.

The tool name remapping is the part that bites:

| Runtime | Claude |
|---|---|
| `bash`, `powershell` | `Bash` |
| `view` | `Read` |
| `create` | `Write` |
| `edit`, `str_replace_editor`, `apply_patch` | `Edit` |
| `grep`, `rg` | `Grep` |
| `glob` | `Glob` |
| `web_fetch` / `web_search` | `WebFetch` / `WebSearch` |
| `ask_user` | `AskUserQuestion` |
| `task` | `Agent` (`Task` also accepted) |

So a `PreToolUse` hook with `"matcher": "bash"` matches **nothing**, because the
name it is tested against is `Bash`. The gate appears installed, fires never,
and fails open by omission — the worst failure mode, because nothing errors.

This repo uses **camelCase event names throughout**, and therefore native
matcher semantics against runtime tool names. If you port these hooks to a
Claude-format plugin, the matcher in `hooks.json` must be rewritten.

To be robust either way, read fields through a helper that accepts both:

```python
def field(payload, camel, snake, default=None):
    if camel in payload:
        return payload[camel]
    return payload.get(snake, default)
```

**Matcher semantics, native (camelCase):** the `matcher` value is a regex,
compiled as `^(?:PATTERN)$`, tested against the tool name, and must match in
full. An invalid regex means the hook is **skipped**, not errored — another
silent fail-open. Omit `matcher` to receive every tool.

---

## 5. Trap four: `agentStop` can loop, and the guard is not yours

`agentStop` with `{"decision":"block","reason":"..."}` forces another agent
turn, using `reason` as the prompt. This is how `verification-sufficient`
refuses a "done" claim that nothing has verified.

It is also an obvious way to build an infinite loop: block, model responds,
block again, forever — burning tokens on every iteration.

Two things bound it:

- **The CLI's runaway guard.** After **8 consecutive** `block` continuations,
  the CLI overrides the hook and ends the turn regardless. You cannot hold a
  session hostage — but 8 forced frontier-model turns is still real money.
- **`stop_hook_active`.** This input field is `true` when the current turn was
  already forced by a prior block from this hook. Use it to self-limit long
  before hitting the cap.

In this repo `agentStop` blocking is **opt-in** via
`COPILOT_JEV_VERIFY_ON_STOP`, and self-limits on `stop_hook_active`. A gate
that can spend the user's money in a loop should not be on by default.

Note also that `agentStop` fires on *every* turn end. A gate here is on the
hot path of the entire session, so it must be cheap when it has nothing to say.

---

## 6. What a `preToolUse` decision can say

```typescript
{
    permissionDecision?: "allow" | "deny" | "ask";
    permissionDecisionReason?: string;   // REQUIRED when denying
    modifiedArgs?: object;               // substitute the tool's arguments
}
```

Three notes that matter for gate design:

1. **`modifiedArgs` means a gate does not have to be binary.** This repo uses it
   for large reads: `view` is deliberately *ungated* in general (it averages
   908ms, so gating every read would be net-negative), but an **unbounded read
   of a large file** is intercepted and rewritten to a bounded `view_range`
   rather than refused. The pre-filter is a local `stat`, costing microseconds,
   so the expensive gate only runs on reads that are themselves expensive.
   Redirecting costs the model nothing and avoids a retry loop — strictly
   better than denying and hoping it adapts. Verified in-repo by
   `LargeReadRewriteTests`.

   Note the layering this implies: the **gate** decides the strategy
   (`ranged_read`), and the **harness** knows how to express that strategy as
   this particular tool's arguments. Gates stay tool-agnostic; only the harness
   knows that `view` takes a `view_range`.
2. **`deny` requires a reason, and the reason is the whole product.** It is fed
   back to the model as the explanation. "Blocked by policy" teaches nothing and
   invites a retry. "This file is already in context from turn 12; re-reading it
   costs ~3k tokens" changes the next action. Gate reasons should name the
   cheaper alternative.
3. **`ask` is not universally available.** Under Copilot cloud agent there is no
   user, so `ask` is treated as `deny`. That is what makes it safe for this repo
   to downgrade fixture-backed blocks to `ask`: interactively a human adjudicates,
   and non-interactively it fails safe.

### Why fixture-backed blocks return `ask`, not `deny`

A gate running in `JEV_MODE=fixture` is replaying a recorded answer. That is
good enough to prove plumbing and to demo offline, but it is **not live evidence
about the actual call in front of it**. Denying on a replayed answer would be
asserting more confidence than we have. So fixture results that would block
return `ask` instead, and every result carries its `source` (`live`, `fixture`,
or `policy`) so no reader has to guess which they are looking at.

`source=policy` is the exception: a hard rule is deterministic local logic, not
a replayed answer, so it denies with full confidence.

---

## 7. Other events worth knowing

- **`permissionRequest`** fires *before* the permission service — before rules,
  session approvals and prompting — and can short-circuit it with
  `{"behavior":"allow"|"deny","message":...,"interrupt":true}`. It is CLI-only,
  and it is the better hook for CI / pipe mode (`-p`) where no prompt can be
  shown. For command hooks here, **exit code 2 means deny**. One asymmetry:
  for a sandbox-bypass request, an `allow` does *not* pre-approve the escape —
  only `deny` propagates.
- **`postToolUse`** can rewrite a tool result via `modifiedResult`, or append
  guidance via `additionalContext` (joined with double newlines, **capped at
  10 KB**). Returning `modifiedResult` with `resultType:"failure"` routes the
  result onward to `postToolUseFailure`.
- **`subagentStop`** supports `modifiedResponse`, which rewrites what the
  subagent returns to its parent — the natural place to redact subagent output.
  Rewrites do **not** compose: every hook sees the original response and the
  last writer wins, so you cannot chain a redactor into a formatter.
- **`subagentStart` / `subagentStop` do not fire for the built-in
  `general-purpose` agent.** They do fire for `explore`, `task`, `code-review`,
  `rubber-duck`, `research`, `security-review` and user-defined agents. A
  subagent-governance gate that only watches these events has a blind spot
  exactly where this repo's own heaviest delegation happens.
- **`sessionStart` `prompt` entries** fire only for **new interactive**
  sessions — not on resume, not under `-p`. Context injection via
  `additionalContext` is the portable choice.

Hook output is bounded at **10 MiB** per invocation; larger responses are
truncated rather than exhausting memory.

---

## 8. The rules this repo follows

Distilled, for anyone writing a gate hook:

1. **Always exit 0.** Non-zero on `preToolUse` denies the call, including when
   you did not mean to deny.
2. **Print exactly one JSON object.** Debug to stderr, never stdout.
3. **Keep the network call well inside `timeoutSec`,** because a timeout is
   fail-open and will bypass your safety gate.
4. **Decide locally before you decide remotely.** Hard rules cannot time out,
   cannot be rate-limited, and cannot be unblocked by an outage.
5. **Use camelCase event names** unless you are deliberately targeting Claude
   compatibility — and if you are, remap every tool name in your matcher.
6. **Prefer `modifiedArgs` to `deny`** when a cheaper correct action exists.
7. **Make the deny reason name the alternative.** The reason is the only thing
   the model learns from.
8. **Never loop `agentStop` by default.** Gate it behind an env var and
   self-limit on `stop_hook_active`.
9. **Label every decision with its source.** A replayed answer is not evidence.

---

## 9. What has been observed, and what is still unverified

Honesty about the edges of this document:

### Observed against a running CLI

The plugin-loading and hook-expansion behaviour below was observed on macOS with
`/opt/homebrew/bin/copilot`. The first scratch expansion run logged `Starting
Copilot CLI: 1.0.88-1`; subsequent scratch-deny and repo-plugin runs logged
`Starting Copilot CLI: 1.0.89-0`, which is also what `copilot --version`
reported after the probes.

- **`${PLUGIN_ROOT}` expands inside `args` for command hooks.** This was tested
  with a session-scoped scratch plugin mounted via `--plugin-dir`. Its hook used
  the same shape as this repo:

  ```json
  {
    "type": "command",
    "exec": "python3",
    "args": ["${PLUGIN_ROOT}/hooks/probe.py", "${PLUGIN_ROOT}", "preToolUse-args"]
  }
  ```

  Prompt-mode runs invoked both `sessionStart` and `preToolUse`. The probe logs
  recorded `argv[0]` as the absolute `.../plugin-root-probe/hooks/probe.py`
  path and recorded the second argument as the absolute plugin root, not the
  literal string `${PLUGIN_ROOT}`. Existing installed plugins on this machine
  use `bash` / OS-specific command-string forms (`awesome-copilot/azure`) or
  relative `bash` with `cwd` (`copilot-cli-guideme`); those examples show the
  common working shapes, but the scratch probe is what verified `exec` + `args`.
- **This repo's plugin hook file parses and loads when mounted as a plugin.**
  `copilot --plugin-dir harness/copilot-jev-gates plugin list --json` listed
  `copilot-jev-gates` as an enabled external plugin. A prompt-mode run with the
  same `--plugin-dir` produced a debug log whose `Plugins loaded` entry included
  `copilot-jev-gates`, and `sessionStart` emitted this repo's
  `[jev-gates] 15 Jev gates are active...` `additionalContext`.
- **This repo's `preToolUse` hook fires.** In fixture mode, a prompt-mode run
  that asked Copilot to run `bash: true` emitted the hook progress line
  `{"type":"progress","message":"jev: tool-worth-it","temporary":true}` before
  the bash command completed. A second run with a harmless scratch-path command
  matching the destructive pattern (`rm -rf <nonexistent scratch path> && ...`)
  emitted `jev: destructive-action` and the final hook decision:

  ```json
  {
    "permissionDecision": "ask",
    "permissionDecisionReason": "Blocked by Jev gate 'destructive-action' (source=fixture): ..."
  }
  ```

  In non-interactive prompt mode, the CLI could not request permission, so the
  bash command was not executed and the scratch marker file remained empty.
- **A command `preToolUse` hook can deny a tool call.** The same scratch plugin
  returned:

  ```json
  {
    "permissionDecision": "deny",
    "permissionDecisionReason": "probe denial: preToolUse hook executed and denied this bash call"
  }
  ```

  Copilot reported that the bash call was denied, and the target scratch file
  stayed at 0 bytes. This verifies the CLI's deny semantics independently of
  this repo's fixture-mode choice to downgrade fixture-backed blocks to `ask`.

### Still unverified

- **Aggregate gate latency has now been measured** — see
  [`../experiments/latency/RESULTS.md`](../experiments/latency/RESULTS.md).
  End-to-end hook cost is ~40ms ungated and ~86ms for a fixture-mode gate, not
  the ~300–500ms previously assumed here; Python interpreter startup (~42.7ms)
  is the dominant term. What remains unmeasured is **live Jev network latency**,
  since no API key was available, so the break-even model assumes 400ms rather
  than measuring it.
- **No live Jev run has been performed.** `TYPESAFE_API_KEY` was unavailable, so
  every result in this repo is `fixture` or `policy`. The live-proof step is
  blocked, not done.
