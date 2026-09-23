#!/usr/bin/env python3
"""subagent-spawn gate — local shared-tree hard rule plus shared runner."""
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


def _score_index(answers: dict, config: dict, key: str) -> tuple[int | None, str | None]:
    criteria = (((config.get("questions") or {}).get(key) or {}).get("criteria") or [])
    answer = answers.get(key) or {}
    legend = answer.get("legend")
    score = answer.get("score")
    if isinstance(legend, str) and legend in criteria:
        return criteria.index(legend), legend
    if isinstance(score, str) and score in criteria:
        return criteria.index(score), score
    if isinstance(score, (int, float)):
        idx = int(round(float(score)))
        if 0 <= idx < len(criteria):
            return idx, criteria[idx]
    probabilities = answer.get("probabilities") or {}
    if isinstance(probabilities, dict):
        labels = [(label, probabilities.get(label)) for label in criteria]
        labels = [(label, prob) for label, prob in labels if isinstance(prob, (int, float))]
        if labels:
            label = max(labels, key=lambda item: item[1])[0]
            return criteria.index(label), label
    return None, None


def _state(client_result: dict) -> dict:
    request = client_result.get("request_sans_auth") or {}
    state = request.get("state") or {}
    return state if isinstance(state, dict) else {}


def _shared_tree_decision(config: dict, state: dict) -> dict:
    thresholds = config.get("thresholds") or {}
    return {
        "action": "require_clean_tree_first",
        "proceed": False,
        "reason": "writes_to_shared_tree=true; require clean or committed tree before spawning",
        "spawn_justified": None,
        "spawn_reason": None,
        "expected_multiplier": None,
        "expected_multiplier_index": None,
        "spawn_kind": state.get("spawn_kind"),
        "writes_to_shared_tree": state.get("writes_to_shared_tree"),
        "thresholds": thresholds,
        "hard_rule_applied": "writes_to_shared_tree",
    }


def hard_rule(state: dict, config: dict) -> dict | None:
    if isinstance(state, dict) and state.get("writes_to_shared_tree") is True:
        return _shared_tree_decision(config, state)
    return None


def evaluate(answers: dict, config: dict, client_result: dict) -> dict:
    state = _state(client_result)
    policy_decision = hard_rule(state, config)
    if policy_decision is not None:
        return policy_decision

    thresholds = config.get("thresholds") or {}
    spawn_min = float(thresholds.get("spawn_justified_min", 0.65))
    blocked_reason = thresholds.get("blocked_spawn_reason", "underspecified")
    factory_reason = thresholds.get("factory_fleet_requires_reason", "true_parallelism")
    factory_max = thresholds.get("factory_fleet_max_multiplier", "5x")
    criteria = (((config.get("questions") or {}).get("expected_multiplier") or {}).get("criteria") or [])
    factory_max_idx = criteria.index(factory_max) if factory_max in criteria else None

    spawn_noul = _noul(answers, "spawn_justified")
    reason = _choice(answers, "spawn_reason")
    multiplier_idx, multiplier = _score_index(answers, config, "expected_multiplier")
    spawn_kind = state.get("spawn_kind")
    base = {
        "spawn_justified": spawn_noul,
        "spawn_reason": reason,
        "expected_multiplier": multiplier,
        "expected_multiplier_index": multiplier_idx,
        "spawn_kind": spawn_kind,
        "writes_to_shared_tree": state.get("writes_to_shared_tree"),
        "thresholds": thresholds,
    }

    if spawn_noul is None or reason is None:
        default = config.get("default_on_error") or {"action": "spawn", "proceed": True}
        return {
            "action": default.get("action", "spawn"),
            "proceed": bool(default.get("proceed", True)),
            "reason": "missing spawn_justified or spawn_reason; fail-open",
            "fail_mode_applied": "open",
            **base,
        }

    base_allowed = spawn_noul >= spawn_min and reason != blocked_reason
    if spawn_kind == "factory_fleet" and base_allowed:
        factory_allowed = reason == factory_reason and multiplier_idx is not None and factory_max_idx is not None and multiplier_idx <= factory_max_idx
        return {
            "action": "spawn_factory_fleet" if factory_allowed else "spawn_narrower_or_inline",
            "proceed": factory_allowed,
            "reason": (
                f"factory fleet allowed: spawn_justified={spawn_noul} >= {spawn_min}; reason={reason}; expected_multiplier={multiplier} <= {factory_max}"
                if factory_allowed
                else f"factory fleet blocked: requires reason={factory_reason} and expected_multiplier <= {factory_max}; got reason={reason}, multiplier={multiplier}"
            ),
            **base,
        }

    spawn = base_allowed
    return {
        "action": "spawn" if spawn else "inline",
        "proceed": spawn,
        "reason": (
            f"spawn: spawn_justified={spawn_noul} >= {spawn_min}; spawn_reason={reason}"
            if spawn
            else f"inline: spawn_justified={spawn_noul} (min {spawn_min}) spawn_reason={reason} (blocked reason {blocked_reason})"
        ),
        **base,
    }


def decide(state: dict, *, write_dry: bool = False) -> dict:
    """Importable: decide(state) -> outcome dict (includes decision + answers)."""
    return _decide(GATE_DIR, state, evaluate, write_dry=write_dry, hard_rule=hard_rule)


if __name__ == "__main__":
    raise SystemExit(run_cli(GATE_DIR, evaluate, hard_rule=hard_rule))
