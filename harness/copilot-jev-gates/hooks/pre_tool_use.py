#!/usr/bin/env python3
"""preToolUse hook — the enforcement point for the gate library.

Copilot CLI runs this before every tool call and reads a single JSON decision
object from stdout: ``allow``, ``deny`` (with a required reason), or ``ask``.

Two failure semantics are in play here and they are not the same thing:

* **Copilot's semantics.** A crashed or non-zero-exit ``preToolUse`` command
  hook is treated as a *deny*. A timeout is treated as an *allow*. So this
  script must always exit 0 and always print exactly one decision.
* **The gate's semantics.** Each gate's ``fail_mode`` describes what to do when
  *Jev* is unreachable — independent of whether this hook ran correctly.

The bridge between them: if the harness itself breaks while handling a call that
a safety gate claimed, deny. If it breaks on a cost gate, allow. Never let an
infrastructure problem silently permit a destructive or externally visible
action, and never let one block ordinary work.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import (  # noqa: E402
    CHEAP_TOOLS,
    allow,
    ask,
    deny,
    emit,
    field,
    log_decision,
    progress,
    ranged_read_args,
    read_payload,
    route_pre_tool_use,
    run_gate,
    unbounded_large_read,
    violates_read_only,
)

SAFETY_SLUGS = frozenset({"destructive-action", "secret-exposure", "external-write", "prompt-injection"})


def main() -> int:
    try:
        payload = read_payload()
    except Exception:
        emit(allow())
        return 0

    tool_name = field(payload, "toolName", "tool_name") or ""
    tool_args = field(payload, "toolArgs", "tool_input")
    cwd = field(payload, "cwd", "cwd") or ""

    # Hard rule, checked before any gate: a standing read-only integration is
    # never writable, and no calibrated score may overrule that.
    if violates_read_only(tool_name):
        emit(
            deny(
                f"Blocked by standing read-only policy: {tool_name} is a write-shaped call "
                "against an integration configured as read-only. This is a policy rule, not a "
                "judgement call. Use a read, search or list operation instead, or ask the user "
                "to perform the write themselves."
            )
        )
        return 0

    # Cheap tools are not worth a ~300-500ms gate. The one exception is an
    # unbounded read of a large file: `view` is cheap in wall-clock but the
    # context it pulls in is the dominant cost driver (input:output = 260.8:1).
    # The exception is detected with a local stat, so the common case stays free.
    if tool_name in CHEAP_TOOLS and unbounded_large_read(tool_name, tool_args) is None:
        emit(allow())
        return 0

    route = route_pre_tool_use(tool_name, tool_args, cwd)
    if route is None:
        emit(allow())
        return 0

    slug, build_state = route
    is_safety = slug in SAFETY_SLUGS

    try:
        progress(f"jev: {slug}")
        outcome = run_gate(slug, build_state(payload))
    except Exception as exc:
        if is_safety:
            emit(
                deny(
                    f"Safety gate '{slug}' could not be evaluated ({type(exc).__name__}). "
                    "Blocking rather than proceeding on an unverified irreversible action. "
                    "Re-run once the gate harness is healthy, or perform this step manually."
                )
            )
        else:
            emit(allow())
        return 0

    decision = to_decision(slug, outcome, tool_name, tool_args)
    log_decision(slug, outcome, decision, tool_name)
    emit(decision)
    return 0


def to_decision(slug: str, outcome: dict, tool_name: str = "", tool_args: object = None) -> dict:
    decision = outcome.get("decision") or {}
    proceed = decision.get("proceed", outcome.get("proceed", True))
    reason = decision.get("reason") or outcome.get("reason") or "no reason supplied"
    source = outcome.get("source", "unknown")
    action = decision.get("action") or outcome.get("action") or "skip"

    if proceed:
        modified = decision.get("modified_args") or outcome.get("modified_args")
        result = allow()
        # A gate decides the *strategy*; the harness knows how to express that
        # strategy as this particular tool's arguments. Rewriting the call is
        # strictly better than allowing a wasteful one: same turn, capped cost.
        if not modified and action == "ranged_read" and isinstance(tool_args, dict):
            if unbounded_large_read(tool_name, tool_args) is not None:
                modified = ranged_read_args(tool_args)
        if isinstance(modified, dict) and modified:
            result["modifiedArgs"] = modified
        return result

    message = (
        f"Blocked by Jev gate '{slug}' (source={source}): {reason}. "
        f"Suggested action: {action}. "
        "Do not simply retry the identical call — address the reason, or explain to the user "
        "why the call is necessary anyway."
    )

    # A fixture-sourced block is a recorded answer, not live evidence, so it is
    # surfaced to the user instead of being enforced silently.
    if source == "fixture":
        return ask(message)
    return deny(message)


if __name__ == "__main__":
    raise SystemExit(main())
