#!/usr/bin/env python3
"""retry-worth-it gate — local retry hard-stop plus shared runner."""
from __future__ import annotations

import sys
from pathlib import Path

GATE_DIR = Path(__file__).resolve().parent
ROOT = GATE_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.runner import decide as _decide  # noqa: E402
from common.runner import run_cli  # noqa: E402


def _noul(answers: dict, key: str) -> float | None:
    value = (answers.get(key) or {}).get("noul")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _choice(answers: dict, key: str) -> str | None:
    value = (answers.get(key) or {}).get("choice")
    return value if isinstance(value, str) else None


def _state(client_result: dict) -> dict:
    request = client_result.get("request_sans_auth") or {}
    state = request.get("state") or {}
    return state if isinstance(state, dict) else {}


def _attempt(state: dict) -> int:
    try:
        return int(state.get("attempt_number") or 0)
    except (TypeError, ValueError):
        return 0


def _hard_stop_decision(config: dict, state: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    hard_stop = int(thresholds.get("hard_stop_attempt_number", 3))
    return {
        "action": "hard_stop",
        "proceed": False,
        "reason": f"attempt_number={_attempt(state)} >= {hard_stop}; hard-stop before retry",
        "retry_will_succeed": None,
        "failure_class": None,
        "next_action": None,
        "attempt_number": _attempt(state),
        "change_since_last_attempt": state.get("change_since_last_attempt"),
        "thresholds": thresholds,
        "hard_rule_applied": "attempt_number_cap",
    }


def hard_rule(state: dict, config: dict) -> dict | None:
    thresholds = config.get("thresholds") or {}
    hard_stop = int(thresholds.get("hard_stop_attempt_number", 3))
    if isinstance(state, dict) and _attempt(state) >= hard_stop:
        return _hard_stop_decision(config, state)
    return None


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    state = _state(client_result)
    policy_decision = hard_rule(state, config)
    if policy_decision is not None:
        return policy_decision

    thresholds = config.get("thresholds") or {}
    retry_min = float(thresholds.get("retry_will_succeed_min", 0.55))
    forbidden = set(thresholds.get("retry_same_forbidden_failure_classes", ["auth", "unsupported"]))
    attempt = _attempt(state)
    change = (state.get("change_since_last_attempt") or "").strip()

    retry_noul = _noul(answers, "retry_will_succeed")
    failure_class = _choice(answers, "failure_class")
    next_action = _choice(answers, "next_action")
    base = {
        "retry_will_succeed": retry_noul,
        "failure_class": failure_class,
        "next_action": next_action,
        "attempt_number": attempt,
        "change_since_last_attempt": change,
        "thresholds": thresholds,
    }

    if failure_class in forbidden and next_action == "retry_same":
        return {
            "action": "ask_user" if failure_class == "auth" else "switch_tool",
            "proceed": False,
            "reason": f"retry_same forbidden for failure_class={failure_class}; choose a different path",
            "hard_rule_applied": "no_retry_same_for_auth_or_unsupported",
            **base,
        }

    if not change:
        return {
            "action": next_action if next_action in {"switch_tool", "ask_user", "abandon"} else "do_not_retry",
            "proceed": False,
            "reason": "change_since_last_attempt is empty; retry threshold cannot be satisfied",
            **base,
        }

    if retry_noul is None:
        default = config.get("default_on_error") or {"action": "retry_adjusted", "proceed": True}
        return {
            "action": default.get("action", "retry_adjusted"),
            "proceed": bool(default.get("proceed", True)),
            "reason": "missing retry_will_succeed; fail-open because a material change is present",
            "fail_mode_applied": "open",
            **base,
        }

    should_retry = retry_noul >= retry_min and (next_action in {"retry_same", "retry_adjusted"} or next_action is None)
    action = next_action if next_action in {"retry_same", "retry_adjusted", "switch_tool", "ask_user", "abandon"} else "retry_adjusted"
    if should_retry:
        action = action if action in {"retry_same", "retry_adjusted"} else "retry_adjusted"
    return {
        "action": action if should_retry else (action if action not in {"retry_same", "retry_adjusted"} else "do_not_retry"),
        "proceed": should_retry,
        "reason": (
            f"retry: retry_will_succeed={retry_noul} >= {retry_min}; change_since_last_attempt is non-empty; next_action={action}"
            if should_retry
            else f"do not retry: retry_will_succeed={retry_noul} (min {retry_min}); next_action={next_action}; change_present={bool(change)}"
        ),
        **base,
    }


def decide(state: dict, *, write_dry: bool = False) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=write_dry, hard_rule=hard_rule)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate, hard_rule=hard_rule))
