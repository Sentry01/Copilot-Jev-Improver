#!/usr/bin/env python3
"""tool-worth-it gate — thin wrapper around shared runner."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

GATE_DIR = Path(__file__).resolve().parent
ROOT = GATE_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.runner import decide as _decide  # noqa: E402
from common.runner import run_cli  # noqa: E402


def _state(client_result: dict[str, Any]) -> dict[str, Any]:
    request = client_result.get("request_sans_auth") or {}
    state = request.get("state") or {}
    return state if isinstance(state, dict) else {}


def should_gate(state: dict[str, Any]) -> bool:
    """Cheap-tool short-circuit: run this gate only for costly or slow tools."""
    try:
        est_latency_ms = int(state.get("est_latency_ms", 0) or 0)
    except (TypeError, ValueError):
        est_latency_ms = 0
    return est_latency_ms >= 2000 or state.get("est_cost_tier") != "low"


def _noul(answers: dict[str, Any], key: str) -> float | None:
    answer = answers.get(key) or {}
    if not isinstance(answer, dict):
        return None
    value = answer.get("noul")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _choice(answers: dict[str, Any], key: str) -> str | None:
    answer = answers.get(key) or {}
    return answer.get("choice") if isinstance(answer, dict) else None


def _default_decision(config: dict[str, Any], reason: str, *, signals: dict[str, Any]) -> dict[str, Any]:
    default = config.get("default_on_error") or {}
    fail_mode = (config.get("fail_mode") or "open").lower()
    return {
        "action": default.get("action", "run_tool"),
        "proceed": bool(default.get("proceed", True)),
        "reason": f"fail-{fail_mode} on missing/invalid Jev answer: {reason}",
        "fail_mode_applied": fail_mode,
        "signals": signals,
        "thresholds": config.get("thresholds") or {},
    }


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    min_worth = float(thresholds.get("tool_worth_it_min", 0.65))
    state = _state(client_result)
    gate_applies = should_gate(state)
    worth = _noul(answers, "tool_worth_it")
    blocker = _choice(answers, "primary_blocker")
    signals = {
        "tool_worth_it": worth,
        "primary_blocker": blocker,
        "est_latency_ms": state.get("est_latency_ms"),
        "est_cost_tier": state.get("est_cost_tier"),
        "gate_applies": gate_applies,
    }

    if not gate_applies:
        return {
            "action": "run_tool",
            "proceed": True,
            "reason": "short-circuit: est_latency_ms < 2000 and est_cost_tier is low, so the gate should not spend a Jev call",
            "signals": signals,
            "thresholds": thresholds,
        }

    if worth is None or not blocker:
        return _default_decision(config, "required tool-worth signal was absent", signals=signals)

    proceed = worth >= min_worth
    return {
        "action": "run_tool" if proceed else "skip_tool",
        "proceed": proceed,
        "reason": (
            f"tool_worth_it={worth:.2f} >= {min_worth:.2f}"
            if proceed
            else f"tool_worth_it={worth:.2f} < {min_worth:.2f}; primary_blocker={blocker}"
        ),
        "signals": signals,
        "thresholds": thresholds,
    }


def decide(state: dict) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=False)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate))
