#!/usr/bin/env python3
"""stop-vs-continue gate — thin wrapper around shared runner."""
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


def _noul(answers: dict[str, Any], key: str) -> float | None:
    answer = answers.get(key) or {}
    if not isinstance(answer, dict):
        return None
    value = answer.get("noul")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _score(answers: dict[str, Any], key: str) -> str | None:
    answer = answers.get(key) or {}
    value = answer.get("score") if isinstance(answer, dict) else None
    return str(value) if value is not None else None


def _choice(answers: dict[str, Any], key: str) -> str | None:
    answer = answers.get(key) or {}
    return answer.get("choice") if isinstance(answer, dict) else None


def _score_index(config: dict[str, Any], key: str, value: str | None) -> int | None:
    criteria = (((config.get("questions") or {}).get(key) or {}).get("criteria") or [])
    if value is None or not isinstance(criteria, list):
        return None
    try:
        return criteria.index(value)
    except ValueError:
        return None


def _default_decision(config: dict[str, Any], reason: str, *, signals: dict[str, Any]) -> dict[str, Any]:
    default = config.get("default_on_error") or {}
    fail_mode = (config.get("fail_mode") or "open").lower()
    return {
        "action": default.get("action", "continue"),
        "proceed": bool(default.get("proceed", True)),
        "reason": f"fail-{fail_mode} on missing/invalid Jev answer: {reason}",
        "fail_mode_applied": fail_mode,
        "signals": signals,
        "thresholds": config.get("thresholds") or {},
    }


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    should_stop_min = float(thresholds.get("should_stop_min", 0.6))
    marginal_min_label = thresholds.get("marginal_value_continue_min", "modest")

    should_stop = _noul(answers, "should_stop")
    marginal_value = _score(answers, "marginal_value")
    marginal_idx = _score_index(config, "marginal_value", marginal_value)
    modest_idx = _score_index(config, "marginal_value", marginal_min_label)
    stop_reason = _choice(answers, "stop_reason")

    signals = {
        "should_stop": should_stop,
        "marginal_value": marginal_value,
        "marginal_value_index": marginal_idx,
        "stop_reason": stop_reason,
    }
    if None in (should_stop, marginal_idx, modest_idx) or not stop_reason:
        return _default_decision(config, "required stop signal was absent", signals=signals)

    stop_by_belief = should_stop >= should_stop_min
    stop_by_marginal = marginal_idx < modest_idx
    should_halt_current_line = stop_by_belief or stop_by_marginal

    if should_halt_current_line and stop_reason == "wrong_approach":
        action = "replan"
        proceed = False
        reason = (
            f"stop triggered (should_stop={should_stop:.2f}, marginal_value={marginal_value}); "
            "stop_reason=wrong_approach so re-plan instead of silently stopping"
        )
    elif should_halt_current_line:
        action = "stop"
        proceed = False
        reason = (
            f"stop triggered: should_stop={should_stop:.2f} >= {should_stop_min:.2f} "
            f"or marginal_value={marginal_value} < {marginal_min_label}; stop_reason={stop_reason}"
        )
    else:
        action = "continue"
        proceed = True
        reason = (
            f"continue: should_stop={should_stop:.2f} < {should_stop_min:.2f} and "
            f"marginal_value={marginal_value} >= {marginal_min_label}"
        )

    return {
        "action": action,
        "proceed": proceed,
        "reason": reason,
        "signals": signals,
        "thresholds": thresholds,
    }


def decide(state: dict) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=False)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate))
