#!/usr/bin/env python3
"""postToolUseFailure hook — recovery guidance instead of a blind retry.

Fires after a tool fails. It cannot block anything, but it can inject
``additionalContext`` that the model sees alongside the error, which is the
right shape for this problem: the goal is not to forbid the retry, it is to stop
the agent reflexively re-running a call that structurally cannot succeed.

Justified by the measured reliability of the browser tools — ``browser_click``
failed 78.6% of the time over 30 days, ``browser_navigate`` 59.6%. At those
rates a blind retry has negative expected value.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import emit, field, read_payload, run_gate  # noqa: E402

# Measured failure rates, used to inform the gate rather than to decide alone.
KNOWN_FAILURE_RATES = {
    "playwright-browser_click": 0.786,
    "playwright-browser_navigate": 0.596,
    "playwright-browser_type": 0.600,
    "kusto-explorer-kusto_mgmt_show": 0.185,
    "open_canvas": 0.162,
    "kusto-explorer-kusto_query_readonly": 0.132,
}

# Tools reliable enough that one failure is probably genuinely transient.
QUIET_TOOLS = frozenset({"edit", "create", "view", "glob", "grep"})


def main() -> int:
    try:
        payload = read_payload()
        tool_name = field(payload, "toolName", "tool_name") or ""
        if tool_name in QUIET_TOOLS:
            emit({})
            return 0

        error = str(field(payload, "error", "error") or "")
        rate = KNOWN_FAILURE_RATES.get(tool_name, 0.0)

        state = {
            "failed_tool": tool_name,
            "error_summary": error[:600],
            "attempt_number": 1,
            "change_since_last_attempt": "",
            "tool_historical_failure_rate": rate,
            "alternative_paths": "unknown",
        }
        outcome = run_gate("retry-worth-it", state)
    except Exception:
        emit({})
        return 0

    emit({"additionalContext": advice(tool_name, rate, outcome)})
    return 0


def advice(tool_name: str, rate: float, outcome: dict) -> str:
    decision = outcome.get("decision") or outcome
    action = decision.get("action") or "unknown"
    reason = decision.get("reason") or ""
    lines = [f"[jev: retry-worth-it] recommended next action: {action}. {reason}".strip()]
    if rate >= 0.5:
        lines.append(
            f"Note: {tool_name} has failed {rate:.0%} of the time in recorded telemetry. "
            "Repeating the same call is unlikely to help — change the approach or ask the user."
        )
    lines.append(
        "Before retrying, state what is actually different about this attempt. "
        "If nothing is different, do not retry."
    )
    return " ".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
