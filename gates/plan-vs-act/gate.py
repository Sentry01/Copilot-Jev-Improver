#!/usr/bin/env python3
"""plan-vs-act gate — thin wrapper around shared runner."""
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


def _score_index(answers: dict[str, Any], config: dict[str, Any], key: str) -> tuple[int | None, str | None]:
    answer = answers.get(key) or {}
    label = answer.get("score")
    criteria = ((config.get("questions") or {}).get(key) or {}).get("criteria") or []
    if label in criteria:
        return criteria.index(label), label
    return None, label


def _threshold_index(config: dict[str, Any], key: str, label: str) -> int:
    criteria = ((config.get("questions") or {}).get(key) or {}).get("criteria") or []
    return criteria.index(label)


def _fail_decision(config: dict[str, Any], message: str, **signals: Any) -> dict[str, Any]:
    default = config.get("default_on_error") or {}
    return {
        "action": default.get("action", "act_now"),
        "proceed": bool(default.get("proceed", True)),
        "reason": f"fail-open: {message}",
        "fail_mode_applied": config.get("fail_mode", "open"),
        **signals,
    }


def _state_from_client(client_result: dict[str, Any]) -> dict[str, Any]:
    request = client_result.get("request_sans_auth") or {}
    state = request.get("state") or {}
    return state if isinstance(state, dict) else {}


def _explicit_mode(value: Any) -> str | None:
    mode = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not mode or mode in {"unspecified", "none", "not_specified", "n/a"}:
        return None
    if mode in {"act", "act_now", "just_do_it", "do_it", "implement", "skip_plan", "no_plan"}:
        return "act_now"
    if mode in {"quick_outline", "outline", "brief_plan"}:
        return "quick_outline"
    if mode in {"plan", "plan_first", "full_plan", "make_a_plan"}:
        return "full_plan"
    if mode in {"ask", "clarify", "clarifying", "ask_clarifying_first"}:
        return "ask_clarifying_first"
    return None


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    needs_plan_min = float(thresholds.get("needs_plan_min", 0.6))
    ambiguity_plan_min = thresholds.get("ambiguity_plan_min", "high")
    ambiguity_blocking = thresholds.get("ambiguity_blocking", "blocking")
    ambiguity_plan_idx = _threshold_index(config, "ambiguity_level", ambiguity_plan_min)
    ambiguity_blocking_idx = _threshold_index(config, "ambiguity_level", ambiguity_blocking)

    state = _state_from_client(client_result)
    override_action = _explicit_mode(state.get("user_specified_mode"))
    if override_action is not None:
        return {
            "action": override_action,
            "proceed": override_action == "act_now",
            "reason": f"user_specified_mode override selected {override_action}; Jev result not allowed to override it",
            "user_specified_mode": state.get("user_specified_mode"),
            "override_applied": True,
            "thresholds": {
                "needs_plan_min": needs_plan_min,
                "ambiguity_plan_min": ambiguity_plan_min,
                "ambiguity_blocking": ambiguity_blocking,
            },
        }

    needs_plan = (answers.get("needs_plan") or {}).get("noul")
    ambiguity_idx, ambiguity_label = _score_index(answers, config, "ambiguity_level")
    recommended = (answers.get("recommended_mode") or {}).get("choice")

    if needs_plan is None or ambiguity_idx is None:
        return _fail_decision(
            config,
            "missing needs_plan or ambiguity_level",
            needs_plan=needs_plan,
            ambiguity_level=ambiguity_label,
            recommended_mode=recommended,
            thresholds={
                "needs_plan_min": needs_plan_min,
                "ambiguity_plan_min": ambiguity_plan_min,
                "ambiguity_blocking": ambiguity_blocking,
            },
        )

    should_plan = float(needs_plan) >= needs_plan_min or ambiguity_idx >= ambiguity_plan_idx
    if ambiguity_idx >= ambiguity_blocking_idx:
        action = "ask_clarifying_first"
    elif should_plan:
        action = recommended if recommended in {"quick_outline", "full_plan", "ask_clarifying_first"} else "full_plan"
    else:
        action = "act_now"

    return {
        "action": action,
        "proceed": action == "act_now",
        "reason": (
            f"{action}: needs_plan={needs_plan} (min {needs_plan_min}) and "
            f"ambiguity_level={ambiguity_label} (plan at {ambiguity_plan_min}); "
            f"recommended_mode={recommended}"
        ),
        "needs_plan": needs_plan,
        "ambiguity_level": ambiguity_label,
        "ambiguity_level_index": ambiguity_idx,
        "recommended_mode": recommended,
        "override_applied": False,
        "thresholds": {
            "needs_plan_min": needs_plan_min,
            "ambiguity_plan_min": ambiguity_plan_min,
            "ambiguity_plan_min_index": ambiguity_plan_idx,
            "ambiguity_blocking": ambiguity_blocking,
            "ambiguity_blocking_index": ambiguity_blocking_idx,
        },
    }


def decide(state: dict) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=False)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate))
