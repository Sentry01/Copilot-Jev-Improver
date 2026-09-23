#!/usr/bin/env python3
"""agentStop hook — refuse an unverified "done".

Fires when the main agent finishes a turn. Returning ``{"decision": "block",
"reason": ...}`` forces another turn using the reason as the prompt, which makes
this the enforcement point for ``verification-sufficient``: if the agent is
about to claim completion without having proven it, send it back to work.

Guardrails, in order of importance:

* **Self-limit.** Copilot CLI overrides the hook after 8 consecutive blocks.
  Relying on that cap is not a design. ``stop_hook_active`` tells us this turn
  was already forced once, so we block at most once and then let the turn end.
* **Fail open here, even though the gate is fail-closed.** ``verification-sufficient``
  fails closed in the sense of refusing to *assert* a verified outcome. That must
  not become an inescapable stop-block loop when the harness is broken, which
  would leave the user unable to end a turn at all.
* **Off by default.** Blocking a turn is the most intrusive thing in this repo,
  so it is opt-in via ``COPILOT_JEV_VERIFY_ON_STOP``.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import emit, field, read_payload, run_gate  # noqa: E402


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "on", "yes"}


def main() -> int:
    try:
        payload = read_payload()
    except Exception:
        emit({})
        return 0

    if not truthy(os.environ.get("COPILOT_JEV_VERIFY_ON_STOP")):
        emit({})
        return 0

    # Already forced to continue once this turn — let it end.
    if payload.get("stop_hook_active"):
        emit({})
        return 0

    try:
        state = {
            "claimed_outcome": "the agent is ending its turn, implying the work is complete",
            "changes_made": summarise_changes(field(payload, "cwd", "cwd") or ""),
            "verification_performed": "",
            "test_coverage": "unknown",
            "reversibility": "moderate",
        }
        outcome = run_gate("verification-sufficient", state)
    except Exception:
        emit({})
        return 0

    decision = outcome.get("decision") or outcome
    if decision.get("proceed", True):
        emit({})
        return 0

    emit(
        {
            "decision": "block",
            "reason": (
                "[jev: verification-sufficient] "
                f"{decision.get('reason', 'the completion claim is not supported by evidence')}. "
                "Before ending this turn, either run the check that would demonstrate the "
                "outcome, or state plainly which parts are unverified. Do not repeat the "
                "completion claim without one of those two things."
            ),
        }
    )
    return 0


def summarise_changes(cwd: str) -> str:
    """Cheap, bounded git probe. Never raises; the harness must not crash."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if out.returncode != 0:
            return "unknown"
        lines = [line for line in out.stdout.splitlines() if line.strip()]
        return f"{len(lines)} changed paths" if lines else "no uncommitted changes"
    except Exception:
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
