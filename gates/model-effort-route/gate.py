#!/usr/bin/env python3
"""model-effort-route gate — thin wrapper around shared runner."""
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


def _score(answers: dict[str, Any], key: str) -> str | None:
    answer = answers.get(key) or {}
    value = answer.get("score") if isinstance(answer, dict) else None
    return str(value) if value is not None else None


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
        "action": default.get("action", "keep_current_tier"),
        "proceed": bool(default.get("proceed", True)),
        "reason": f"fail-{fail_mode} on missing/invalid Jev answer: {reason}",
        "fail_mode_applied": fail_mode,
        "signals": signals,
        "thresholds": config.get("thresholds") or {},
    }


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    needs_min = float(thresholds.get("needs_frontier_model_escalate_min", 0.8))
    needs_max = float(thresholds.get("needs_frontier_model_downgrade_max", 0.45))
    shallow_max_label = thresholds.get("downgrade_reasoning_depth_max", "shallow")
    deep_min_label = thresholds.get("escalate_reasoning_depth_min", "deep")

    needs = _noul(answers, "needs_frontier_model")
    depth = _score(answers, "reasoning_depth")
    depth_idx = _score_index(config, "reasoning_depth", depth)
    shallow_idx = _score_index(config, "reasoning_depth", shallow_max_label)
    deep_idx = _score_index(config, "reasoning_depth", deep_min_label)
    recommended = _choice(answers, "recommended_tier")
    state = _state(client_result)
    current_tier = state.get("current_tier")
    try:
        prior_attempts = int(state.get("prior_attempts", 0) or 0)
    except (TypeError, ValueError):
        prior_attempts = 0

    signals = {
        "needs_frontier_model": needs,
        "reasoning_depth": depth,
        "reasoning_depth_index": depth_idx,
        "recommended_tier": recommended,
        "current_tier": current_tier,
        "prior_attempts": prior_attempts,
    }
    if None in (needs, depth_idx, shallow_idx, deep_idx) or not recommended:
        return _default_decision(config, "required routing signal was absent", signals=signals)

    may_downgrade = needs < needs_max and depth_idx <= shallow_idx and prior_attempts == 0
    would_downgrade_but_prior_failure = needs < needs_max and depth_idx <= shallow_idx and prior_attempts > 0
    should_escalate = needs >= needs_min and depth_idx >= deep_idx

    if may_downgrade:
        action = "downgrade"
        target_tier = recommended
        reason = (
            f"needs_frontier_model={needs:.2f} < {needs_max:.2f} and "
            f"reasoning_depth={depth} <= {shallow_max_label}; prior_attempts=0"
        )
    elif should_escalate:
        action = "escalate"
        target_tier = recommended
        reason = (
            f"needs_frontier_model={needs:.2f} >= {needs_min:.2f} and "
            f"reasoning_depth={depth} >= {deep_min_label}"
        )
    else:
        action = "keep_current_tier"
        target_tier = current_tier
        if would_downgrade_but_prior_failure:
            reason = (
                f"downgrade signals present but prior_attempts={prior_attempts}; "
                "after a failed attempt, never downgrade"
            )
        else:
            reason = (
                f"routing signals do not cross asymmetric thresholds; "
                f"needs_frontier_model={needs:.2f}, reasoning_depth={depth}"
            )

    return {
        "action": action,
        "proceed": True,
        "reason": reason,
        "target_tier": target_tier,
        "signals": signals,
        "thresholds": thresholds,
    }


def decide(state: dict) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=False)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate))
